# Session 01 — Environment Setup & Dependency Resolution

**Date:** 2026-08-25  
**Goal:** Install backend Python dependencies and run the FastAPI server.

---

## Problem 1: psycopg2-binary build failure on Python 3.12

### ATTEMPT
```
pip install -r requirements.txt
```
`requirements.txt` contained `psycopg2-binary==2.9.9`

### ERROR
```
Getting requirements to build wheel did not run successfully.
× Getting requirements to build wheel did not run successfully.
note: you may need to install Visual Studio build tools with the "C++ build tools" workload
error: could not compile `proc-macro2` (build script)
```

### DIAGNOSIS
`psycopg2-binary 2.9.9` does not provide a pre-built wheel for Python 3.12 on Windows. It falls back to compiling from source, which requires Rust/MSVC build tools — neither of which were installed.

Additionally, the codebase was using `psycopg2` (version 2) while the async driver we needed for SQLAlchemy's `asyncpg` is `psycopg` (version 3).

### FIX
Replaced `psycopg2-binary==2.9.9` with `psycopg[binary]==3.2.1` in `requirements.txt`.  
Updated all database connection strings from `postgresql://` to `postgresql+asyncpg://` (asyncpg is the async driver that ships with psycopg3).

Updated `scripts/ingest.py` to use psycopg3 connection API:
```python
# Before (psycopg2)
import psycopg2
conn = psycopg2.connect(dsn)

# After (psycopg3)
import psycopg
conn = psycopg.connect(dsn)
```

### DECISION RECORDED
Added comment in `requirements.txt`:
```
# psycopg3 (not psycopg2) — provides async support for SQLAlchemy asyncpg
# psycopg2 does not ship Python 3.12 wheels on Windows, causing source compilation failures
```

---

## Problem 2: Python 3.12 not found by py launcher

### ATTEMPT
```
py -3.12 -m venv .venv
```

### ERROR
```
No suitable Python runtime found
Pass --list (-0) to see all detected environments on your machine
```

### DIAGNOSIS
The system had Python 3.11 installed but not 3.12. The `py` launcher (Windows Python Launcher) only knows about versions registered in the Windows registry. A fresh Python 3.12 install via python.org was needed.

### FIX
Downloaded and installed Python 3.12 from https://www.python.org/downloads/  
Confirmed with `py -0` that 3.12 appeared in the launcher list.  
Re-ran: `py -3.12 -m venv .venv`

---

## Problem 3: pydantic-core Rust compilation failure

### ATTEMPT
Second `pip install` attempt after Python 3.12 install.

### ERROR
```
link: extra operand 'C:\...\proc-macro2-21bc178692270b8a\build_script_build...'
note: link.exe returned an unexpected error
note: you may need to install Visual Studio build tools with the "C++ build tools" workload
```

### DIAGNOSIS
`pydantic-core` requires Rust compilation when no pre-built wheel is available. The system had no `link.exe` (MSVC linker).

### FIX
Pinned `pydantic` and `pydantic-core` to versions that provide Windows wheels:
```
pydantic==2.7.4
pydantic-core==2.18.4
```
These versions have pre-built `.whl` files for Python 3.12 on Windows x64, eliminating the Rust compilation step.

---

## Outcome

After all three fixes, `pip install -r requirements.txt` succeeded in ~2 minutes.  
Backend started successfully with `uvicorn app.main:app --reload --port 8000`.
