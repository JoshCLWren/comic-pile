"""Analytics metrics query construction and persistence.

All SQLAlchemy access for the analytics metrics surface lives here. Functions
return ORM rows or plain values; the analytics service owns aggregation and
serialization; the router owns HTTP concerns.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel

RECENT_SESSIONS_LIMIT = 5
TOP_THREADS_LIMIT = 5
TOP_RATING_THRESHOLD = 4.0


async def count_threads(
    db: AsyncSession,
    user_id: int,
    *,
    status: str | None = None,
) -> int:
    """Count a user's threads, optionally filtered by thread status.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        status: Optional thread status filter (e.g. ``"active"``).

    Returns:
        The matching thread count (0 when none exist).
    """
    query = select(func.count(Thread.id)).where(Thread.user_id == user_id)
    if status is not None:
        query = query.where(Thread.status == status)
    return await db.scalar(query) or 0


async def average_session_hours(db: AsyncSession, user_id: int) -> int | float:
    """Return the mean duration in hours of a user's ended reading sessions.

    Args:
        db: Database session.
        user_id: Owner of the sessions.

    Returns:
        The average session length rounded to one decimal, or 0 when there are
        no ended sessions.
    """
    result = await db.scalar(
        select(
            func.avg(
                func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600
            )
        ).where(
            SessionModel.user_id == user_id,
            SessionModel.ended_at.isnot(None),
        )
    )
    return round(result, 1) if result is not None else 0


async def recent_sessions(
    db: AsyncSession,
    user_id: int,
    *,
    since: datetime,
    limit: int = RECENT_SESSIONS_LIMIT,
) -> list[SessionModel]:
    """Return a user's most recent sessions started on or after ``since``.

    Args:
        db: Database session.
        user_id: Owner of the sessions.
        since: Earliest ``started_at`` boundary for inclusion.
        limit: Maximum number of sessions to return.

    Returns:
        Sessions ordered newest first, at most ``limit`` rows.
    """
    result = await db.scalars(
        select(SessionModel)
        .where(
            SessionModel.user_id == user_id,
            SessionModel.started_at >= since,
        )
        .order_by(SessionModel.started_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def event_type_counts(db: AsyncSession, user_id: int) -> dict[str, int]:
    """Count a user's events grouped by event type.

    Args:
        db: Database session.
        user_id: Owner of the sessions that events belong to.

    Returns:
        Mapping of event type to its count across the user's sessions.
    """
    result = await db.execute(
        select(Event.type, func.count(Event.id))
        .join(SessionModel, Event.session_id == SessionModel.id)
        .where(SessionModel.user_id == user_id)
        .group_by(Event.type)
    )
    rows = result.all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row[0])] = int(row[1])
    return counts


async def top_rated_threads(
    db: AsyncSession,
    user_id: int,
    *,
    threshold: float = TOP_RATING_THRESHOLD,
    limit: int = TOP_THREADS_LIMIT,
) -> list[Thread]:
    """Return a user's highest-rated threads at or above a rating threshold.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        threshold: Minimum ``last_rating`` required for inclusion.
        limit: Maximum number of threads to return.

    Returns:
        Threads ordered by ``last_rating`` descending, at most ``limit`` rows.
    """
    result = await db.scalars(
        select(Thread)
        .where(
            Thread.user_id == user_id,
            Thread.last_rating.isnot(None),
            Thread.last_rating >= threshold,
        )
        .order_by(Thread.last_rating.desc())
        .limit(limit)
    )
    return list(result.all())
