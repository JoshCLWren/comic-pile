"""Snooze backoff query construction for cross-session eligibility.

All SQLAlchemy access used to derive durable snooze state across reading
sessions lives here. Functions return plain rows or ORM values; the service
layer owns the eligibility policy and transaction boundaries.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread

from app.repositories.reading_eligibility_queries import candidate_predicate
from app.services.reading_eligibility_service import ReadingEligibilitySnapshot

SnoozeBackoffRow = tuple[int, datetime | None, str | None, datetime | None, int]


async def fetch_snooze_backoff_rows(
    db: AsyncSession, user_id: int, *, eligibility: ReadingEligibilitySnapshot | None = None
) -> list[SnoozeBackoffRow]:
    """Return snooze evidence rows for a user's active, unblocked threads.

    Each row pairs an active thread with one of its ``snooze`` or ``unsnooze``
    events. Threads without such events appear exactly once with ``None``
    event values courtesy of the left outer join. The join is filtered to only
    the two relevant event types so the existing event-type index narrows the
    set efficiently.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        eligibility: Shared live eligibility, or None for legacy execution.

    Returns:
        Rows of ``(thread_id, last_activity_at, event_type, event_timestamp,
        event_id)`` ordered by thread ID then event timestamp.
    """
    result = await db.execute(
        select(Thread.id, Thread.last_activity_at, Event.type, Event.timestamp, Event.id)
        .outerjoin(
            Event,
            (Event.thread_id == Thread.id)
            & Event.type.in_(("snooze", "unsnooze"))
            # Native Roll rerolls record a snooze for history/die projection,
            # but their temporary exclusion is browser-cookie state. They must
            # not create durable cross-session backoff or block Read now.
            & Event.context.op("->>")("dice_command_key").is_(None),
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(candidate_predicate(eligibility))
        .order_by(Thread.id, Event.timestamp, Event.id)
    )
    return [(row[0], row[1], row[2], row[3], row[4]) for row in result.all()]


async def fetch_user_session_started_ats(db: AsyncSession, user_id: int) -> list[datetime]:
    """Return the ordered reading-session start times for a user.

    Args:
        db: Database session.
        user_id: Owner of the sessions.

    Returns:
        All ``started_at`` values for the user's sessions, oldest first.
    """
    result = await db.execute(
        select(ReadingSession.started_at)
        .where(ReadingSession.user_id == user_id)
        .order_by(ReadingSession.started_at)
    )
    return list(result.scalars().all())
