"""Keep-alive query construction and persistence.

All SQLAlchemy access for the Neon warm-pool keep-alive probe lives here.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def execute_keepalive_ping(db: AsyncSession) -> None:
    """Execute the cheapest read-only database round trip for keep-alive.

    Args:
        db: Async database session.
    """
    await db.execute(text("SELECT 1"))
