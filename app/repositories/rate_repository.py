"""Rate pipeline query construction and persistence.

All SQLAlchemy access for the rate/undo pipeline lives here. Functions
return ORM models, plain rows/tuples, or IDs; callers (services) own
transaction boundaries.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread


async def fetch_source_roll_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
) -> int | None:
    """Return the ID of the most recent roll event selecting a thread.

    Args:
        db: Database session.
        session_id: Session to search within.
        thread_id: Thread whose originating roll event is sought.

    Returns:
        The ID of the most recent roll event selecting this thread,
        or None when no such event exists.
    """
    result = await db.execute(
        select(Event.id)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_user_rated_threads(
    db: AsyncSession,
    user_id: int,
    min_rating: float = 3.5,
    limit: int = 50,
) -> list[tuple[int, str, float]]:
    """Fetch threads the user has rated at or above a threshold.

    Returns thread ID, title, and rating for the user's highest-rated threads,
    ordered by rating descending then most recent first.

    Args:
        db: Database session.
        user_id: The user whose ratings to fetch.
        min_rating: Minimum rating threshold (default 3.5 for "liked" comics).
        limit: Maximum number of threads to return.

    Returns:
        List of (thread_id, title, rating) tuples.
    """
    result = await db.execute(
        select(Event.thread_id, Thread.title, Event.rating)
        .join(Thread, Thread.id == Event.thread_id)
        .where(Event.type == "rate")
        .where(Thread.user_id == user_id)
        .where(Event.rating >= min_rating)
        .where(Event.thread_id.is_not(None))
        .order_by(Event.rating.desc(), Event.timestamp.desc())
        .limit(limit)
    )
    return [(row.thread_id, row.title, row.rating) for row in result.all()]


async def fetch_user_recent_rated_threads(
    db: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> list[tuple[int, str, float]]:
    """Fetch the user's most recently rated threads.

    Returns thread ID, title, and rating for the user's most recent ratings,
    ordered by timestamp descending.

    Args:
        db: Database session.
        user_id: The user whose ratings to fetch.
        limit: Maximum number of threads to return.

    Returns:
        List of (thread_id, title, rating) tuples.
    """
    result = await db.execute(
        select(Event.thread_id, Thread.title, Event.rating)
        .join(Thread, Thread.id == Event.thread_id)
        .where(Event.type == "rate")
        .where(Thread.user_id == user_id)
        .where(Event.thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
        .limit(limit)
    )
    return [(row.thread_id, row.title, row.rating) for row in result.all()]
