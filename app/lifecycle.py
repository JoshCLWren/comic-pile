"""Application startup lifecycle for local database initialization."""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy import exc as sqlalchemy_exc

from app.database import AsyncSessionLocal, Base, async_engine

logger = logging.getLogger(__name__)


async def init_database(environment: str) -> None:
    """Initialize database tables only for non-production environments.

    Production migrations run in the deployment workflow. A production function
    must not acquire a Neon connection merely to prove connectivity or inspect
    schema state during application startup.

    Args:
        environment: The current application environment.

    Raises:
        RuntimeError: If table creation fails in a non-production environment.
    """
    if environment == "production":
        logger.info(
            "Production database startup is lazy; deployment migrations own schema setup"
        )
        return

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
        except sqlalchemy_exc.DBAPIError as error:
            logger.warning(
                "Database connection attempt %d/%d failed (%s)",
                attempt,
                max_retries,
                type(error).__name__,
            )
            if attempt < max_retries:
                logger.info("Retrying database connection in %d second(s)", retry_delay)
                await asyncio.sleep(retry_delay)
            else:
                logger.error("All database connection attempts failed")

    if not database_ready:
        logger.warning("Skipping local database initialization due to connection failure")
        return

    try:
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")
    except sqlalchemy_exc.DBAPIError as error:
        logger.error("Failed to create database tables (%s)", type(error).__name__)
        raise RuntimeError("Failed to create database tables") from error
