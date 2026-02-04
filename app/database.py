"""Database connection and session management."""

import logging
import os
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_database_settings

logger = logging.getLogger(__name__)

_db_settings = get_database_settings()

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
    pool_size=5,
    max_overflow=10,
    pool_timeout=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(async_engine, autocommit=False, autoflush=False)


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
