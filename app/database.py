"""Database connection and session management."""

import logging
import os
import time
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_database_settings
from app.performance_diagnostics import record_database_query

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

# Log database URLs with password redacted
_redacted_database_url = make_url(DATABASE_URL).render_as_string(hide_password=True)
_redacted_async_url = make_url(ASYNC_DATABASE_URL).render_as_string(hide_password=True)
logger.info(f"Database URL configured: {_redacted_database_url}")
logger.info(f"Async database URL: {_redacted_async_url}")

# Additional debugging: log environment variables
logger.info(
    f"DATABASE_URL env var: {os.getenv('DATABASE_URL', 'NOT SET')[:50] if os.getenv('DATABASE_URL') else 'NOT SET'}..."
)
logger.info(
    f"TEST_DATABASE_URL env var: {os.getenv('TEST_DATABASE_URL', 'NOT SET')[:50] if os.getenv('TEST_DATABASE_URL') else 'NOT SET'}..."
)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_recycle=3600,
    pool_size=1,
    max_overflow=2,
    pool_timeout=30,
    pool_pre_ping=True,
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
    setattr(context, "_comic_pile_query_started_at", time.perf_counter())


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
    started_at = getattr(context, "_comic_pile_query_started_at", None)
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
    """Get async database session.

    Yields:
        AsyncSession: Database session for use in dependency injection.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def test_database_connection() -> bool:
    """Test database connection.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
