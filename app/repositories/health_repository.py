"""Health query construction and persistence.

All SQLAlchemy access for health probes lives here. Functions return plain
values; callers (services) own transactions and error handling.
"""

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event


async def execute_database_ping(db: AsyncSession) -> None:
    """Execute the cheapest read-only database round trip.

    Args:
        db: Async database session.

    Raises:
        Exception: If the database is unavailable.
    """
    await db.execute(text("SELECT 1"))


async def check_recent_activity(db: AsyncSession, cutoff_seconds: int) -> bool:
    """Check if there's recent session activity within the inactivity threshold.

    Args:
        db: Database session.
        cutoff_seconds: Inactivity threshold in seconds.

    Returns:
        True if recent activity exists, False otherwise.
    """
    from datetime import UTC, datetime, timedelta

    cutoff_time = datetime.now(UTC) - timedelta(seconds=cutoff_seconds)

    result = await db.execute(
        select(func.max(Event.timestamp)).where(Event.timestamp >= cutoff_time)
    )
    last_event_time = result.scalar_one_or_none()
    return last_event_time is not None