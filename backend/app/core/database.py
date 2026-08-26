"""
Database engine, session factory, and dependency injection.

DECISION: Async SQLAlchemy sessions over sync
  FastAPI handles many concurrent requests on a single thread via async I/O.
  A synchronous DB call blocks that thread — every other request waits.
  Async sessions let the event loop serve other requests while waiting for
  Postgres to respond.

DECISION: Scoped sessions via dependency injection
  Each API request gets its own session (via `get_db()`). The session commits
  or rolls back when the request ends. No shared mutable state between requests.
  This prevents the classic bug: request A's uncommitted writes leaking into
  request B's reads.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# Create the async engine
# pool_size=5: maintain 5 persistent connections.
#   Why 5? Default is fine for a demo. In production, tune to:
#   pool_size = (number_of_uvicorn_workers × 2) capped at Postgres max_connections.
# echo=False: don't log every SQL query. Set to True for debugging.
engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    echo=False,
    connect_args={
        "ssl": "require"
    },
)

# Session factory — produces new AsyncSession instances
# expire_on_commit=False: objects remain usable after commit without re-querying.
#   Default (True) would require a refresh() after every commit, adding latency.
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models.

    DECISION: DeclarativeBase over declarative_base()
      DeclarativeBase is the modern SQLAlchemy 2.0 API. declarative_base()
      is the legacy 1.x API that still works but is discouraged. Using the
      modern API means better type hints and IDE support.
    """
    pass


async def get_db():
    """
    FastAPI dependency that provides a database session per request.

    Usage in route handlers:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...

    The `async with` ensures the session is properly closed even if
    the request handler raises an exception.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Create tables if they don't exist.

    NOTE: In this project, tables are created by init_db.sql via Docker.
    This function is a fallback for running without Docker (e.g., local dev).
    It won't create the pgvector extension — that requires superuser privileges
    that the application DB user may not have.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
