# Project Structure Rationale

## Why a Monorepo?

We use a single repository with `backend/` and `frontend/` at the top level.

**Decision:** Monorepo over polyrepo
**Reason:** For a take-home assignment, a single `git clone` + `docker-compose up` is the gold standard. Splitting into multiple repos forces the evaluator to clone, configure, and coordinate multiple services — unnecessary friction for a project of this size.
**Trade-off:** In production, separate repos enable independent deploy cycles. Here, developer experience and evaluator convenience outweigh that.

## Directory Layout

```
lenny-growth-assistant/
├── backend/
│   ├── app/
│   │   ├── api/          # Route handlers (thin — delegate to services)
│   │   ├── core/         # Config, database, LLM provider abstraction
│   │   ├── models/       # SQLAlchemy ORM models + Pydantic schemas
│   │   ├── services/     # Business logic (chat, retrieval, sessions)
│   │   ├── skills/       # Encapsulated skills (ship30, artifact gen)
│   │   └── agents/       # Agent routing and orchestration
│   ├── tests/            # Pytest test suite
│   └── scripts/          # Ingestion, seeding, utilities
├── frontend/             # React UI (Vite)
├── docs/                 # PRD, architecture, design docs
├── agent-logs/           # Coding agent transcripts (required deliverable)
├── data/transcripts/     # Downloaded Lenny's podcast transcripts
├── docker-compose.yml
├── .env.example
└── README.md
```

## Why This Backend Layout?

The `app/` package follows a **layered architecture**:

- **api/** — HTTP concerns only. Parse request, call service, return response. No business logic here.
- **core/** — Cross-cutting: config, DB engine, LLM client factory. Things everything depends on.
- **models/** — Data layer. SQLAlchemy models define the DB schema; Pydantic schemas define API contracts.
- **services/** — Where the work happens. Retrieval, chat orchestration, session management.
- **skills/** — Isolated, testable prompt+logic bundles (Ship 30, artifact gen). Each skill is a self-contained module.
- **agents/** — The routing layer that decides which skill or retrieval path to invoke.

This separation means you can test services without HTTP, swap LLM providers without touching skills, and add new skills without modifying the agent's core logic.
