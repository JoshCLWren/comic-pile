"""Application startup lifecycle (database initialization)."""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy import exc as sqlalchemy_exc

from app.database import AsyncSessionLocal, Base, async_engine

logger = logging.getLogger(__name__)


async def init_database(environment: str) -> None:
    """Connect to the database with retries and create tables in non-production envs.

    Attempts to connect to the database up to three times with a fixed delay.
    In non-production environments, creates tables via SQLAlchemy metadata.
    In production, table creation is skipped (migrations are required).

    Args:
        environment: The current application environment.

    Raises:
        RuntimeError: If table creation fails in a non-production environment.
    """
    max_retries = 3
    retry_delay = 1

    database_ready = False
    for attempt in range(1, max_retries + 1):
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
                database_ready = True
                logger.info("Database connection established successfully")
                break
        except sqlalchemy_exc.DBAPIError as e:
            # Catch database connection and execution errors (OperationalError, InterfaceError, etc.)
            logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("All database connection attempts failed")

    if database_ready:
        if environment == "production":
            logger.info("Production mode: Skipping table creation (migrations required)")
        else:
            try:
                async with async_engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.info("Database tables created successfully")
            except sqlalchemy_exc.DBAPIError as e:
                # Fail fast instead of exiting the process from inside the app factory.
                logger.error(f"Failed to create database tables: {e}")
                raise RuntimeError(f"Failed to create database tables: {e}") from e
    else:
        logger.warning("Skipping database initialization due to connection failure")
