"""
Embedding service — generates vector embeddings for text.

DECISION: sentence-transformers (local) over OpenAI Embeddings API
  - No API key required — works completely offline
  - No per-request cost ($0 vs $0.02/1M tokens for OpenAI)
  - No network latency — embeddings generate in <100ms on CPU
  - No rate limits — can embed 1000 chunks without throttling
  - The model (all-MiniLM-L6-v2) downloads once (~80MB) and runs forever

  TRADE-OFF: OpenAI's text-embedding-3-small produces higher-quality
  embeddings (1536-dim) with better semantic understanding. For our use
  case — retrieving English podcast transcripts where queries and content
  share vocabulary — the quality difference is marginal. If retrieval
  quality is poor, switching to OpenAI embeddings is a 5-line change.

DECISION: Singleton model loading
  The sentence-transformer model takes ~2s to load. Loading it once at
  startup and reusing it across all requests avoids repeated 2s penalties.
  The model uses ~200MB RAM — acceptable for a single-service deployment.

DECISION: Batch embedding over one-at-a-time
  sentence-transformers can encode multiple texts in one call, using
  vectorized operations. Encoding 100 texts in a batch is ~10x faster
  than encoding them individually. Critical for the ingestion pipeline
  where we process thousands of chunks.
"""

import time
from functools import lru_cache

import numpy as np
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """Generates vector embeddings for text using a local sentence-transformer model."""

    def __init__(self):
        self._model = None
        self._model_name = settings.embedding_model
        self._dimension = settings.embedding_dimension

    @property
    def model(self):
        """
        Lazy-load the model on first use.

        DECISION: Lazy loading over eager loading
          If the app starts but nobody calls the embedding service (e.g.,
          just hitting /health), we avoid the 2s model load + 200MB RAM.
          The first embedding request pays the cost; all subsequent ones
          are instant.
        """
        if self._model is None:
            logger.info("loading_embedding_model", model=self._model_name)
            start = time.time()
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            elapsed = time.time() - start
            logger.info(
                "embedding_model_loaded",
                model=self._model_name,
                load_time_seconds=round(elapsed, 2),
            )
        return self._model

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (e.g., 384 for MiniLM)."""
        return self._dimension

    def embed_text(self, text: str) -> list[float]:
        """
        Generate an embedding vector for a single text string.

        Used for:
          - Embedding user queries at search time
          - Embedding individual chunks during incremental updates

        Args:
            text: The text to embed.

        Returns:
            A list of floats (length = self.dimension).
        """
        if not text or not text.strip():
            return [0.0] * self._dimension

        embedding = self.model.encode(
            text,
            normalize_embeddings=True,
            # DECISION: Normalize embeddings
            #   Normalized vectors have unit length (L2 norm = 1).
            #   This means cosine similarity = dot product, which is faster.
            #   pgvector's <=> operator (cosine distance) benefits from this.
            show_progress_bar=False,
        )
        return embedding.tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """
        Generate embeddings for multiple texts efficiently.

        Used for:
          - Bulk ingestion of transcript chunks
          - Re-embedding after model changes

        Args:
            texts: List of text strings to embed.
            batch_size: Number of texts to process in each internal batch.
                        64 is a sweet spot: large enough for GPU/SIMD gains,
                        small enough to avoid OOM on CPU.

        Returns:
            List of embedding vectors (same order as input texts).
        """
        if not texts:
            return []

        logger.info(
            "embedding_batch",
            count=len(texts),
            batch_size=batch_size,
        )

        start = time.time()

        # Replace empty strings with a placeholder to avoid model errors
        cleaned = [t if t and t.strip() else "empty" for t in texts]

        embeddings = self.model.encode(
            cleaned,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )

        elapsed = time.time() - start
        logger.info(
            "embedding_batch_complete",
            count=len(texts),
            total_seconds=round(elapsed, 2),
            per_text_ms=round((elapsed / len(texts)) * 1000, 1) if texts else 0,
        )

        return embeddings.tolist()


# Module-level singleton
# DECISION: Module singleton over FastAPI dependency injection
#   The embedding model is heavy (200MB). We want exactly one instance
#   across all requests. DI with Depends() creates a new instance per
#   request by default. We could use a custom dependency with caching,
#   but a simple module-level singleton is clearer and has the same effect.
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the singleton EmbeddingService."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
