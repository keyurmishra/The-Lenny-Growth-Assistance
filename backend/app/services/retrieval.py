"""
Retrieval service — finds relevant transcript chunks for a given query.

This is the R in RAG (Retrieval-Augmented Generation). The flow:
  1. User asks a question
  2. We embed the question into a 384-dim vector
  3. We query pgvector for the nearest chunks (cosine similarity)
  4. We return the top-k chunks with their source metadata
  5. These chunks become context for the LLM to generate a grounded answer

DECISION: pgvector cosine similarity over keyword search (BM25/tsvector)
  - Semantic search: "How do I keep users?" matches chunks about "retention"
    and "engagement" — keyword search would miss these unless the exact
    words appear.
  - Podcast transcripts use conversational language that rarely matches
    the formal terms users search for. Semantic search bridges this gap.

  TRADE-OFF: Keyword search has zero false positives — if the word is there,
  it matches. Semantic search can return false positives (chunks that are
  embeddings-similar but topically irrelevant). We mitigate this with a
  similarity threshold (reject chunks below 0.3 cosine similarity).

DECISION: Similarity threshold of 0.3
  Below 0.3 cosine similarity, chunks are essentially random matches.
  Returning them would dilute the context and increase hallucination risk.
  The threshold is configurable — tune it based on retrieval quality testing.

DECISION: Return raw chunks with metadata, not pre-formatted citations
  The retrieval service returns structured data. The agent/prompt layer
  decides how to format citations. This keeps retrieval pure and testable
  — you can verify "does this query find the right chunks?" without
  involving the LLM.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.embedding import get_embedding_service

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    """A transcript chunk retrieved by similarity search."""
    chunk_id: str
    transcript_name: str
    content: str
    similarity_score: float
    chunk_index: int
    metadata: dict

    def to_source_dict(self) -> dict:
        """Convert to the source reference format stored in messages."""
        return {
            "transcript": self.transcript_name,
            "chunk_id": self.chunk_id,
            "text": self.content[:500],  # Truncate for storage
            "relevance_score": round(self.similarity_score, 4),
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
        }


class RetrievalService:
    """Finds relevant transcript chunks for a user query via vector similarity."""

    def __init__(self):
        self.embedding_service = get_embedding_service()
        self.top_k = settings.retrieval_top_k
        self.similarity_threshold = 0.3   # Minimum cosine similarity to include a chunk
        self.confidence_threshold = 0.45  # Below this, we don't have enough info to answer
        # DECISION: Two separate thresholds
        #   similarity_threshold (0.3): filters out noise — chunks that are
        #     essentially random matches. Any chunk above 0.3 "kind of" matches.
        #   confidence_threshold (0.45): the bar for confident retrieval.
        #     If the BEST chunk is below 0.45, we tell the user we don't have
        #     enough information rather than hallucinating from weak matches.
        #   This mirrors how RAG works in production: weak retrieval = no answer.

    async def retrieve(
        self,
        query: str,
        db: AsyncSession,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """
        Find the most relevant transcript chunks for a query.

        Flow:
          1. Embed the query text
          2. Run a cosine similarity search against pgvector
          3. Filter by similarity threshold
          4. Return ranked results with metadata

        Args:
            query: The user's question or search text.
            db: Async database session.
            top_k: Override the default number of results (default: 5).
            similarity_threshold: Override minimum similarity (default: 0.3).

        Returns:
            List of RetrievedChunk objects, sorted by similarity (highest first).
        """
        k = top_k or self.top_k
        threshold = similarity_threshold or self.similarity_threshold

        # Step 1: Embed the query
        logger.info("retrieval_started", query=query[:100], top_k=k)
        query_embedding = self.embedding_service.embed_text(query)

        # Step 2: Query pgvector using cosine distance
        # The <=> operator is cosine distance (1 - cosine_similarity).
        # So we ORDER BY distance ASC (smallest distance = most similar).
        # We compute similarity as (1 - distance) for human-readable scores.
        #
        # DECISION: Raw SQL over SQLAlchemy ORM for vector queries
        #   SQLAlchemy's pgvector integration is limited — it doesn't support
        #   the <=> operator natively in all query builder contexts. Raw SQL
        #   with parameterized queries is clearer and avoids ORM gymnastics.

        # pgvector expects the embedding as a string: '[0.1, 0.2, ...]'
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # DECISION: Hybrid scoring = vector similarity + keyword ranking
        #   Pure vector search can miss when the user uses exact terminology
        #   from the transcripts (e.g., "AARRR framework"). Pure keyword search
        #   misses semantic equivalents ("retention" vs "keeping users").
        #   We combine: 70% vector + 30% keyword for the best of both worlds.
        #
        #   ts_rank uses PostgreSQL's built-in full-text search ranking.
        #   plainto_tsquery handles natural language (strips stop words, stems).
        #
        #   TRADE-OFF: The combined score makes the SQL slightly more complex
        #   but retrieval quality improves measurably for specific queries.
        sql = text("""
            SELECT
                id,
                transcript_name,
                content,
                chunk_index,
                metadata,
                1 - (embedding <=> :embedding) AS vector_sim,
                ts_rank(
                    to_tsvector('english', content),
                    plainto_tsquery('english', :query_text)
                ) AS keyword_rank,
                (
                    0.7 * (1 - (embedding <=> :embedding))
                    + 0.3 * LEAST(
                        ts_rank(
                            to_tsvector('english', content),
                            plainto_tsquery('english', :query_text)
                        ), 1.0
                    )
                ) AS combined_score
            FROM transcript_chunks
            WHERE embedding IS NOT NULL
            ORDER BY combined_score DESC
            LIMIT :limit
        """)

        result = await db.execute(
            sql,
            {"embedding": embedding_str, "limit": k * 2, "query_text": query[:500]},
            # Fetch 2x the requested amount, then filter by threshold.
        )

        rows = result.fetchall()

        # Step 3: Filter by similarity threshold (using vector_sim for threshold check)
        chunks = []
        for row in rows:
            similarity = float(row.vector_sim)
            if similarity < threshold:
                continue

            chunks.append(
                RetrievedChunk(
                    chunk_id=str(row.id),
                    transcript_name=row.transcript_name,
                    content=row.content,
                    similarity_score=similarity,
                    chunk_index=row.chunk_index,
                    metadata=row.metadata or {},
                )
            )

            if len(chunks) >= k:
                break

        logger.info(
            "retrieval_complete",
            query=query[:100],
            chunks_found=len(chunks),
            top_similarity=round(chunks[0].similarity_score, 4) if chunks else 0,
            lowest_similarity=round(chunks[-1].similarity_score, 4) if chunks else 0,
        )

        return chunks

    async def retrieve_with_context(
        self,
        query: str,
        db: AsyncSession,
        top_k: int | None = None,
        check_confidence: bool = True,
    ) -> tuple[list[RetrievedChunk], str]:
        """
        Retrieve chunks AND format them into a context string for the LLM.

        Args:
            query: The search query.
            db: Async database session.
            top_k: Override default result count.
            check_confidence: If True (default), return empty when the top chunk
                is below self.confidence_threshold. This triggers graceful
                "I don't have enough info" responses instead of hallucinations.

        Returns:
            Tuple of (chunks, formatted_context_string).
            Returns ([], "") when no confident results found.
        """
        chunks = await self.retrieve(query, db, top_k=top_k)

        if not chunks:
            return chunks, ""

        # DECISION: Confidence gate
        #   If the best match is below confidence_threshold, the transcripts
        #   don't reliably cover this topic. Return empty so the caller
        #   triggers the "I don't have enough information" response path.
        #   This prevents weak matches from leading to hallucinated answers.
        if check_confidence and chunks[0].similarity_score < self.confidence_threshold:
            logger.info(
                "retrieval_below_confidence_threshold",
                top_similarity=round(chunks[0].similarity_score, 4),
                threshold=self.confidence_threshold,
                query=query[:100],
            )
            return [], ""

        # Format chunks into a context block the LLM can reference
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            guest = chunk.metadata.get("guest", "Unknown")
            title = chunk.metadata.get("title", chunk.transcript_name)
            context_parts.append(
                f"[Source {i}: {title} (Guest: {guest})]\n{chunk.content}\n"
            )

        context_string = "\n---\n".join(context_parts)
        return chunks, context_string

    async def get_chunk_count(self, db: AsyncSession) -> int:
        """Return the total number of indexed chunks. Used by health checks."""
        result = await db.execute(text("SELECT COUNT(*) FROM transcript_chunks"))
        return result.scalar() or 0


# Module-level singleton
_retrieval_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    """Get or create the singleton RetrievalService."""
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service
