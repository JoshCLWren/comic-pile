"""Roll query construction and persistence.

All SQLAlchemy access for roll-related model families lives here.
Functions return ORM models or plain tuples/dicts; callers
(services) own transaction boundaries.
"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


from app.models import (
    Event,
    Issue,
    ReadingSession,
    Snapshot,
    Thread,
)
from app.models.recommendation_context import RecommendationContext as RecContextModel


async def fetch_session_for_roll(
    db: AsyncSession, user_id: int,
) -> ReadingSession | None:
    """Return the active session for a user.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active (non-ended) session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_session_by_id(
    db: AsyncSession, session_id: int,
) -> ReadingSession | None:
    """Return a session by primary key.

    Args:
        db: Database session.
        session_id: Primary key of the session.

    Returns:
        The session, or None when it does not exist.
    """
    return await db.get(ReadingSession, session_id)


async def fetch_thread_by_id(
    db: AsyncSession, thread_id: int, user_id: int, *, for_update: bool = False
) -> Thread | None:
    """Find a thread by ID scoped to its owner.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.
        user_id: Owner that must own the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread, or None when absent or foreign.
    """
    query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def fetch_issue_by_id(
    db: AsyncSession, issue_id: int,
) -> Issue | None:
    """Return an issue by primary key.

    Args:
        db: Database session.
        issue_id: Primary key of the issue.

    Returns:
        The issue, or None when it does not exist.
    """
    return await db.get(Issue, issue_id)


async def fetch_session_events(
    db: AsyncSession, session_id: int,
) -> list[Event]:
    """Return all events for a session in chronological order.

    Args:
        db: Database session.
        session_id: Session whose events are fetched.

    Returns:
        Events ordered by timestamp.
    """
    result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    return list(result.scalars().all())


async def fetch_bounded_roll_pool_rows(
    db: AsyncSession,
    user_id: int,
    current_die: int,
    snoozed_ids: list[int] | None = None,
    skipped_ids: list[int] | None = None,
) -> list[tuple[Thread, int, str | None]]:
    """Return the bounded roll-candidate pool for a user.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        current_die: Current die size; caps pool size.
        snoozed_ids: Thread IDs to exclude.
        skipped_ids: Thread IDs to exclude.

    Returns:
        List of ``(Thread, unread_count, next_issue_number)`` tuples.
    """
    from comic_pile.queue import get_bounded_roll_pool_rows

    return await get_bounded_roll_pool_rows(
        user_id, db, current_die, snoozed_ids, skipped_ids
    )


async def insert_event(db: AsyncSession, event: Event) -> None:
    """Persist an Event row.

    Args:
        db: Database session.
        event: Event instance to add.
    """
    db.add(event)


async def insert_recommendation_context(
    db: AsyncSession, context: RecContextModel
) -> None:
    """Persist a RecommendationContext row.

    Args:
        db: Database session.
        context: RecommendationContext instance to add.
    """
    db.add(context)


async def update_session_pending_thread(
    db: AsyncSession,
    session_id: int,
    thread_id: int | None,
    now: datetime,
) -> None:
    """Set or clear the pending thread on a session.

    Args:
        db: Database session.
        session_id: Session to update.
        thread_id: Thread ID to set as pending, or None to clear.
        now: Timestamp for the update.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.id == session_id)
        .values(
            pending_thread_id=thread_id,
            pending_thread_updated_at=now,
        )
    )


async def fetch_latest_session_event(db: AsyncSession, session_id: int) -> Event | None:
    """Return the session's most recent event, or None.

    Backs the #3467 duplicate-override guard: the latest event identifies
    whether the immediately preceding action was already an override of the
    same series, which is what a double-clicked "Pick this series" produces.

    Args:
        db: Database session.
        session_id: Session whose newest event should be read.

    Returns:
        The newest Event in the session, ordered by timestamp then id, or None
        when the session has no events.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def fetch_pending_thread_id(db: AsyncSession, session_id: int) -> int | None:
    """Return the session's committed pending thread id, or None.

    Companion signal to ``fetch_latest_session_event`` for the #3467 guard. A
    pending pointer is required alongside the trailing override so a repeat pick
    is only suppressed while the first one is still the live, unconsumed
    selection.

    Args:
        db: Database session.
        session_id: Session whose pending pointer should be read.

    Returns:
        The pending thread id when a roll is awaiting consumption, else None.
    """
    result = await db.execute(
        select(ReadingSession.pending_thread_id).where(ReadingSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def clear_session_pending(db: AsyncSession, session_id: int, now: datetime) -> None:
    """Clear the pending thread on a session.

    Args:
        db: Database session.
        session_id: Session to update.
        now: Timestamp for the update.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.id == session_id)
        .values(pending_thread_id=None, pending_thread_updated_at=now)
    )


async def update_session_skipped(
    db: AsyncSession,
    session_id: int,
    skipped_ids: list[int],
) -> None:
    """Update the skipped thread list on a session.

    Args:
        db: Database session.
        session_id: Session to update.
        skipped_ids: New list of skipped thread IDs.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.id == session_id)
        .values(skipped_thread_ids=skipped_ids)
    )


async def fetch_session_for_unskip(
    db: AsyncSession, user_id: int,
) -> ReadingSession | None:
    """Return the active session for unskip operations.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_active_session(
    db: AsyncSession, user_id: int,
) -> ReadingSession | None:
    """Return the active session for a user.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_current_die_for_session(
    db: AsyncSession, session_id: int,
) -> int:
    """Return the current die size for a session.

    Args:
        db: Database session.
        session_id: Session ID.

    Returns:
        The current die size.
    """
    from comic_pile.reading_session import get_current_die_for_session as _get_die
    from app.models import ReadingSession
    session = await db.get(ReadingSession, session_id)
    if session is None:
        return 1
    return await _get_die(session, db)


async def count_snapshots(db: AsyncSession, session_id: int) -> int:
    """Count snapshots for a session.

    Args:
        db: Database session.
        session_id: Session whose snapshots are counted.

    Returns:
        Number of snapshots (0 when none exist).
    """
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
    )
    return result.scalar() or 0


async def fetch_recommendation_explanation(
    db: AsyncSession, event_id: int, user_id: int,
) -> tuple[Event | None, ReadingSession | None]:
    """Fetch event and session for recommendation explanation.

    Args:
        db: Database session.
        event_id: Event ID to look up.
        user_id: Owner of the session that generated the event.

    Returns:
        Tuple of (Event, Session) or (None, None) when not found.
    """
    result = await db.execute(
        select(Event, ReadingSession)
        .join(ReadingSession, Event.session_id == ReadingSession.id)
        .where(Event.id == event_id)
    )
    row = result.one_or_none()
    if row is None:
        return None, None
    event, session = row
    if session.user_id != user_id:
        return None, None
    if event.type != "roll":
        return None, None
    return event, session
