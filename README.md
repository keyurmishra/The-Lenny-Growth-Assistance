# The Lenny Growth Assistant

> **AI-powered conversational assistant grounded in [Lenny's Podcast](https://www.lennyspodcast.com/) transcripts.**  
> Ask complex product and growth questions, generate Ship 30 for 30 essays, and view rendered artifacts — all with source citations from real podcast conversations.

---

## Demo Video

🎥 **[Watch the 2-minute demo on YouTube](https://youtube.com/YOUR_LINK_HERE)**  
*(Shows: live Q&A → Ship30 essay → HTML artifact → LLM provider switch → security model)*

---

## Architecture Overview

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│   React UI   │────▶│  FastAPI API  │────▶│   PostgreSQL    │
│  (Vite:5173) │     │  (:8000)      │     │   + pgvector     │
└──────────────┘     └───────┬───────┘     └──────────────────┘
                             │
                     ┌───────▼───────┐
                     │  Agent Layer  │
                     │  ┌──────────┐ │
                     │  │ RAG Q&A  │ │
                     │  │ Ship30   │ │
                     │  │ Artifact │ │
                     │  └──────────┘ │
                     └───────┬───────┘
                             │
                     ┌───────▼───────┐
                     │ LLM Provider  │
                     │ Ollama│Claude │
                     │ OpenAI│       │
                     └───────────────┘
```

Full architecture details: [`docs/architecture.md`](docs/architecture.md)

---

## Prerequisites

- **Docker & Docker Compose** (recommended) — OR Python 3.12+, Node 20+, PostgreSQL 16 with pgvector
- **Ollama** — for local LLM inference (required for demo)
- ~4 GB RAM minimum (for Ollama llama3.2:3b)

---

## Quick Start — Docker (Recommended)

```bash
# 1. Clone and configure
git clone https://github.com/YOUR_USERNAME/lenny-growth-assistant.git
cd lenny-growth-assistant
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD and optionally ANTHROPIC_API_KEY

# 2. Start all services
docker-compose up --build

# 3. Pull the Ollama model (first time only — ~2GB download)
docker exec -it lenny-growth-assistant-ollama-1 ollama pull llama3.2:3b

# 4. Ingest transcripts (run once)
docker exec -it lenny-growth-assistant-backend-1 python scripts/ingest.py

# 5. Open the app
open http://localhost:5173     # Frontend
open http://localhost:8000/docs  # API documentation (Swagger UI)
open http://localhost:8000/health  # Health check
```

---

## Quick Start — Local (Without Docker)

```bash
# Terminal 1: Start Ollama
ollama serve
ollama pull llama3.2:3b

# Terminal 2: Backend
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env   # Edit .env with your DB credentials
uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend
cd frontend
npm install
npm run dev
```

---

## Environment Variables

See [`.env.example`](.env.example) for all variables with inline documentation.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | Yes | `ollama` | `ollama`, `anthropic`, or `openai` |
| `OLLAMA_MODEL` | Yes (demo) | `llama3.2:3b` | Ollama model name |
| `OLLAMA_BASE_URL` | Yes (demo) | `http://localhost:11434` | Ollama server URL |
| `ANTHROPIC_API_KEY` | If using Claude | — | Anthropic API key |
| `OPENAI_API_KEY` | If using OpenAI | — | OpenAI API key |
| `POSTGRES_HOST` | Yes | `postgres` | PostgreSQL host |
| `POSTGRES_PASSWORD` | Yes | `lenny_local_dev` | DB password |
| `POSTGRES_USER` | Yes | `lenny` | DB user |
| `POSTGRES_DB` | Yes | `lenny_assistant` | DB name |

---

## Switching LLM Providers

Change `LLM_PROVIDER` in `.env` and restart the backend. No code changes needed.

```bash
# Use Anthropic Claude
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Use OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Use local Ollama (default)
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
```

The active provider and model are visible:
- In the **UI sidebar** (bottom badge)
- At `GET /config/model`
- In every server log line

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | System health (DB, LLM, knowledge base) |
| `GET` | `/config/model` | Active LLM provider, model, health status |
| `POST` | `/config/model/test` | Send test prompt to verify LLM works |
| `POST` | `/api/v1/sessions` | Create a new chat session |
| `GET` | `/api/v1/sessions` | List sessions (limit/offset) |
| `DELETE` | `/api/v1/sessions/{id}` | Delete session and all messages |
| `GET` | `/api/v1/sessions/{id}/messages` | Get full conversation history |
| `POST` | `/api/v1/sessions/{id}/chat` | **Main endpoint** — send message, get AI response |
| `GET` | `/api/v1/knowledge/stats` | Chunk count, transcript count |
| `GET` | `/api/v1/knowledge/search?q=...` | Direct vector search (bypasses LLM) |

Interactive docs: `http://localhost:8000/docs`

---

## Testing

```bash
cd backend
pytest tests/ -v
```

Test files:
| File | What it covers |
|---|---|
| `test_api.py` | Session CRUD, chat endpoint, health, knowledge search |
| `test_chat_service.py` | Intent routing, RAG pipeline, artifact generation |
| `test_retrieval.py` | Vector search, hybrid scoring, confidence threshold |
| `test_llm_provider.py` | Provider abstraction, fallback behavior |
| `test_transcript_parser.py` | Chunking, metadata extraction |

Manual test plan: [`docs/MANUAL_TEST_PLAN.md`](docs/MANUAL_TEST_PLAN.md)

---

## Project Structure

```
lenny-growth-assistant/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI route handlers
│   │   ├── agents/       # System prompts (prompts.py)
│   │   ├── core/         # Config, DB, LLM provider, logging
│   │   ├── models/       # Pydantic schemas
│   │   ├── services/     # ChatService, RetrievalService, EmbeddingService
│   │   ├── skills/       # Ship30Skill (ship30.py)
│   │   └── main.py       # FastAPI app, health endpoints
│   ├── scripts/
│   │   └── ingest.py     # Transcript ingestion pipeline
│   └── tests/            # Automated test suite
├── frontend/
│   └── src/
│       ├── components/   # Sidebar, ChatPanel, ChatMessage, ArtifactViewer
│       ├── lib/          # API client (api.js)
│       └── App.jsx       # Root layout (sidebar + chat + artifact)
├── docs/
│   ├── PRD.md            # Product requirements + discovery brief
│   ├── architecture.md   # System design, schema, flows, security
│   ├── design.md         # UI/UX principles and decisions
│   └── MANUAL_TEST_PLAN.md
├── agent_transcripts/    # AI-assisted development logs
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## How to Extend

### Add a new transcript source
1. Add `.txt` files to the `data/transcripts/` directory
2. Re-run `python scripts/ingest.py` — uses upsert, safe to run on existing data
3. New transcripts are available immediately after ingestion completes

### Add a new LLM provider
1. Create `backend/app/core/providers/your_provider.py` implementing `BaseLLMProvider`:
   ```python
   class YourProvider(BaseLLMProvider):
       async def generate(self, messages, config) -> LLMResponse: ...
       async def health_check(self) -> dict: ...
   ```
2. Add `your_provider` to the `LLMProvider` enum in `config.py`
3. Add the instantiation branch in `get_llm_provider()` in `llm_provider.py`
4. Set `LLM_PROVIDER=your_provider` in `.env`

### Add a new skill
1. Create `backend/app/skills/your_skill.py` with your skill class
2. Add intent detection patterns in `ChatService._classify_intent()`
3. Add a handler method `ChatService._handle_your_skill()`
4. Route the new intent in `ChatService.chat()`

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vector DB | pgvector (PostgreSQL) | One fewer service; already need Postgres |
| Embeddings | all-MiniLM-L6-v2 | No API key, runs on CPU, 384-dim, good English quality |
| Hybrid search | 70% vector + 30% keyword | Semantic + exact-term coverage |
| Query rewriting | LLM-based | Follow-up questions get contextual retrieval |
| Confidence threshold | 0.45 cosine similarity | Prevents hallucination from weak matches |
| Artifact isolation | Sandboxed iframe | No allow-same-origin prevents sandbox escape |
| Async DB | asyncpg | Non-blocking I/O matches FastAPI's async model |
| Logging | structlog (JSON) | Machine-parseable, searchable, production-ready |

---

## Troubleshooting

| Problem | Likely cause | Solution |
|---------|-------------|----------|
| `getaddrinfo failed` on DB | Special chars in password or whitespace in hostname | Check `.env` — password auto URL-encoded, but verify no trailing spaces |
| Ollama model not found | Model not pulled | `ollama pull llama3.2:3b` |
| Empty answers / "no information" | Transcripts not ingested | Run `python scripts/ingest.py` |
| CORS errors in browser | Frontend URL not in CORS whitelist | Add URL to `CORS_ORIGINS` in `.env` |
| `vector type does not exist` | pgvector extension not enabled | Run `CREATE EXTENSION IF NOT EXISTS vector;` in your DB |
| Backend won't start | Missing `.env` | Run `cp .env.example .env` and configure required vars |
| Slow responses | Ollama on CPU | Normal for local models (15–30s). Switch to `anthropic` for speed |

---

## License

Take-home assignment submission. Transcript content belongs to Lenny Rachitsky / Lenny's Podcast.
