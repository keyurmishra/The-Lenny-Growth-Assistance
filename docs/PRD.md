# Product Requirements Document — The Lenny Growth Assistant

## 1. Forward Deployment Brief

### 1.1 User and Problem

**Primary user:** Product managers and growth practitioners on a product/growth team (IC to lead level) who consume Lenny's Podcast for frameworks, tactics, and expert perspectives.

**Job to be done:** When preparing a strategy doc, planning a feature launch, or making a growth decision, the user needs to quickly find what Lenny's guests have said about a specific topic — synthesized, cited, and in a form they can reuse (essay, memo, artifact) — without re-listening to 200+ hours of podcast content.

**Pain removed:**
- **Search friction:** Podcast transcripts are long-form, unstructured text. Ctrl+F across 200 files is slow and misses semantic matches ("retention strategies" won't find "keeping users engaged").
- **Synthesis burden:** Even after finding relevant excerpts, the user must read, compare, and distill them into actionable takeaways. The assistant does this automatically.
- **Content creation tax:** Turning research into a polished essay or artifact requires a separate writing step. The assistant collapses research → writing into a single interaction.

### 1.2 Success Metrics

| Metric | Definition | Target | Why |
|--------|-----------|--------|-----|
| **Grounding accuracy** | % of assistant claims traceable to a specific transcript | ≥ 90% | The core value prop collapses if answers are hallucinated. |
| **Source relevance** | User satisfaction with cited sources (1-5 rating) | ≥ 4.0 | Correct citations from irrelevant transcripts erode trust. |
| **Time to answer** | Median latency for a grounded response | < 10s (cloud), < 30s (Ollama) | Users abandon after ~15s of waiting. Ollama has higher tolerance since users expect local models to be slower. |
| **Session depth** | Avg messages per session | ≥ 3 | Indicates the assistant handles follow-ups, not just one-shots. |

### 1.3 Assumptions

These assumptions were made because the client brief was incomplete:

| # | Assumption | Risk if wrong | Mitigation |
|---|-----------|---------------|-----------|
| A1 | Transcripts are plain text, not audio files. | Ingestion pipeline would need ASR (speech-to-text). | Verified: the GitHub repo contains .txt transcript files. |
| A2 | The target dataset is ~100-300 transcripts (manageable in a single pgvector table). | If 10,000+ transcripts, we'd need sharding or a dedicated vector DB. | Current architecture handles up to ~50k chunks without performance issues. |
| A3 | Users ask questions in English. | Multi-language support would require multilingual embeddings. | all-MiniLM-L6-v2 is English-optimized. Swap to multilingual-e5-base if needed. |
| A4 | The assistant is an internal tool (not public-facing). | A public tool needs auth, rate limiting, abuse prevention, and content moderation. | Basic API structure supports adding auth middleware later. |
| A5 | "Ship 30 for 30 style" means the specific writing framework from ship30for30.com (hook, skimmable formatting, single takeaway). | If the client means a different writing style, the skill is miscalibrated. | Skill is modular — swap the system prompt to change the output format. |
| A6 | Local Ollama demo is for evaluation purposes; production would use a cloud LLM. | If production must run locally, model quality and latency become first-class concerns. | LLM provider is configurable; quality gaps are documented. |

### 1.4 Scope Choices

**Included (MVP):**
- Grounded Q&A with transcript citations
- Ship 30 for 30 essay generation skill
- Markdown and HTML artifact viewer with sandboxed rendering
- Multi-session conversation management with PostgreSQL persistence
- Configurable LLM provider (Ollama / Anthropic / OpenAI)
- Docker Compose one-command startup
- Structured logging and health checks
- Automated tests for API, retrieval, and persistence

**Intentionally excluded (and why):**

| Feature | Why excluded |
|---------|-------------|
| **User authentication** | Internal tool (Assumption A4). Auth adds 4-6 hours of work (OAuth, JWT, middleware) for zero demo value. The evaluator needs to test freely without credentials. |
| **Real-time streaming (SSE)** | Significant frontend complexity. A loading indicator with final response is acceptable for the demo. Will add if time permits. |
| **Transcript auto-refresh** | The GitHub repo is static. A webhook or polling system for new episodes adds complexity without demo value. The ingestion script can be re-run manually. |
| **Multi-user support** | No auth = no user identity = no multi-user. Sessions are anonymous. |
| **Conversation export** | Nice-to-have. The API already returns conversation history as JSON; a frontend "Export" button is trivial to add later. |
| **Custom embedding fine-tuning** | Diminishing returns. Off-the-shelf MiniLM embeddings are sufficient for English transcript retrieval. Fine-tuning requires labeled data we don't have. |

### 1.5 Risks and Trade-offs

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Hallucination** | High | RAG retrieval grounds answers in transcript text. System prompt instructs the model to say "I don't have information about this" when retrieval returns no relevant chunks. Sources are displayed to the user for verification. |
| **Ollama quality gap** | Medium | Local models ( llama3.2:3b 7B) produce lower-quality answers than Claude Sonnet. We document this gap, show which model generated each response, and make switching to cloud a one-variable change. |
| **Latency on Ollama** | Medium | 7B models on CPU can take 15-30s per response. UI shows a loading state. We set a 60s timeout and return a graceful error if exceeded. |
| **Unsafe artifact rendering** | Medium | Generated HTML is rendered in a sandboxed iframe (`sandbox="allow-scripts"` without `allow-same-origin`). This prevents access to parent DOM, cookies, localStorage, and top-level navigation. Scripts can run (for interactive artifacts) but are fully isolated. |
| **Data leakage** | Low | Transcripts are public (GitHub). No PII in the knowledge base. No user auth means no credentials to leak. API keys are in .env (never committed). |
| **Cost (cloud models)** | Low | RAG reduces token usage by injecting only relevant chunks (~2k tokens) instead of full transcripts (~50k tokens). Estimated cost: ~$0.01 per query with Claude Sonnet. |

---

## 2. User Flows

### 2.1 Core Q&A Flow
```
User opens app → Clicks "New Chat" → Types question about product/growth
→ Backend retrieves relevant transcript chunks → LLM generates grounded answer
→ Response displays with inline source citations → User asks follow-up
→ Agent uses session context + new retrieval → Response maintains conversation thread
```

### 2.2 Ship 30 for 30 Flow
```
User is in a conversation → Asks "Write a Ship 30 essay about [topic]"
→ Agent routes to Ship 30 skill → Skill retrieves grounded content
→ Generates ~1,250 word essay with hook, headings, bullets, takeaway
→ Essay appears as a Markdown artifact in the Artifact Viewer
```

### 2.3 Artifact Flow
```
User asks for an artifact ("Create an HTML summary of...") → Agent detects
artifact intent → Generates Markdown or HTML/CSS → Response includes artifact
→ Artifact Viewer opens in a split pane → User sees rendered output alongside chat
→ Copy/Download buttons available
```

---

## 3. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC1 | User can start a new chat session | Create session via UI, verify in DB |
| AC2 | Questions return grounded answers with source citations | Ask "What does Lenny say about product-market fit?" — response cites specific transcript |
| AC3 | Follow-up questions maintain context | Ask a follow-up without repeating context — response is coherent |
| AC4 | Assistant acknowledges when it doesn't know | Ask about a topic not in transcripts — response says "I don't have information about this" |
| AC5 | Ship 30 essay is ~1,250 words with proper formatting | Trigger skill, count words, verify headings/bullets/bold/hook/takeaway |
| AC6 | Artifacts render in the viewer | Generate Markdown → renders formatted; generate HTML → renders in sandboxed iframe |
| AC7 | LLM provider is switchable | Change .env, restart, verify different model in UI and /config/model |
| AC8 | App starts with one command | `docker-compose up --build` → all services healthy within 2 minutes |
| AC9 | Health endpoint reports accurate status | Kill Postgres → /health shows degraded; restart → shows healthy |
| AC10 | Conversations persist across page reloads | Send messages, refresh browser, messages still visible |

---

## 4. Implementation Plan

| Phase | Deliverable | Time |
|-------|------------|------|
| 1 | Project scaffolding, Docker Compose, DB schema, config, health endpoint | 1.5 hrs |
| 2 | Transcript ingestion, chunking, embedding, pgvector storage | 2.5 hrs |
| 3 | LLM provider abstraction (Ollama / Anthropic / OpenAI) | 1.5 hrs |
| 4 | Agent layer, RAG pipeline, session context management | 3 hrs |
| 5 | API endpoints, Pydantic validation, structured errors | 1.5 hrs |
| 6 | Core automated tests | 1 hr |
| 7 | React chat UI with session management | 3 hrs |
| 8 | Ship 30 for 30 skill | 1.5 hrs |
| 9 | Artifact viewer with sandboxed rendering | 2 hrs |
| 10 | Documentation (architecture.md, design.md, README) | 2 hrs |
| 11 | Resilience, logging, error handling | 1.5 hrs |
| 12 | Demo video, final testing, submission | 2 hrs |
