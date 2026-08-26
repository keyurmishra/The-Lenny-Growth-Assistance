"""
Structured logging configuration.

DECISION: structlog with JSON output over stdlib logging
  When debugging "why did the model return garbage for session X?", you need:
    {"level": "warning", "session_id": "abc-123", "model": " llama3.2:3b",
     "retrieval_count": 0, "event": "empty_retrieval_results"}

  Not:
    WARNING:app.services.chat:Something went wrong

  JSON logs are grep-able, jq-able, and ingestible by any log aggregator
  (Datadog, CloudWatch, ELK). Plain text logs are not.

TRADE-OFF: structlog adds ~50 lines of setup. Worth it for any project
  that will ever need debugging (i.e., all of them).
"""

import logging
import sys

import structlog

from app.core.config import settings


def setup_logging() -> None:
    """Configure structured logging for the application."""

    # Determine if we should output JSON (production) or colored console (dev)
    is_dev = settings.app_env == "development"

    # Shared processors — run on every log event
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        # ^ Merges context variables (like request_id) bound via structlog.contextvars
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_dev:
        # Development: colored, human-readable output
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # Production: JSON lines — one JSON object per log event
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure the stdlib root logger to use structlog's formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named logger instance.

    Usage:
        logger = get_logger(__name__)
        logger.info("chat_response_generated", session_id=sid, model=" llama3.2:3b", latency_ms=234)
    """
    return structlog.get_logger(name)
