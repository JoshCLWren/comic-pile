"""Reading session, event, and snapshot query construction and persistence.

All SQLAlchemy access for the ``ReadingSession``/``Event``/``Snapshot`` model family
lives here. Functions return ORM models or plain values; callers (services)
own transaction boundaries.
"""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession as ReadingSessionModel, Snapshot, Thread
from app.models.thread import normalize_format_value


async def get_reading_session(db: AsyncSession, session_id: int) -> ReadingSessionModel | None:
    """Return a reading session by primary key.

    Args:
        db: Database session.
        session_id: Primary key of the reading session.

    Returns:
        The reading session, or None when it does not exist.
    """
    return await db.get(ReadingSessionModel, session_id)


async def delete_all_reading_sessions_for_user(db: AsyncSession, user_id: int) -> None:
    """Delete all reading sessions for a user.

    Args:
        db: Database session.
        user_id: Owner whose reading sessions should be removed.
    """
    await db.execute(delete(ReadingSessionModel).where(ReadingSessionModel.user_id == user_id))


async def find_owned_reading_session(
    db: AsyncSession, user_id: int, session_id: int
) -> ReadingSessionModel | None:
    """Find a reading session by ID scoped to its owner.

    Args:
        db: Database session.
        user_id: Owner that must own the reading session.
        session_id: Primary key of the reading session.

    Returns:
        The owned reading session, or None when absent or foreign.
    """
    result = await db.execute(
        select(ReadingSessionModel).where(
            ReadingSessionModel.id == session_id,
            ReadingSessionModel.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def fetch_active_reading_session(db: AsyncSession, user_id: int) -> ReadingSessionModel | None:
    """Return a user's most recently started reading session that has not ended.

    Args:
        db: Database session.
        user_id: Owner of the reading sessions.

    Returns:
        The latest un-ended reading session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSessionModel)
        .where(ReadingSessionModel.user_id == user_id)
        .where(ReadingSessionModel.ended_at.is_(None))
        .order_by(ReadingSessionModel.started_at.desc(), ReadingSessionModel.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def fetch_history_page(
    db: AsyncSession,
    user_id: int,
    *,
    cursor: tuple[datetime, int] | None,
    limit: int,
) -> list[ReadingSessionModel]:
    """Fetch one page of a user's reading session history, newest first.

    Args:
        db: Database session.
        user_id: Owner of the reading sessions.
        cursor: Decoded ``(started_at, id)`` continuation cursor, or None for
            the first page.
        limit: Maximum number of reading sessions to return.

    Returns:
        Reading sessions in canonical page order, at most ``limit`` rows.
    """
    query = select(ReadingSessionModel).where(ReadingSessionModel.user_id == user_id)
    query = query.order_by(ReadingSessionModel.started_at.desc(), ReadingSessionModel.id.desc())

    if cursor is not None:
        cursor_started_at, cursor_id = cursor
        query = query.where(
            (ReadingSessionModel.started_at < cursor_started_at)
            | ((ReadingSessionModel.started_at == cursor_started_at) & (ReadingSessionModel.id > cursor_id))
        )

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def latest_action_event(
    db: AsyncSession, session_id: int, event_types: tuple[str, ...]
) -> Event | None:
    """Return the most recent event of the given types for a reading session.

    Args:
        db: Database session.
        session_id: Reading session whose events are searched.
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
        session_id: Reading session whose events are searched.

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
    """Return every event of a reading session in chronological order.

    Args:
        db: Database session.
        session_id: Reading session whose events are fetched.

    Returns:
        Events ordered by timestamp.
    """
    result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    return list(result.scalars().all())


async def recent_reading_session_events(db: AsyncSession, session_id: int) -> list[Event]:
    """Return the most recent rate/snooze/undo/roll events for a reading session.

    Args:
        db: Database session.
        session_id: Reading session whose events are fetched.

    Returns:
        Matching events ordered newest first by ``(timestamp desc, id desc)``.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type.in_(("rate", "snooze", "undo", "roll")))
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    return list(result.scalars().all())


async def recent_snooze_events(
    db: AsyncSession, session_id: int, *, limit: int = 10
) -> list[Event]:
    """Return the most recent snooze events for a reading session.

    Args:
        db: Database session.
        session_id: Reading session whose snooze events are fetched.
        limit: Maximum number of events to return.

    Returns:
        Snooze events ordered newest first by ``(timestamp desc, id desc)``.
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "snooze")
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def die_change_events(db: AsyncSession, session_id: int) -> list[Event]:
    """Return rate/snooze/undo events that changed the die for a reading session.

    Args:
        db: Database session.
        session_id: Reading session whose events are fetched.

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


async def history_events_for_reading_sessions(
    db: AsyncSession, session_ids: list[int]
) -> list[Event]:
    """Return roll and die-change events for many reading sessions in projection order.

    Args:
        db: Database session.
        session_ids: Reading session IDs to load events for.

    Returns:
        Events ordered by ``(session_id, timestamp, id)`` suitable for the
        linear reading-session-history projection.
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
    """Count snapshots recorded for a reading session.

    Args:
        db: Database session.
        session_id: Reading session whose snapshots are counted.

    Returns:
        Number of snapshots (0 when none exist).
    """
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
    )
    return result.scalar() or 0


async def snapshot_counts_by_reading_session(
    db: AsyncSession, session_ids: list[int]
) -> dict[int, int]:
    """Count snapshots for many reading sessions in one grouped query.

    Args:
        db: Database session.
        session_ids: Reading session IDs to count snapshots for.

    Returns:
        Mapping of reading session ID to snapshot count; absent IDs have zero.
    """
    result = await db.execute(
        select(Snapshot.session_id, func.count())
        .where(Snapshot.session_id.in_(session_ids))
        .group_by(Snapshot.session_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def snapshots_desc(db: AsyncSession, session_id: int) -> list[Snapshot]:
    """List a reading session's snapshots, newest first.

    Args:
        db: Database session.
        session_id: Reading session whose snapshots are fetched.

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
    """Return the earliest "Reading session start" snapshot of a reading session.

    Args:
        db: Database session.
        session_id: Reading session whose snapshots are searched.

    Returns:
        The first reading session-start snapshot by creation time, or None.
    """
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .where(Snapshot.description == "Reading session start")
        .order_by(Snapshot.created_at)
    )
    return result.scalars().first()


async def detach_pending_thread_references(db: AsyncSession, thread_id: int) -> None:
    """Clear pending-thread pointers on reading sessions referencing a thread.

    Args:
        db: Database session.
        thread_id: Thread whose pending references should be detached.
    """
    await db.execute(
        update(ReadingSessionModel)
        .where(ReadingSessionModel.pending_thread_id == thread_id)
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


async def restore_reading_session_start(
    db: AsyncSession,
    reading_session: ReadingSessionModel,
    snapshot: Snapshot,
    user_id: int,
) -> tuple[ReadingSessionModel, list[Thread]]:
    """Restore reading session to its initial state at reading session start.

    Args:
        db: Database session.
        reading_session: The owned reading session being restored.
        snapshot: The "Reading session start" snapshot to replay.
        user_id: The reading session owner for thread scoping.

    Returns:
        Tuple of (restored reading session, affected threads).
    """
    from app.repositories.thread_repository import threads_by_ids, delete_threads_by_ids
    from app.models import Issue
    from sqlalchemy import delete

    # Get current threads for the user
    current_threads_result = await db.execute(
        select(Thread).where(Thread.user_id == user_id)
    )
    current_threads = current_threads_result.scalars().all()
    current_thread_ids = {thread.id for thread in current_threads}

    # Get thread IDs from snapshot
    snapshot_thread_ids = {int(tid) for tid in snapshot.thread_states.keys()}

    # Delete threads that don't exist in the snapshot
    threads_to_delete = current_thread_ids - snapshot_thread_ids
    if threads_to_delete:
        await null_event_thread_references(db, threads_to_delete)
        await delete_threads_by_ids(db, threads_to_delete, user_id)

    # Batch load existing threads to avoid N+1
    existing_threads_map = await threads_by_ids(db, snapshot_thread_ids)

    # Batch delete all issues for snapshot threads (recreated or cleared)
    if snapshot_thread_ids:
        await db.execute(delete(Issue).where(Issue.thread_id.in_(snapshot_thread_ids)))

    # Get threads from snapshot (both existing and new)
    affected_threads = []

    for thread_id, state in snapshot.thread_states.items():
        thread_id_int = int(thread_id)
        thread = existing_threads_map.get(thread_id_int)
        
        if thread:
            # Update existing thread
            if "title" in state:
                thread.title = state["title"]
            if "format" in state:
                thread.format = normalize_format_value(state["format"])
            thread.issues_remaining = state.get("issues_remaining", thread.issues_remaining)
            thread.last_rating = state.get("last_rating", thread.last_rating)
            thread.queue_position = state.get("queue_position", thread.queue_position)
            thread.status = state.get("status", thread.status)
            if "notes" in state:
                thread.notes = state["notes"]
            if "is_test" in state:
                thread.is_test = state["is_test"]
            if state.get("last_activity_at"):
                thread.last_activity_at = datetime.fromisoformat(state["last_activity_at"])

            # Handle issue states
            if "issue_states" in state and state["issue_states"] is not None:
                # Issues already batch-deleted above; recreate from snapshot
                max_position = 0
                for issue_state in state["issue_states"]:
                    position = issue_state.get("position", max_position + 1)
                    if position > max_position:
                        max_position = position
                    issue = Issue(
                        id=issue_state["id"],
                        thread_id=thread_id_int,
                        issue_number=issue_state["number"],
                        status=issue_state["status"],
                        read_at=datetime.fromisoformat(issue_state["read_at"])
                        if issue_state["read_at"]
                        else None,
                        created_at=datetime.now(UTC),
                        position=position,
                    )
                    db.add(issue)
                
                thread.total_issues = state.get("total_issues")
                thread.next_unread_issue_id = state.get("next_unread_issue_id")
                thread.reading_progress = state.get("reading_progress")
            else:
                # Clear migrated state when restoring to legacy (issues batch-deleted above)
                thread.total_issues = None
                thread.next_unread_issue_id = None
                thread.reading_progress = None
                thread.issues_remaining = state.get("issues_remaining", thread.issues_remaining)
        else:
            # Create new thread
            new_thread = Thread(
                id=thread_id_int,
                title=state.get("title", "Unknown Thread"),
                format=normalize_format_value(state.get("format", "comic")),
                issues_remaining=state.get("issues_remaining", 0),
                last_rating=state.get("last_rating"),
                queue_position=state.get("queue_position", 1),
                status=state.get("status", "active"),
                notes=state.get("notes"),
                is_test=state.get("is_test", False),
                user_id=state.get("user_id", user_id),
                created_at=datetime.fromisoformat(state["created_at"])
                if state.get("created_at")
                else datetime.now(UTC),
            )
            
            if state.get("last_activity_at"):
                new_thread.last_activity_at = datetime.fromisoformat(state["last_activity_at"])
            
            db.add(new_thread)

            # Handle issue states for new thread
            if "issue_states" in state and state["issue_states"] is not None:
                max_position = 0
                for issue_state in state["issue_states"]:
                    position = issue_state.get("position", max_position + 1)
                    if position > max_position:
                        max_position = position
                    issue = Issue(
                        id=issue_state["id"],
                        thread_id=thread_id_int,
                        issue_number=issue_state["number"],
                        status=issue_state["status"],
                        read_at=datetime.fromisoformat(issue_state["read_at"])
                        if issue_state["read_at"]
                        else None,
                        created_at=datetime.now(UTC),
                        position=position,
                    )
                    db.add(issue)
                
                new_thread.total_issues = state.get("total_issues")
                new_thread.next_unread_issue_id = state.get("next_unread_issue_id")
                new_thread.reading_progress = state.get("reading_progress")
            else:
                new_thread.issues_remaining = state.get("issues_remaining", 0)

        affected_threads.append(thread if thread else new_thread)

    # Restore reading session state
    if snapshot.session_state:
        reading_session.start_die = snapshot.session_state.get("start_die", reading_session.start_die)
        reading_session.manual_die = snapshot.session_state.get("manual_die", reading_session.manual_die)
        reading_session.active_bandwidth = snapshot.session_state.get(
            "active_bandwidth", reading_session.active_bandwidth
        )
        reading_session.predicted_bandwidth = snapshot.session_state.get(
            "predicted_bandwidth", reading_session.predicted_bandwidth
        )
        reading_session.bandwidth_confidence = snapshot.session_state.get(
            "bandwidth_confidence", reading_session.bandwidth_confidence
        )
        reading_session.bandwidth_source = snapshot.session_state.get(
            "bandwidth_source", reading_session.bandwidth_source
        )
        reading_session.bandwidth_version = snapshot.session_state.get(
            "bandwidth_version", reading_session.bandwidth_version
        )
        reading_session.active_intent = snapshot.session_state.get(
            "active_intent", reading_session.active_intent
        )
        reading_session.predicted_intent = snapshot.session_state.get(
            "predicted_intent", reading_session.predicted_intent
        )
        reading_session.intent_confidence = snapshot.session_state.get(
            "intent_confidence", reading_session.intent_confidence
        )
        reading_session.intent_source = snapshot.session_state.get(
            "intent_source", reading_session.intent_source
        )
        reading_session.intent_version = snapshot.session_state.get(
            "intent_version", reading_session.intent_version
        )

    return reading_session, affected_threads