# Session 02 — Database Connection Bugs (Supabase + pgvector)

**Date:** 2026-08-25  
**Goal:** Connect the FastAPI backend to Supabase PostgreSQL and run the transcript ingestion script.

---

## Problem 1: `getaddrinfo failed` — DNS resolution error

### ATTEMPT
Started the backend with Supabase credentials in `.env`.

### ERROR
```
2026-08-25T08:18:56.087425Z [error] database_connection_failed [app.main]
error=[Errno 11001] getaddrinfo failed
```

### DIAGNOSIS
`getaddrinfo` is a DNS lookup — the hostname wasn't being resolved. There were two causes:

**Cause A — URL encoding of special characters in password:**  
The Supabase database password contained `@` characters (e.g., `p@ssw0rd`). In a PostgreSQL connection string, `@` is the separator between credentials and hostname:
```
postgresql://user:p@ssw0rd@host:5432/db
             ↑ This @ ends the password section — host = "ssw0rd@host"
```
The `asyncpg` driver was trying to connect to `ssw0rd@host` (the garbage substring) instead of the real Supabase host.

**Cause B — Whitespace in `.env` values:**  
The `.env` file had values like:
```
POSTGRES_HOST=db.abcxyz.supabase.co 
```
(trailing space after the hostname). The `Settings` class was not stripping whitespace, so the hostname passed to `asyncpg` was `"db.abcxyz.supabase.co "` (with space) — which fails DNS lookup.

### FIX 1 — URL-encode the password
Updated `config.py` to use `urllib.parse.quote_plus()`:
```python
from urllib.parse import quote_plus

@property
def database_url(self) -> str:
    password = quote_plus(self.postgres_password.strip())
    return (
        f"postgresql+asyncpg://"
        f"{self.postgres_user.strip()}:{password}"
        f"@{self.postgres_host.strip()}:{self.postgres_port}"
        f"/{self.postgres_db.strip()}"
    )
```

### FIX 2 — Strip whitespace from all config fields
Added `.strip()` to every field used in connection strings. `pydantic-settings` doesn't strip whitespace by default — values are passed verbatim from the `.env` file.

```python
# Before (vulnerable to whitespace)
f"@{self.postgres_host}:{self.postgres_port}"

# After (explicit strip)
f"@{self.postgres_host.strip()}:{self.postgres_port}"
```

### DECISION RECORDED
Added this note in `config.py`:
```python
# IMPORTANT: Always call .strip() on env vars used in connection strings.
# .env files frequently have trailing spaces/newlines that cause silent DNS failures.
# quote_plus() handles passwords with @, #, %, or spaces that would break URL parsing.
```

---

## Problem 2: pgvector extension not enabled

### ATTEMPT
Ran `scripts/ingest.py` to load transcripts.

### ERROR
```
asyncpg.exceptions.UndefinedObjectError: type "vector" does not exist
```

### DIAGNOSIS
The `transcript_chunks` table uses `VECTOR(384)` as the column type. This type is provided by the `pgvector` extension. The extension was not enabled in the Supabase database.

### FIX
Connected to Supabase via the SQL editor and ran:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then confirmed with:
```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

Supabase supports pgvector natively — it just needs to be explicitly enabled per database.

---

## Problem 3: Ingestion script failing silently on duplicate chunks

### ATTEMPT
Re-ran `scripts/ingest.py` after fixing the extension.

### SYMPTOM
Script completed with `0 errors` but chunk count didn't increase on re-runs.

### DIAGNOSIS
The ingestion script used `INSERT INTO transcript_chunks ...` without upsert logic. On re-run, PostgreSQL raised a unique constraint violation (transcript_name + chunk_index), which the script caught and silently swallowed.

### FIX
Changed to upsert:
```sql
INSERT INTO transcript_chunks (transcript_name, content, chunk_index, metadata, embedding)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (transcript_name, chunk_index) DO UPDATE
SET content = EXCLUDED.content,
    embedding = EXCLUDED.embedding,
    metadata = EXCLUDED.metadata;
```

This makes ingestion idempotent — safe to re-run when new transcripts are added.

---

## Outcome

After all three fixes:
- Backend connected to Supabase successfully on startup
- Ingestion script loaded ~48,000 chunks from ~303 transcripts
- Re-running ingestion is safe (idempotent upsert)
- Health endpoint correctly reports `"knowledge_base": "loaded (48231 chunks)"`
