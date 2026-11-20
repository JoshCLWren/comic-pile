"""Keep-alive business logic and orchestration.

Query construction lives in ``app/repositories/keepalive_repository.py``.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import keepalive_repository


async def warm_database(db: AsyncSession) -> str:
    """Run a minimal database round trip to keep the Neon pool warm.

    Args:
        db: Async database session.

    Returns:
        Status string confirming the round trip succeeded.
    """
    await keepalive_repository.execute_keepalive_ping(db)
    return "warmed"
