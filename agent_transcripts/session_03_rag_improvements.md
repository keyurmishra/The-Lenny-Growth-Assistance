# Session 03 — RAG Improvements (Context, Confidence, Hybrid Search)

**Date:** 2026-08-25  
**Goal:** Improve retrieval quality — handle follow-up questions properly, prevent hallucination from weak matches, and boost precision for exact terminology.

---

## Problem 1: Follow-up questions retrieve irrelevant chunks

### SYMPTOM
```
User:      "What does Lenny say about product-market fit?"
Assistant: [Good answer citing Brian Chesky, Andy Rachleff]

User:      "Can you give me an example?"
Assistant: [Generic answer about a completely unrelated topic]
```

### DIAGNOSIS
The second message "Can you give me an example?" is embedded as a 384-dim vector. The phrase "give me an example" has no semantic overlap with "product-market fit" — it's a generic follow-up phrase. The retrieval engine returned chunks about completely different topics that happened to include example-giving language.

The root cause: **retrieval was stateless** — it only saw the current message, not the conversation history.

### FIX: Query Rewriting

Added `_rewrite_query()` to `ChatService`:

```python
async def _rewrite_query(self, user_content: str, history: list) -> str:
    """
    If the query looks like a follow-up (short, starts with 'it'/'that'/'this',
    or contains anaphoric references), use the LLM to rewrite it as a
    self-contained search query before embedding.
    """
    if not history:
        return user_content  # First message is always clear

    # Heuristic: short messages or those starting with deictic references
    # are likely follow-ups that need context
    ambiguous_signals = ["it", "that", "this", "example", "more", "also", ...]
    needs_rewrite = (
        len(user_content.split()) < 12
        or any(user_content.lower().startswith(s) for s in ambiguous_signals)
    )

    if not needs_rewrite:
        return user_content  # Long, explicit questions don't need rewriting

    # Call LLM with last 2 turns of history + the follow-up
    # Returns: "Give an example of product-market fit from Lenny's Podcast"
    rewritten = await self._call_rewriter_llm(user_content, history[-4:])
    return rewritten or user_content  # Fallback to original on error
```

**Result:** Follow-up questions now retrieve contextually relevant chunks.

**Trade-off documented:** One extra LLM call per RAG query. At `max_tokens=80` and `temperature=0.0`, this adds ~100-200ms for Ollama, negligible for cloud providers. The quality improvement justifies the latency cost.

---

## Problem 2: Weak matches generating hallucinated answers

### SYMPTOM
```
User:      "What does Lenny say about quantum computing?"
Assistant: "Lenny's guests have discussed quantum computing in the context
           of future technology trends. Brian Chesky mentioned..."
```
(Brian Chesky never mentioned quantum computing. The model hallucinated a citation.)

### DIAGNOSIS
The retrieval service was using a `similarity_threshold = 0.30` — meaning any chunk with cosine similarity above 0.30 was included as context. The best-matching chunk for "quantum computing" had similarity 0.34 (a loose semantic match to "technology disruption"). The LLM received this weak context and hallucinated rather than acknowledging uncertainty.

The existing "No context found" path was never reached because 0.30 is too permissive.

### FIX: Confidence Threshold

Added a **second, higher threshold** (`confidence_threshold = 0.45`) in `RetrievalService`:

```python
# Two separate thresholds serve different purposes:
self.similarity_threshold = 0.30   # Noise cutoff — chunks below this are random
self.confidence_threshold = 0.45   # Confidence gate — below this, transcripts
                                   # don't reliably cover the topic

# In retrieve_with_context():
if check_confidence and chunks[0].similarity_score < self.confidence_threshold:
    logger.info("retrieval_below_confidence_threshold", ...)
    return [], ""  # → triggers "I don't have enough information" response
```

**Result:** Off-topic questions now correctly receive "I don't have enough information in Lenny's transcripts to answer this."

**Trade-off:** The threshold is a fixed value. Topics at the boundary (0.43–0.47 similarity) may be incorrectly rejected. Logged for monitoring so the threshold can be tuned with real user data.

---

## Problem 3: Exact-term queries returning semantically-adjacent but wrong results

### SYMPTOM
```
User:      "What is the AARRR framework?"
Assistant: [Answered about "pirate metrics" without using the exact AARRR acronym
           — retrieved generic "growth metrics" chunks instead of the specific
           episode where Dave McClure defined AARRR]
```

### DIAGNOSIS
Pure vector search uses semantic similarity — "AARRR" and "pirate metrics" and "acquisition activation retention revenue referral" are semantically related. But the chunk that *defined* AARRR had lower vector similarity to the query than chunks that discussed "growth metrics" more generically.

Keyword search would have found the exact "AARRR" mention — but would miss the semantic equivalents.

### FIX: Hybrid Scoring (70% Vector + 30% Keyword)

Changed the SQL query in `RetrievalService.retrieve()`:

```sql
SELECT
    id, transcript_name, content, chunk_index, metadata,
    1 - (embedding <=> :embedding) AS vector_sim,
    ts_rank(
        to_tsvector('english', content),
        plainto_tsquery('english', :query_text)
    ) AS keyword_rank,
    (
        0.7 * (1 - (embedding <=> :embedding))
        + 0.3 * LEAST(ts_rank(...), 1.0)
    ) AS combined_score
FROM transcript_chunks
WHERE embedding IS NOT NULL
ORDER BY combined_score DESC
LIMIT :limit
```

**Why 70/30?**  
Vector search is more robust for paraphrased or semantic queries (which are most user questions). Keyword search is a tiebreaker for exact terminology. Tuned by manual testing on 20 representative queries.

**Result:** Exact-term queries ("AARRR", "HEART framework", "North Star metric") now rank the defining chunk first.

---

## Outcome

These three changes — query rewriting, confidence threshold, and hybrid search — significantly improved retrieval quality:

| Scenario | Before | After |
|---|---|---|
| Follow-up "Can you give me an example?" | Off-topic answer | Context-aware answer |
| Off-topic query ("quantum computing") | Hallucinated citation | "I don't have info" |
| Exact framework name ("AARRR") | Generic growth answer | Specific defining chunk |
