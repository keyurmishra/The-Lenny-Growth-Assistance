-- =============================================================================
-- Database Initialization — The Lenny Growth Assistant
-- =============================================================================
-- This script runs ONCE on first Postgres container startup.
-- It enables pgvector and creates all required tables.
--
-- DECISION: SQL init script over Alembic migrations
--   For a take-home, a single idempotent SQL file is simpler and faster.
--   Alembic adds value when you have a team making incremental schema changes
--   over months. Here, the schema is stable and defined upfront.
--
-- TRADE-OFF: No migration history, no rollback. Acceptable for a demo.
--   In production, we'd use Alembic from day one.
-- =============================================================================

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;
-- Why "IF NOT EXISTS"? Idempotency. If someone re-runs this, it won't crash.

-- Enable uuid-ossp for generating UUIDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Sessions table
-- =============================================================================
-- DECISION: UUID primary keys over auto-increment integers
--   - UUIDs are safe to expose in URLs and APIs (no enumeration attacks)
--   - No sequential leakage ("session 47" tells an attacker there are ≤47 sessions)
--   - Generated client-side if needed, no round-trip to DB
--
-- TRADE-OFF: UUIDs are 16 bytes vs 4 bytes for int. At our scale, irrelevant.
-- =============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           VARCHAR(255),
    -- Auto-generated from first message or user-provided
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}'::jsonb
    -- DECISION: JSONB metadata column
    --   Flexible key-value store for user preferences, model used, etc.
    --   Avoids adding a column every time we want to track something new.
    --   TRADE-OFF: No type safety or constraints on JSONB contents.
);

-- =============================================================================
-- Messages table
-- =============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    -- ON DELETE CASCADE: when a session is deleted, its messages go too.
    -- No orphaned messages cluttering the DB.
    role            VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    -- DECISION: CHECK constraint over application-level validation
    --   The database is the last line of defense. Even if a bug in the API
    --   sends a bad role, the DB rejects it. Defense in depth.
    content         TEXT NOT NULL,
    sources         JSONB DEFAULT '[]'::jsonb,
    -- Which transcript chunks grounded this response.
    -- Stored as JSON array: [{"transcript": "...", "chunk_id": "...", "text": "..."}]
    -- DECISION: Denormalize sources into the message row
    --   Alternative: a separate message_sources join table.
    --   At our read pattern (load full conversation), a JOIN adds latency
    --   for no real benefit. JSONB is queryable if we ever need to search by source.
    artifact_type   VARCHAR(20) CHECK (artifact_type IN ('markdown', 'html', NULL)),
    artifact_content TEXT,
    -- If this message includes a generated artifact, store it here.
    -- NULL for normal chat messages.
    model_used      VARCHAR(100),
    -- Track which model generated this response. Critical for debugging
    -- quality issues when toggling between Ollama and cloud models.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast conversation loading (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
-- Index for chronological ordering within a session
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);

-- =============================================================================
-- Transcript chunks table (knowledge base)
-- =============================================================================
CREATE TABLE IF NOT EXISTS transcript_chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transcript_name VARCHAR(500) NOT NULL,
    -- Original filename or episode title for source attribution
    chunk_index     INTEGER NOT NULL,
    -- Position within the transcript (for ordering and context)
    content         TEXT NOT NULL,
    -- The actual text chunk
    embedding       vector(384),
    -- DECISION: 384 dimensions (all-MiniLM-L6-v2)
    --   - 384-dim vectors are small → fast indexing, fast search, low memory
    --   - MiniLM-L6-v2 is the most popular sentence-transformer for retrieval
    --   - Runs on CPU without GPU dependency
    --   TRADE-OFF: OpenAI text-embedding-3-small (1536-dim) has better semantic
    --   understanding, but adds API cost and network dependency. For transcript
    --   retrieval where queries and content share vocabulary, 384-dim is sufficient.
    metadata        JSONB DEFAULT '{}'::jsonb,
    -- Episode number, guest name, date, URL — anything useful for citations
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint: no duplicate chunks from the same transcript
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_transcript_index
    ON transcript_chunks(transcript_name, chunk_index);

-- =============================================================================
-- HNSW index for fast approximate nearest neighbor search
-- =============================================================================
-- DECISION: HNSW over IVFFlat
--   - HNSW: no training step, good recall at any dataset size, slightly more memory
--   - IVFFlat: needs a training step (CREATE INDEX takes longer), recall degrades
--     if data distribution changes after training
--   At our scale (<50k chunks), HNSW is the clear winner.
--
-- TRADE-OFF: HNSW uses ~2-3x more memory than IVFFlat. At <50k vectors × 384 dims,
-- this is ~60MB — negligible.
--
-- cosine distance (<=>) is the standard metric for sentence embeddings.
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON transcript_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- m=16: each node connects to 16 neighbors (default, good balance)
-- ef_construction=64: build-time search breadth (higher = better recall, slower build)
