"""Database connection and session management."""

import logging
import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable must be set (or provided via a .env file)")

logger.info(f"Database URL configured: {DATABASE_URL.split('@')[0]}@...")

if DATABASE_URL.startswith("postgresql://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    SYNC_DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
else:
    ASYNC_DATABASE_URL = DATABASE_URL
    SYNC_DATABASE_URL = DATABASE_URL

logger.info(f"Sync database URL: {SYNC_DATABASE_URL.split('@')[0]}@...")

async_engine = create_engine(ASYNC_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
sync_engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

engine = sync_engine

AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=async_engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def get_db() -> Generator[Session]:
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.close()
        raise
    finally:
        db.close()


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
