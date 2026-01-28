"""Database connection and session management."""

import logging
from collections.abc import AsyncIterator, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_database_settings

logger = logging.getLogger(__name__)

_db_settings = get_database_settings()

DATABASE_URL = _db_settings.database_url
SYNC_DATABASE_URL = _db_settings.sync_url
ASYNC_DATABASE_URL = _db_settings.async_url

# Log database URLs with password redacted
_redacted_database_url = make_url(DATABASE_URL).render_as_string(hide_password=True)
_redacted_sync_url = make_url(SYNC_DATABASE_URL).render_as_string(hide_password=True)
logger.info(f"Database URL configured: {_redacted_database_url}")
logger.info(f"Sync database URL: {_redacted_sync_url}")

async_engine = create_async_engine(ASYNC_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
sync_engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

engine = sync_engine

# Async session factory - Phase 0 of async transition
AsyncSessionLocal = async_sessionmaker(async_engine, autocommit=False, autoflush=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def get_db() -> Generator[Session]:
    """Get sync database session - Phase 0: kept as primary during async transition."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.close()
        raise
    finally:
        db.close()


async def get_db_async() -> AsyncIterator[AsyncSession]:
    """Get async database session - Phase 0 of async transition (to be used in production)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def test_database_connection() -> bool:
    """Test database connection."""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return True
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
