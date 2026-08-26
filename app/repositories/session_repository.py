"""Session, event, and snapshot query construction and persistence.

All SQLAlchemy access for the ``Session``/``Event``/``Snapshot`` model family
lives here. Functions return ORM models or plain values; callers (services)
own transaction boundaries.
"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session as SessionModel, Snapshot


async def get_session(db: AsyncSession, session_id: int) -> SessionModel | None:
    """Return a session by primary key.

    Args:
        db: Database session.
        session_id: Primary key of the reading session.

    Returns:
        The session, or None when it does not exist.
    """
    return await db.get(SessionModel, session_id)


async def find_owned(
    db: AsyncSession, user_id: int, session_id: int
) -> SessionModel | None:
    """Find a session by ID scoped to its owner.

    Args:
        db: Database session.
        user_id: Owner that must own the session.
        session_id: Primary key of the session.

    Returns:
        The owned session, or None when absent or foreign.
    """
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def fetch_active_session(db: AsyncSession, user_id: int) -> SessionModel | None:
    """Return a user's most recently started session that has not ended.

    Args:
        db: Database session.
        user_id: Owner of the sessions.

    Returns:
        The latest un-ended session, or None when none exists.
    """
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == user_id)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def fetch_history_page(
    db: AsyncSession,
    user_id: int,
    *,
    cursor: tuple[datetime, int] | None,
    limit: int,
) -> list[SessionModel]:
    """Fetch one page of a user's session history, newest first.

    Args:
        db: Database session.
        user_id: Owner of the sessions.
        cursor: Decoded ``(started_at, id)`` continuation cursor, or None for
            the first page.
        limit: Maximum number of sessions to return.

    Returns:
        Sessions in canonical page order, at most ``limit`` rows.
    """
    query = select(SessionModel).where(SessionModel.user_id == user_id)
    query = query.order_by(SessionModel.started_at.desc(), SessionModel.id.desc())

    if cursor is not None:
        cursor_started_at, cursor_id = cursor
        query = query.where(
            (SessionModel.started_at < cursor_started_at)
            | ((SessionModel.started_at == cursor_started_at) & (SessionModel.id > cursor_id))
        )

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def latest_action_event(
    db: AsyncSession, session_id: int, event_types: tuple[str, ...]
) -> Event | None:
    """Return the most recent event of the given types for a session.

    Args:
        db: Database session.
        session_id: Session whose events are searched.
        event_types: Event types to consider.

    Returns:
        The newest matching event ordered by ``(timestamp desc, id desc)``, or
        None when no such event exists.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type.in_(event_types))
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    return result.scalars().first()


async def latest_roll_event(db: AsyncSession, session_id: int) -> Event | None:
    """Return the most recent roll event that selected a thread.

    Args:
        db: Database session.
        session_id: Session whose events are searched.

    Returns:
        The newest roll event with a selected thread, or None.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    return result.scalars().first()


async def events_chronological(db: AsyncSession, session_id: int) -> list[Event]:
    """Return every event of a session in chronological order.

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


async def die_change_events(db: AsyncSession, session_id: int) -> list[Event]:
    """Return rate/snooze/undo events that changed the die for a session.

    Args:
        db: Database session.
        session_id: Session whose events are fetched.

    Returns:
        Die-changing events in chronological order with a known ``die_after``.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type.in_(("rate", "snooze", "undo")))
        .where(Event.die_after.is_not(None))
        .order_by(Event.timestamp, Event.id)
    )
    return list(result.scalars().all())


async def history_events_for_sessions(
    db: AsyncSession, session_ids: list[int]
) -> list[Event]:
    """Return roll and die-change events for many sessions in projection order.

    Args:
        db: Database session.
        session_ids: Session IDs to load events for.

    Returns:
        Events ordered by ``(session_id, timestamp, id)`` suitable for the
        linear session-history projection.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id.in_(session_ids))
        .where(
            (Event.type == "roll") & (Event.selected_thread_id.is_not(None))
            | (Event.type.in_(("rate", "snooze", "undo"))) & (Event.die_after.is_not(None))
        )
        .order_by(Event.session_id, Event.timestamp, Event.id)
    )
    return list(result.scalars().all())


async def count_snapshots(db: AsyncSession, session_id: int) -> int:
    """Count snapshots recorded for a session.

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


async def snapshot_counts_by_session(
    db: AsyncSession, session_ids: list[int]
) -> dict[int, int]:
    """Count snapshots for many sessions in one grouped query.

    Args:
        db: Database session.
        session_ids: Session IDs to count snapshots for.

    Returns:
        Mapping of session ID to snapshot count; absent IDs have zero.
    """
    result = await db.execute(
        select(Snapshot.session_id, func.count())
        .where(Snapshot.session_id.in_(session_ids))
        .group_by(Snapshot.session_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def snapshots_desc(db: AsyncSession, session_id: int) -> list[Snapshot]:
    """List a session's snapshots, newest first.

    Args:
        db: Database session.
        session_id: Session whose snapshots are fetched.

    Returns:
        Snapshots ordered by creation date descending (ID descending as
        tie-breaker).
    """
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    return list(result.scalars().all())


async def first_start_snapshot(db: AsyncSession, session_id: int) -> Snapshot | None:
    """Return the earliest "Session start" snapshot of a session.

    Args:
        db: Database session.
        session_id: Session whose snapshots are searched.

    Returns:
        The first session-start snapshot by creation time, or None.
    """
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .where(Snapshot.description == "Session start")
        .order_by(Snapshot.created_at)
    )
    return result.scalars().first()


async def detach_pending_thread_references(db: AsyncSession, thread_id: int) -> None:
    """Clear pending-thread pointers on sessions referencing a thread.

    Args:
        db: Database session.
        thread_id: Thread whose pending references should be detached.
    """
    await db.execute(
        update(SessionModel)
        .where(SessionModel.pending_thread_id == thread_id)
        .values(pending_thread_id=None)
    )


async def null_event_thread_references(db: AsyncSession, thread_ids: set[int]) -> None:
    """Null out thread references on events pointing at deleted threads.

    Args:
        db: Database session.
        thread_ids: Thread IDs whose event references should be nulled.
    """
    await db.execute(
        update(Event)
        .where(
            Event.thread_id.in_(thread_ids) | Event.selected_thread_id.in_(thread_ids)
        )
        .values(thread_id=None, selected_thread_id=None)
    )
