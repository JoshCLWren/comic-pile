"""ReadingSession, Event, and Snapshot query construction and persistence.

All SQLAlchemy access for the ``ReadingSession``/``Event``/``Snapshot`` model
family lives here. Every helper is reading-history scoped: nothing in this
module revokes credentials or touches authentication state. Functions return
ORM models or plain values; callers (services) own transaction boundaries.

Naming note: the module and its mutating helpers carry a ``reading_session``
qualifier so an auth change cannot mistake them for login-session revocation.
See ``docs/READING_SESSION_NAMING.md``.
"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Snapshot


async def get_reading_session(db: AsyncSession, reading_session_id: int) -> ReadingSession | None:
    """Return a session by primary key.

    Args:
        db: Database session.
        reading_session_id: Primary key of the reading session.

    Returns:
        The session, or None when it does not exist.
    """
    return await db.get(ReadingSession, reading_session_id)


async def find_owned_reading_session(
    db: AsyncSession, user_id: int, reading_session_id: int
) -> ReadingSession | None:
    """Find a session by ID scoped to its owner.

    Args:
        db: Database session.
        user_id: Owner that must own the session.
        reading_session_id: Primary key of the session.

    Returns:
        The owned session, or None when absent or foreign.
    """
    result = await db.execute(
        select(ReadingSession).where(
            ReadingSession.id == reading_session_id,
            ReadingSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def fetch_active_reading_session(db: AsyncSession, user_id: int) -> ReadingSession | None:
    """Return a user's most recently started session that has not ended.

    Args:
        db: Database session.
        user_id: Owner of the sessions.

    Returns:
        The latest un-ended session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc(), ReadingSession.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def fetch_reading_history_page(
    db: AsyncSession,
    user_id: int,
    *,
    cursor: tuple[datetime, int] | None,
    limit: int,
) -> list[ReadingSession]:
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
    query = select(ReadingSession).where(ReadingSession.user_id == user_id)
    query = query.order_by(ReadingSession.started_at.desc(), ReadingSession.id.desc())

    if cursor is not None:
        cursor_started_at, cursor_id = cursor
        query = query.where(
            (ReadingSession.started_at < cursor_started_at)
            | ((ReadingSession.started_at == cursor_started_at) & (ReadingSession.id > cursor_id))
        )

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def latest_action_event(
    db: AsyncSession, reading_session_id: int, event_types: tuple[str, ...]
) -> Event | None:
    """Return the most recent event of the given types for a session.

    Args:
        db: Database session.
        reading_session_id: Session whose events are searched.
        event_types: Event types to consider.

    Returns:
        The newest matching event ordered by ``(timestamp desc, id desc)``, or
        None when no such event exists.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == reading_session_id)
        .where(Event.type.in_(event_types))
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    return result.scalars().first()


async def latest_roll_event(db: AsyncSession, reading_session_id: int) -> Event | None:
    """Return the most recent roll event that selected a thread.

    Args:
        db: Database session.
        reading_session_id: Session whose events are searched.

    Returns:
        The newest roll event with a selected thread, or None.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == reading_session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    return result.scalars().first()


async def events_chronological(db: AsyncSession, reading_session_id: int) -> list[Event]:
    """Return every event of a session in chronological order.

    Args:
        db: Database session.
        reading_session_id: Session whose events are fetched.

    Returns:
        Events ordered by timestamp.
    """
    result = await db.execute(
        select(Event).where(Event.session_id == reading_session_id).order_by(Event.timestamp)
    )
    return list(result.scalars().all())


async def recent_reading_session_events(db: AsyncSession, reading_session_id: int) -> list[Event]:
    """Return the most recent rate/snooze/undo/roll events for a session.

    Args:
        db: Database session.
        reading_session_id: Session whose events are fetched.

    Returns:
        Matching events ordered newest first by ``(timestamp desc, id desc)``.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == reading_session_id)
        .where(Event.type.in_(("rate", "snooze", "undo", "roll")))
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    return list(result.scalars().all())


async def recent_snooze_events(
    db: AsyncSession, reading_session_id: int, *, limit: int = 10
) -> list[Event]:
    """Return the most recent snooze events for a session.

    Args:
        db: Database session.
        reading_session_id: Session whose snooze events are fetched.
        limit: Maximum number of events to return.

    Returns:
        Snooze events ordered newest first by ``(timestamp desc, id desc)``.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == reading_session_id)
        .where(Event.type == "snooze")
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def die_change_events(db: AsyncSession, reading_session_id: int) -> list[Event]:
    """Return rate/snooze/undo events that changed the die for a session.

    Args:
        db: Database session.
        reading_session_id: Session whose events are fetched.

    Returns:
        Die-changing events in chronological order with a known ``die_after``.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == reading_session_id)
        .where(Event.type.in_(("rate", "snooze", "undo")))
        .where(Event.die_after.is_not(None))
        .order_by(Event.timestamp, Event.id)
    )
    return list(result.scalars().all())


async def history_events_for_reading_sessions(
    db: AsyncSession, reading_session_ids: list[int]
) -> list[Event]:
    """Return roll and die-change events for many sessions in projection order.

    Args:
        db: Database session.
        reading_session_ids: Session IDs to load events for.

    Returns:
        Events ordered by ``(session_id, timestamp, id)`` suitable for the
        linear session-history projection.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id.in_(reading_session_ids))
        .where(
            (Event.type == "roll") & (Event.selected_thread_id.is_not(None))
            | (Event.type.in_(("rate", "snooze", "undo"))) & (Event.die_after.is_not(None))
        )
        .order_by(Event.session_id, Event.timestamp, Event.id)
    )
    return list(result.scalars().all())


async def count_snapshots(db: AsyncSession, reading_session_id: int) -> int:
    """Count snapshots recorded for a session.

    Args:
        db: Database session.
        reading_session_id: Session whose snapshots are counted.

    Returns:
        Number of snapshots (0 when none exist).
    """
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == reading_session_id)
    )
    return result.scalar() or 0


async def snapshot_counts_by_reading_session(
    db: AsyncSession, reading_session_ids: list[int]
) -> dict[int, int]:
    """Count snapshots for many sessions in one grouped query.

    Args:
        db: Database session.
        reading_session_ids: Session IDs to count snapshots for.

    Returns:
        Mapping of session ID to snapshot count; absent IDs have zero.
    """
    result = await db.execute(
        select(Snapshot.session_id, func.count())
        .where(Snapshot.session_id.in_(reading_session_ids))
        .group_by(Snapshot.session_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def snapshots_desc(db: AsyncSession, reading_session_id: int) -> list[Snapshot]:
    """List a session's snapshots, newest first.

    Args:
        db: Database session.
        reading_session_id: Session whose snapshots are fetched.

    Returns:
        Snapshots ordered by creation date descending (ID descending as
        tie-breaker).
    """
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == reading_session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    return list(result.scalars().all())


async def first_start_snapshot(db: AsyncSession, reading_session_id: int) -> Snapshot | None:
    """Return the earliest "Session start" snapshot of a session.

    Args:
        db: Database session.
        reading_session_id: Session whose snapshots are searched.

    Returns:
        The first session-start snapshot by creation time, or None.
    """
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == reading_session_id)
        .where(Snapshot.description == "Session start")
        .order_by(Snapshot.created_at)
    )
    return result.scalars().first()


async def detach_pending_thread_references_from_reading_sessions(
    db: AsyncSession, thread_id: int
) -> None:
    """Clear pending-thread pointers on sessions referencing a thread.

    Args:
        db: Database session.
        thread_id: Thread whose pending references should be detached.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.pending_thread_id == thread_id)
        .values(pending_thread_id=None)
    )


async def snapshot_thread_titles(db: AsyncSession, reading_session_id: int) -> dict[int, str]:
    """Recover last-known thread titles from a session's snapshots.

    Snapshots persist each thread's title at capture time, so a thread that
    was later deleted can still be named on the history timeline. Snapshots
    are scanned newest first, so the first title recorded for a thread is the
    most recent one available. Delta snapshots only cover rated threads, so
    recovery is best-effort: threads with no snapshot coverage are simply
    absent from the mapping.

    Args:
        db: Database session.
        reading_session_id: Session whose snapshots should be searched.

    Returns:
        Mapping of thread ID to its last-known title.
    """
    result = await db.execute(
        select(Snapshot.thread_states)
        .where(Snapshot.session_id == reading_session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    titles: dict[int, str] = {}
    for (states,) in result.all():
        if not isinstance(states, dict):
            continue
        for key, state in states.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            try:
                thread_id = int(key)
            except (TypeError, ValueError):
                continue
            if thread_id in titles:
                continue
            if isinstance(state, dict):
                title = state.get("title")
                if isinstance(title, str) and title.strip():
                    titles[thread_id] = title
    return titles

