# Architecture — The Lenny Growth Assistant

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        BROWSER                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  React + Vite (port 5173)                           │   │
│   │  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│   │  │  Sidebar  │  │  ChatPanel   │  │ArtifactViewer│  │   │
│   │  │(sessions) │  │(messages,    │  │(markdown /   │  │   │
│   │  │           │  │ input)       │  │ sandboxed    │  │   │
│   │  └──────────┘  └──────────────┘  │ iframe HTML) │  │   │
│   │                                   └──────────────┘  │   │
│   └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/REST (JSON)
                           │ CORS from localhost:5173
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Backend (port 8000)                 │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ API Layer (/api/v1)                                  │   │
│  │  POST /sessions/:id/chat  ← main entry point         │   │
│  │  POST /sessions           ← create session           │   │
│  │  GET  /sessions           ← list sessions            │   │
│  │  GET  /sessions/:id/messages                         │   │
│  │  DELETE /sessions/:id                                │   │
│  │  GET  /health             ← dependency health check  │   │
│  │  GET  /config/model       ← active LLM info          │   │
│  │  GET  /api/v1/knowledge/search                       │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                       │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │ Agent / Orchestration Layer (ChatService)            │   │
│  │                                                      │   │
│  │  1. Load conversation history from DB                │   │
│  │  2. Classify intent (RAG_QA / SHIP30 / ARTIFACT /    │   │
│  │     GENERAL)                                         │   │
│  │  3. Rewrite query for context-awareness              │   │
│  │  4. Route to skill handler                           │   │
│  │  5. Persist response + artifact                      │   │
│  │                                                      │   │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐  │   │
│  │  │  _handle_   │ │  _handle_    │ │  _handle_    │  │   │
│  │  │  rag_qa()   │ │  ship30()    │ │  artifact()  │  │   │
│  │  └──────┬──────┘ └──────┬───────┘ └──────┬───────┘  │   │
│  └─────────│───────────────│────────────────│──────────┘   │
│            │               │                │               │
│  ┌─────────▼───────────────▼────────────────▼──────────┐   │
│  │ Services Layer                                       │   │
│  │  RetrievalService    EmbeddingService   Ship30Skill  │   │
│  │  (pgvector search)   (all-MiniLM-L6)   (essay rules) │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │ LLM Provider Abstraction                             │   │
│  │  OllamaProvider | AnthropicProvider | OpenAIProvider  │   │
│  │  Configured via LLM_PROVIDER env var                 │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
                ▼                         ▼
┌──────────────────────┐      ┌──────────────────────────────┐
│  PostgreSQL          │      │  LLM Inference               │
│  (Supabase / Docker) │      │                              │
│                      │      │  Ollama (local, port 11434)  │
│  • chat_sessions     │      │    llama3.2:3b               │
│  • chat_messages     │      │                              │
│  • transcript_chunks │      │  — OR —                      │
│    + pgvector        │      │                              │
│                      │      │  Anthropic API               │
│                      │      │    claude-sonnet-4           │
│                      │      │                              │
│                      │      │  — OR —                      │
│                      │      │                              │
│                      │      │  OpenAI API                  │
│                      │      │    gpt-4o-mini               │
└──────────────────────┘      └──────────────────────────────┘
```

---

## 2. Database Schema

### `chat_sessions`
```sql
CREATE TABLE chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT,                    -- Auto-generated from first message
    metadata    JSONB DEFAULT '{}',      -- Extensible: user_id, tags, etc.
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### `chat_messages`
```sql
CREATE TABLE chat_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,           -- 'user' | 'assistant'
    content     TEXT NOT NULL,           -- Message text (Markdown for assistant)
    sources     JSONB DEFAULT '[]',      -- Retrieved transcript chunks [{transcript, relevance_score, text}]
    artifact    JSONB,                   -- Nullable: {type, title, content} for rendered artifacts
    model_used  TEXT,                    -- Which LLM model generated this response
    latency_ms  FLOAT,                   -- Response time in milliseconds
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at);
```

### `transcript_chunks`
```sql
CREATE TABLE transcript_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transcript_name TEXT NOT NULL,       -- File name (e.g., "ep-234-lenny.txt")
    content         TEXT NOT NULL,       -- Chunk text (512 tokens, 50 overlap)
    chunk_index     INTEGER NOT NULL,    -- Position within transcript
    metadata        JSONB DEFAULT '{}',  -- {title, guest, episode, date, url}
    embedding       VECTOR(384),         -- all-MiniLM-L6-v2 embedding
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON transcript_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);                  -- Approximate nearest neighbor for speed
```

**Why pgvector instead of a dedicated vector DB (Pinecone, Weaviate)?**
One fewer service to run, manage, and secure. PostgreSQL already handles persistence — pgvector adds vector search without infrastructure overhead. With ~48k chunks and 384-dim embeddings, query time is <50ms.

---

## 3. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | DB, LLM, and knowledge base status |
| `GET` | `/config/model` | None | Active provider, model, health |
| `POST` | `/config/model/test` | None | Send test prompt to verify LLM |
| `POST` | `/api/v1/sessions` | None | Create a new chat session |
| `GET` | `/api/v1/sessions` | None | List sessions (pagination: limit/offset) |
| `GET` | `/api/v1/sessions/{id}` | None | Get session details |
| `DELETE` | `/api/v1/sessions/{id}` | None | Delete session + all messages |
| `GET` | `/api/v1/sessions/{id}/messages` | None | Get conversation history |
| `POST` | `/api/v1/sessions/{id}/chat` | None | Send message, get AI response |
| `GET` | `/api/v1/knowledge/stats` | None | Chunk count, transcript count |
| `GET` | `/api/v1/knowledge/search?q=...&top_k=5` | None | Direct vector search (bypasses LLM) |

**Request/Response Contract (POST /api/v1/sessions/{id}/chat):**
```json
// Request
{ "content": "What does Lenny say about product-market fit?" }

// Response
{
  "message": {
    "id": "uuid",
    "session_id": "uuid",
    "role": "assistant",
    "content": "Lenny's guests emphasize...",
    "sources": [
      {
        "transcript": "ep-234-brian-chesky.txt",
        "relevance_score": 0.82,
        "text": "The key to PMF is...",
        "metadata": { "guest": "Brian Chesky", "title": "...", "episode": "234" }
      }
    ],
    "artifact": {
      "type": "markdown",
      "title": "Ship 30 Essay: PMF",
      "content": "# How to Find PMF..."
    },
    "model_used": "llama3.2:3b",
    "latency_ms": 4231.5,
    "created_at": "2025-08-25T08:00:00Z"
  }
}
```

---

## 4. Ingestion and Retrieval Flow

### Ingestion Pipeline (`scripts/ingest.py`)

```
1. LOAD        Scan transcripts/ directory for .txt files
               Parse metadata from filename + content header
               (episode number, guest name, title, date)

2. CHUNK       Split each transcript into 512-token chunks
               50-token overlap to preserve sentence continuity
               ~48,000 total chunks from ~303 transcripts

3. EMBED       Run each chunk through all-MiniLM-L6-v2 (local, CPU)
               Output: 384-dimensional float32 vector
               No API key required; runs at ~800 chunks/min on CPU

4. INDEX       INSERT chunks into transcript_chunks table (upsert on name+index)
               pgvector stores embedding as VECTOR(384)
               IVFFlat index with lists=100 for ANN search

5. VERIFY      Log ingestion stats: transcripts processed, chunks created,
               errors, duration
```

### Retrieval Pipeline (per query)

```
1. REWRITE     If conversation history exists AND query is short/ambiguous:
               LLM rewrites "Can you give me an example?" →
               "Give an example of product-market fit from Lenny's Podcast"
               Fallback: use original query on error

2. EMBED       Embed the (possibly rewritten) query with all-MiniLM-L6-v2

3. SEARCH      Hybrid SQL query against transcript_chunks:
               combined_score = 0.7 × vector_cosine_similarity
                              + 0.3 × postgresql_ts_rank(keyword)
               ORDER BY combined_score DESC LIMIT (top_k × 2)

4. THRESHOLD   Filter: vector_similarity ≥ 0.30 (noise cutoff)
               Confidence check: if top chunk < 0.45, return empty
               → triggers "I don't have enough information" response

5. FORMAT      Format top-k chunks as [Source N: Title (Guest: Name)]
               Pass as context string to LLM prompt
```

---

## 5. Agent Routing Logic

```python
# Intent classification (app/services/chat.py: _classify_intent)
SHIP30_PATTERNS   = ["ship 30", "ship30", "essay", "write an article"]
ARTIFACT_PATTERNS = ["create an html", "generate html", "landing page",
                     "create a markdown", "generate a document"]

# Priority order:
1. SHIP30   — if any ship30 pattern matches
2. ARTIFACT — if any artifact pattern matches
3. GENERAL  — if message < 10 words and no question mark
4. RAG_QA   — default (most messages)
```

**Why keyword matching over LLM classification?**
A router LLM call adds ~500ms latency for every message. Keyword matching is instantaneous and handles 95% of routing correctly. The RAG_QA fallback handles everything ambiguous — it's safe to over-retrieve rather than over-route.

---

## 6. LLM Provider Abstraction

All providers implement the same interface (`BaseLLMProvider`):

```python
class BaseLLMProvider:
    async def generate(messages: list[LLMMessage], config: LLMConfig) -> LLMResponse
    async def health_check() -> dict
    @property provider_name: str
    @property model_name: str
```

**Switching providers:** Change `LLM_PROVIDER` in `.env` → restart backend → provider is live.
No application code changes needed.

**Fallback behavior:**
- Ollama unreachable → error logged, graceful HTTP 503 with explanation
- API key missing → error at startup, health endpoint reports "degraded"
- Model not pulled → health check detects `model_missing`, suggests `ollama pull`
- Timeout → 60s deadline, returns structured error response

---

## 7. Security Architecture

### HTML Artifact Isolation (Defense in Depth)

**Layer 1 — Server-side prompt constraints:**
The `ARTIFACT_SYSTEM_PROMPT` explicitly instructs the LLM:
- No external URLs (no CDN, no fonts.googleapis.com, no img src http://)
- All CSS must be inline in a `<style>` block
- Use system fonts only

**Layer 2 — Client-side attribute stripping (ArtifactViewer.jsx):**
Before injecting HTML into the iframe, we strip:
- Event handler attributes (`onclick`, `onload`, `onerror`, etc.)
- `javascript:` URI scheme in href/src
- External `<script src="...">` tags

**Layer 3 — Sandboxed iframe (primary runtime isolation):**
```html
<iframe
  srcDoc={sanitizedHtml}
  sandbox="allow-scripts"
  referrerPolicy="no-referrer"
/>
```

`sandbox="allow-scripts"` WITHOUT `allow-same-origin`:
| Capability | Allowed | Blocked |
|---|---|---|
| JavaScript execution | ✅ | — |
| CSS styling | ✅ | — |
| Parent DOM access | — | ✅ |
| Cookie access | — | ✅ |
| localStorage/sessionStorage | — | ✅ |
| Top-level navigation | — | ✅ |
| Form submission | — | ✅ |
| Popups (window.open) | — | ✅ |

**Why not `allow-same-origin`?** Combining `allow-scripts` + `allow-same-origin` lets the iframe remove its own sandbox attribute via JavaScript — a known escape vector. We never combine them on untrusted content.

---

## 8. Deployment Topology

### Docker Compose (Recommended)

```
docker-compose.yml defines:
  postgres  → PostgreSQL 16 + pgvector extension (port 5432)
  backend   → FastAPI + all Python deps (port 8000)
  frontend  → Vite dev server (port 5173)
  [ollama]  → Optional: include if not running Ollama natively
```

**Startup sequence (with healthchecks):**
```
postgres (healthcheck: pg_isready) →
  backend (depends_on: postgres, condition: healthy) →
    frontend (depends_on: backend)
```

### Environment Configuration

All secrets and configuration flow through `.env` → `pydantic-settings` → `Settings` singleton.
- `.env` is gitignored, never committed
- `.env.example` has safe defaults and documentation for every variable
- `Settings` strips whitespace from all connection fields (prevents DNS errors from invisible characters)

### Observability

All logs are structured JSON via `structlog`:
```json
{"event": "retrieval_complete", "query": "PMF", "chunks_found": 5,
 "top_similarity": 0.82, "latency_ms": 48.3, "timestamp": "..."}
```

Key logged events:
| Event | What it tells you |
|---|---|
| `database_connected` | DB is up on startup |
| `database_connection_failed` | Connection string issue |
| `retrieval_started` / `retrieval_complete` | RAG performance |
| `retrieval_below_confidence_threshold` | Query not covered by transcripts |
| `query_rewritten` | Context-aware rewriting fired |
| `ship30_generated` | Essay quality metrics (word count, headings, valid) |
| `llm_response` | Provider, model, latency, token counts |
| `unhandled_exception` | Unexpected errors with full stack trace |

---

## 9. Component Boundaries

| Component | Responsibility | Does NOT do |
|---|---|---|
| `api/routes.py` | HTTP interface — validates requests, returns responses | Business logic |
| `services/chat.py` | Orchestration — routes intents, calls skills, persists | LLM calls, SQL |
| `services/retrieval.py` | Vector + keyword search against pgvector | LLM calls, response formatting |
| `services/embedding.py` | Text → 384-dim vector | Storage, retrieval |
| `core/llm_provider.py` | LLM abstraction — single interface for 3 providers | Prompt construction |
| `agents/prompts.py` | All system prompts centralized | Agent routing |
| `skills/ship30.py` | Ship 30 rules, prompt building, output validation | LLM calls, retrieval |
| `core/config.py` | Settings from environment | Any business logic |
| `core/database.py` | SQLAlchemy async engine + session factory | Query construction |
