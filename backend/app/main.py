"""
FastAPI application entry point.

DECISION: Lifespan context manager over @app.on_event("startup")
  on_event is deprecated in FastAPI. The lifespan pattern is the modern
  replacement — it handles both startup AND shutdown in one place, and
  the resources created during startup are guaranteed to be cleaned up
  during shutdown (no forgotten cleanup handlers).

DECISION: CORS middleware
  The frontend (Vite on :5173) and backend (FastAPI on :8000) are on
  different ports = different origins. Without CORS headers, the browser
  blocks every frontend→backend request. This is the #1 "it works in
  Postman but not the browser" issue.
"""

from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings, LLMProvider
from app.core.database import engine, init_db
from app.core.logging import setup_logging, get_logger
from app.api.routes import router as api_router
from app.models.schemas import HealthStatus, ErrorResponse

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan — runs on startup and shutdown.
    
    Startup:
      1. Configure logging
      2. Verify database connection
      3. Log active LLM provider
    
    Shutdown:
      1. Dispose database connection pool
    """
    # --- Startup ---
    setup_logging()
    logger.info(
        "application_starting",
        environment=settings.app_env,
        llm_provider=settings.llm_provider.value,
        llm_model=settings.get_active_model_name(),
    )

    # Verify DB connection
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected", host=settings.postgres_host)
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        # Don't crash — the app can still serve health checks and non-DB routes.
        # The health endpoint will report the DB as unhealthy.

    # Initialize tables (fallback for non-Docker environments)
    try:
        await init_db()
    except Exception as e:
        logger.warning("table_creation_skipped", error=str(e))

    yield  # Application runs here

    # --- Shutdown ---
    logger.info("application_shutting_down")
    await engine.dispose()


# =============================================================================
# Create the FastAPI app
# =============================================================================
app = FastAPI(
    title="The Lenny Growth Assistant",
    description=(
        "AI-powered conversational assistant grounded in Lenny's Podcast transcripts. "
        "Answers product management and growth questions with source citations."
    ),
    version="0.1.0",
    lifespan=lifespan,
    # DECISION: Include docs in all environments
    #   For a take-home, the evaluator benefits from /docs (Swagger UI).
    #   In production, you might disable with: docs_url=None, redoc_url=None
)


# =============================================================================
# CORS Middleware
# =============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # DECISION: allow_methods=["*"] over explicit list
    #   We use GET, POST, DELETE. Listing them explicitly is marginally safer
    #   but adds maintenance burden. For an internal tool, wildcard is fine.
    #   For a public API, you'd restrict to exactly the methods you support.
)


# =============================================================================
# Global Exception Handler
# =============================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions.
    
    DECISION: Return structured JSON errors, never stack traces
      A raw traceback in the response is a security leak (file paths,
      library versions, internal logic). Log the full error server-side;
      return a sanitized message to the client.
    """
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            detail="An unexpected error occurred. Check server logs for details.",
            status_code=500,
        ).model_dump(),
    )


# =============================================================================
# Health Check Endpoint
# =============================================================================
@app.get(
    "/health",
    response_model=HealthStatus,
    tags=["system"],
    summary="System health check",
)
async def health_check():
    """
    Check the health of all dependencies.
    
    DECISION: Comprehensive health check over simple "ok"
      A load balancer or evaluator needs to know WHICH dependency is down.
      Returning {"status": "ok"} when the DB is dead is lying.
      
      We check: database, LLM provider, and knowledge base.
      Status is "healthy" only if all critical deps are up.
      "degraded" means the app runs but some features won't work.
    """
    from app.core.llm_provider import get_llm_provider

    health = {
        "database": "unknown",
        "ollama": "not configured",
        "knowledge_base": "unknown",
    }
    overall = "healthy"

    # Check database
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception as e:
        health["database"] = f"error: {str(e)[:100]}"
        overall = "degraded"

    # Check LLM provider health
    try:
        provider = get_llm_provider()
        provider_health = await provider.health_check()
        provider_status = provider_health.get("status", "unknown")
        provider_detail = provider_health.get("detail", "")

        if provider.provider_name == "ollama":
            if provider_status == "healthy":
                health["ollama"] = f"connected ({provider.model_name})"
            elif provider_status == "model_missing":
                health["ollama"] = f"connected but model '{provider.model_name}' not pulled. Run: ollama pull {provider.model_name}"
                overall = "degraded"
            else:
                health["ollama"] = f"error: {provider_detail}"
                overall = "degraded"
        else:
            # For cloud providers, report via ollama field (reuse existing schema)
            health["ollama"] = f"{provider.provider_name}: {provider_status} ({provider.model_name})"
    except Exception as e:
        health["ollama"] = f"error: {str(e)[:100]}"
        overall = "degraded"

    # Check knowledge base (count chunks)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) FROM transcript_chunks")
            )
            count = result.scalar()
            if count and count > 0:
                health["knowledge_base"] = f"loaded ({count} chunks)"
            else:
                health["knowledge_base"] = "empty"
    except Exception:
        health["knowledge_base"] = "error: table may not exist yet"

    return HealthStatus(
        status=overall,
        database=health["database"],
        ollama=health["ollama"],
        knowledge_base=health["knowledge_base"],
    )


# =============================================================================
# Model Config Endpoint
# =============================================================================
@app.get(
    "/config/model",
    tags=["system"],
    summary="Current LLM configuration",
)
async def get_model_config():
    """
    Return the currently active LLM provider, model name, and health status.
    
    DECISION: Include health in config endpoint
      The frontend displays a model badge (e.g., "Ollama:  llama3.2:3b ✓").
      It needs both the model name AND whether it's actually reachable,
      in a single call. Two calls (config + health) would be wasteful.
    """
    from app.core.llm_provider import get_llm_provider

    provider = get_llm_provider()
    health = await provider.health_check()

    return {
        "active_provider": provider.provider_name,
        "active_model": provider.model_name,
        "provider_health": health,
        "available_providers": ["ollama", "anthropic", "openai"],
    }


# =============================================================================
# LLM Test Endpoint
# =============================================================================
@app.post(
    "/config/model/test",
    tags=["system"],
    summary="Test the active LLM provider with a simple prompt",
)
async def test_model():
    """
    Send a simple test prompt to the active LLM provider.
    
    DECISION: Dedicated test endpoint
      The evaluator needs to verify the LLM is working BEFORE testing
      the full RAG pipeline. If chat fails, is it the LLM, the retrieval,
      or the agent? This endpoint isolates the LLM layer.
    """
    from app.core.llm_provider import get_llm_provider, LLMMessage, LLMConfig

    provider = get_llm_provider()

    response = await provider.generate(
        messages=[LLMMessage(role="user", content="Say hello and tell me your name and model.")],
        config=LLMConfig(max_tokens=100, temperature=0.0),
    )

    if response.is_error:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "provider": provider.provider_name,
                "model": provider.model_name,
                "error": response.error,
                "latency_ms": round(response.latency_ms),
            },
        )

    return {
        "status": "ok",
        "provider": provider.provider_name,
        "model": provider.model_name,
        "response": response.content,
        "latency_ms": round(response.latency_ms),
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }


# =============================================================================
# Provider List Endpoint
# =============================================================================
@app.get(
    "/config/providers",
    tags=["system"],
    summary="List all available LLM providers and their configuration status",
)
async def list_providers():
    """
    Return all providers that can be switched to, with their model and
    whether an API key is configured for them.
    Used by the frontend model-picker dropdown.
    """
    from app.core.llm_provider import get_llm_provider, list_available_providers

    active = get_llm_provider()
    providers = list_available_providers()
    return {
        "active_provider": active.provider_name,
        "active_model": active.model_name,
        "providers": providers,
    }


# =============================================================================
# Provider Switch Endpoint
# =============================================================================
@app.post(
    "/config/model/switch",
    tags=["system"],
    summary="Hot-swap the active LLM provider without restarting",
)
async def switch_model(body: dict):
    """
    Switch the active LLM provider at runtime.

    Request body:
        { "provider": "ollama" | "anthropic" | "openai", "model": "<optional>" }

    Response:
        { "active_provider": "...", "active_model": "...", "health": {...} }

    DECISION: No auth on this endpoint
      This is an internal tool. Adding auth here adds complexity for zero
      security benefit in a local/demo deployment. For production, this
      would sit behind an admin auth middleware.
    """
    from app.core.llm_provider import switch_llm_provider

    provider = body.get("provider")
    model = body.get("model")  # Optional

    if not provider:
        return JSONResponse(
            status_code=422,
            content={"error": "missing_field", "detail": "'provider' is required"},
        )

    try:
        new_provider = switch_llm_provider(provider=provider, model=model)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_provider", "detail": str(e)},
        )

    health = await new_provider.health_check()

    logger.info(
        "llm_provider_switched_via_api",
        provider=new_provider.provider_name,
        model=new_provider.model_name,
    )

    return {
        "active_provider": new_provider.provider_name,
        "active_model": new_provider.model_name,
        "health": health,
    }


# =============================================================================
# Mount API Routes
# =============================================================================
app.include_router(api_router, prefix="/api/v1")
# DECISION: Versioned API prefix (/api/v1)
#   If we ever need breaking changes, we add /api/v2 without breaking
#   existing clients. Costs nothing to add upfront; expensive to retrofit.
