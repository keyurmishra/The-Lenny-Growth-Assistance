# # =============================================================================
# # Backend Dockerfile — The Lenny Growth Assistant
# # =============================================================================
# #
# # DECISION: python:3.11-slim over python:3.11 (full) or alpine
# #   - slim: ~150MB base. Includes essentials, excludes compilers and dev headers.
# #   - full (~900MB): wasteful for production; we don't need gcc/make at runtime.
# #   - alpine (~50MB): smaller but uses musl libc, which causes silent breakage
# #     with numpy, scipy, and some C-extension Python packages. The 100MB savings
# #     isn't worth hours of debugging cryptic segfaults.
# #
# # DECISION: Single-stage build (no multi-stage)
# #   We have no compile-heavy dependencies that need a build stage.
# #   sentence-transformers installs from wheels. Multi-stage adds complexity
# #   for zero benefit here.
# # =============================================================================

# FROM python:3.11-slim

# # Set working directory
# WORKDIR /app

# # Install system dependencies
# # - curl: for healthcheck endpoint probing
# # - build-essential: some Python packages need C compilation (rare but safe to include)
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends curl build-essential && \
#     rm -rf /var/lib/apt/lists/*
# # Why `--no-install-recommends`? Avoids pulling in ~200MB of "recommended" packages
# # we don't need (man pages, X11 libs, etc.)
# # Why `rm -rf /var/lib/apt/lists/*`? Reduces image size by removing apt cache.

# # Copy and install Python dependencies first (Docker layer caching)
# # If requirements.txt hasn't changed, Docker reuses the cached layer.
# # This means code changes don't trigger a slow pip install.
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt
# # --no-cache-dir: Don't store pip's download cache in the image. Saves ~50-100MB.

# # Copy application code
# COPY . .

# # Expose the API port
# EXPOSE 8000

# # DECISION: uvicorn with --reload for development
# #   In production, you'd use gunicorn with uvicorn workers:
# #   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
# #   For a demo, single-worker with reload is fine.
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]



FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only PyTorch
RUN pip install --no-cache-dir \
    torch==2.5.1 \
    --index-url https://download.pytorch.org/whl/cpu

# Install application dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]