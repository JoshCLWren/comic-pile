"""Database connection and session management."""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator

from fastapi import HTTPException, status
from sqlalchemy import event, exc as sqlalchemy_exc, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_database_settings
from app.performance_diagnostics import record_database_query
from app.safe_logging import safe_connection_metadata, safe_exception_metadata

logger = logging.getLogger(__name__)

_db_settings = get_database_settings()

# Use test_database_url if in test environment, otherwise use database_url
if (
    os.getenv("ENVIRONMENT") == "test" or os.getenv("TEST_ENVIRONMENT") == "true"
) and _db_settings.test_database_url:
    DATABASE_URL = _db_settings.test_database_url
else:
    DATABASE_URL = _db_settings.database_url
ASYNC_DATABASE_URL = _db_settings.async_url

# Keep a missing or sleeping Neon endpoint from holding a serverless request open
# indefinitely. The dependency timeout covers the first pool acquisition, while
# asyncpg's connect and command timeouts bound lower-level network waits.
DATABASE_DEPENDENCY_TIMEOUT_SECONDS = 10.0
DATABASE_CONNECT_TIMEOUT_SECONDS = 3.0
DATABASE_COMMAND_TIMEOUT_SECONDS = 8.0

# Log only an allowlisted metadata projection. Rendering a URL, even with its
# password hidden, risks exposing usernames, query credentials, or encoded secrets.
logger.info(
    "Database configured",
    extra={"database": safe_connection_metadata(ASYNC_DATABASE_URL)},
)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_recycle=3600,
    pool_size=1,
    max_overflow=2,
    pool_timeout=DATABASE_CONNECT_TIMEOUT_SECONDS,
    pool_pre_ping=True,
    connect_args={
        "timeout": DATABASE_CONNECT_TIMEOUT_SECONDS,
        "command_timeout": DATABASE_COMMAND_TIMEOUT_SECONDS,
    },
)


@event.listens_for(async_engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(
    connection: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Start timing a SQL statement after a connection has been acquired."""
    del connection, cursor, statement, parameters, executemany
    vars(context)["_comic_pile_query_started_at"] = time.perf_counter()


@event.listens_for(async_engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(
    connection: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Record SQL execution time in the active request diagnostics context."""
    del connection, cursor, statement, parameters, executemany
    started_at = vars(context).get("_comic_pile_query_started_at")
    if isinstance(started_at, float):
        record_database_query((time.perf_counter() - started_at) * 1000)


AsyncSessionLocal = async_sessionmaker(
    async_engine,
    autocommit=False,
    autoflush=True,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """Get an async database session with bounded first connection acquisition.

    Yields:
        AsyncSession: Database session for use in dependency injection.

    Raises:
        HTTPException: If the first pool acquisition cannot complete within the
            configured dependency timeout.
    """
    started_at = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            async with asyncio.timeout(DATABASE_DEPENDENCY_TIMEOUT_SECONDS):
                await session.connection()
            logger.info(
                "database_dependency_opened duration_ms=%.2f",
                (time.perf_counter() - started_at) * 1000,
            )
            try:
                yield session
            finally:
                await session.close()
    except (TimeoutError, sqlalchemy_exc.TimeoutError, sqlalchemy_exc.DBAPIError) as error:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "database_dependency_unavailable duration_ms=%.2f limit_seconds=%.1f error=%s",
            elapsed_ms,
            DATABASE_DEPENDENCY_TIMEOUT_SECONDS,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable",
        ) from error


async def test_database_connection() -> bool:
    """Test database connection.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        async with asyncio.timeout(DATABASE_DEPENDENCY_TIMEOUT_SECONDS):
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
                return True
    except Exception as error:
        logger.error(
            "Database connection test failed",
            extra={"database_error": safe_exception_metadata(error)},
        )
        return False
