"""Shared session response builders and ladder helpers.

This module consolidates cross-router shared logic that was previously
living as private functions in session.py, snooze.py, and roll.py.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, ReadingSession, Snapshot, Thread
from app.models.thread import normalize_format_value
from app.services.queue_display import display_position, display_positions
from app.repositories import reading_session_repository, thread_repository
from app.schemas import ActiveThreadInfo, SessionResponse
from app.services.tag_inheritance_service import TagInheritanceService
from app.schemas.session import (
    EventDetail,
    SnoozeCorrectionInfo,
    SnoozedThreadInfo,
    build_session_bandwidth_state,
    build_session_intent_state,
)
from comic_pile.reading_session import get_current_die

#: Reader-friendly verbs for session event types on the history timeline.
EVENT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "skip": "Skipped",
    "rolled_but_skipped": "Skipped",
    "complete": "Completed",
    "completion": "Completed",
    "reorder": "Reordered",
    "undo": "Restored",
    "restore": "Restored",
    "move": "Moved",
    "shuffle": "Shuffled",
    "roll": "Rolled",
    "rate": "Rated",
    "unsnooze": "Unsnoozed",
    "dismiss": "Dismissed",
}


def _event_word(event_type: str) -> str:
    """Return a reader-friendly verb for a session event type.

    Args:
        event_type: Raw event type identifier.

    Returns:
        Human-readable past-tense verb for timeline descriptions.
    """
    return EVENT_TYPE_DESCRIPTIONS.get(event_type, event_type.replace("_", " ").capitalize())


def _deleted_title(title: str | None) -> str:
    """Return display text for a deleted thread reference.

    Args:
        title: Last-known title recovered from snapshots, or None.

    Returns:
        The recovered title with a deletion marker, or a graceful fallback.
    """
    if title:
        return f"{title} (deleted)"
    return "deleted thread"


def _context_text(event: Event, key: str) -> str | None:
    """Return a trimmed string value from an event's JSON context.

    Args:
        event: The session event carrying the context.
        key: The context key to read.

    Returns:
        The trimmed value, or None when the key is absent or not a string.
    """
    context = event.context
    if not isinstance(context, dict):
        return None
    value = context.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _mode_label(value: str) -> str:
    """Return a display label for a stored reading-mode value.

    Args:
        value: Stored bandwidth or intent value such as ``deep``.

    Returns:
        The value with underscores spaced and its first letter capitalized.
    """
    label = value.replace("_", " ").strip()
    if not label:
        return value
    return label[:1].upper() + label[1:]


def _session_mode_description(event: Event) -> str:
    """Describe a manual session-mode change in reader language.

    ``session_mode`` events are session-level state changes with no thread
    reference. Sending them through the generic thread fallback made them read
    like a broken thread reference (#3574). The event context records which
    dimensions changed and their new values, so the timeline can say exactly
    what changed instead of showing a placeholder.

    Args:
        event: The ``session_mode`` event to describe.

    Returns:
        A plain-language summary of the changed dimensions, or a generic
        fallback for legacy events without usable context.
    """
    context = event.context
    changed_raw = context.get("changed") if isinstance(context, dict) else None
    changed = (
        {value for value in changed_raw if isinstance(value, str)}
        if isinstance(changed_raw, (list, tuple))
        else set()
    )

    parts: list[str] = []
    if "bandwidth" in changed:
        bandwidth = _context_text(event, "bandwidth")
        if bandwidth:
            parts.append(f"Bandwidth set to {_mode_label(bandwidth)}")
    if "intent" in changed:
        intent = _context_text(event, "intent")
        if intent:
            parts.append(f"Intent set to {_mode_label(intent)}")
    return " · ".join(parts) or "Session mode changed"


async def build_ladder_path(
    session_id: int,
    db: AsyncSession,
    *,
    session: ReadingSession | None = None,
    die_events: list[Event] | None = None,
) -> str:
    """Build narrative summary of dice ladder from session events.

    Args:
        session_id: The session ID to build ladder path for.
        db: Database session.
        session: Pre-loaded session object (avoids a redundant SELECT).
        die_events: Pre-fetched die-changing events (avoids a redundant SELECT).

    Returns:
        String representation of dice ladder path (e.g., "d4 → d6 → d8").
    """
    if session is None:
        session = await db.get(ReadingSession, session_id)
        if not session:
            return ""

    if die_events is None:
        events_result = await db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type.in_(("rate", "snooze", "undo")))
            .where(Event.die_after.is_not(None))
            .order_by(Event.timestamp, Event.id)
        )
        die_events = events_result.scalars().all()

    if not die_events:
        return str(session.start_die)

    path = [session.start_die]
    for event in die_events:
        if event.die_after:
            path.append(event.die_after)

    return " → ".join(str(d) for d in path)


async def _fetch_thread_issue_metadata(
    thread: Thread, db: AsyncSession
) -> tuple[int | None, str | None]:
    """Fetch issue metadata for a thread.

    Args:
        thread: The thread to fetch issue metadata for.
        db: Database session.

    Returns:
        Tuple of (issue_id, issue_number) for the thread's next unread issue,
        or (None, None) if the thread doesn't use issue tracking or has no next issue.
    """
    if not thread.uses_issue_tracking() or not thread.next_unread_issue_id:
        return None, None

    issue_result = await db.execute(select(Issue).where(Issue.id == thread.next_unread_issue_id))
    next_issue = issue_result.scalar_one_or_none()
    if next_issue:
        return next_issue.id, next_issue.issue_number
    return None, None


async def get_session_with_thread_safe(
    session_id: int, db: AsyncSession
) -> tuple[ReadingSession | None, ActiveThreadInfo | None]:
    """Get session and active thread with consistent lock ordering to prevent deadlocks.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        Tuple of (session or None, active_thread or None).
    """
    session = await db.get(ReadingSession, session_id)
    if not session:
        return None, None

    # Query the latest action event to determine if there's an active roll.
    # An active roll exists only if the most recent action was a "roll".
    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type.in_(["roll", "rate", "snooze", "rolled_but_skipped"]))
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    latest_event = event_result.scalars().first()

    event = latest_event if latest_event and latest_event.type == "roll" else None

    last_rolled_result = event.result if event else None

    # Prefer pending thread when present so UI and rate target stay consistent.
    if session.pending_thread_id is not None:
        pending_result = await db.execute(
            select(Thread)
            .where(Thread.id == session.pending_thread_id)
            .where(Thread.user_id == session.user_id)
        )
        pending_thread = pending_result.scalar_one_or_none()
        if pending_thread:
            issues_remaining = await pending_thread.get_issues_remaining(db)
            issue_id, issue_number = await _fetch_thread_issue_metadata(pending_thread, db)
            tags = await TagInheritanceService(db).get_threads_direct_tags(
                session.user_id, [pending_thread.id]
            )
            return session, ActiveThreadInfo(
                id=pending_thread.id,
                title=pending_thread.title,
                format=normalize_format_value(pending_thread.format),
                issues_remaining=issues_remaining,
                queue_position=await display_position(db, pending_thread),
                last_rolled_result=last_rolled_result,
                total_issues=pending_thread.total_issues,
                reading_progress=pending_thread.reading_progress,
                issue_id=issue_id,
                issue_number=issue_number,
                next_issue_id=issue_id,
                next_issue_number=issue_number,
                tags=tags.get(pending_thread.id, []),
            )
        return session, None

    if event and event.selected_thread_id:
        thread = await db.get(Thread, event.selected_thread_id)
        if thread and thread.user_id == session.user_id:
            issues_remaining = await thread.get_issues_remaining(db)
            issue_id, issue_number = await _fetch_thread_issue_metadata(thread, db)
            tags = await TagInheritanceService(db).get_threads_direct_tags(
                session.user_id, [thread.id]
            )
            return session, ActiveThreadInfo(
                id=thread.id,
                title=thread.title,
                format=normalize_format_value(thread.format),
                issues_remaining=issues_remaining,
                queue_position=await display_position(db, thread),
                last_rolled_result=last_rolled_result,
                total_issues=thread.total_issues,
                reading_progress=thread.reading_progress,
                issue_id=issue_id,
                issue_number=issue_number,
                next_issue_id=issue_id,
                next_issue_number=issue_number,
                tags=tags.get(thread.id, []),
            )

    return session, None


async def get_active_thread(session_id: int, db: AsyncSession) -> ActiveThreadInfo | None:
    """Get the most recently rolled thread for the session.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        ActiveThreadInfo if found, None otherwise.
    """
    session = await db.get(ReadingSession, session_id)
    user_id = session.user_id if session else None

    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    event = event_result.scalars().first()

    if not event or not event.selected_thread_id:
        return None

    thread = await db.get(Thread, event.selected_thread_id)
    if not thread or (user_id and thread.user_id != user_id):
        return None

    issues_remaining = await thread.get_issues_remaining(db)
    issue_id, issue_number = await _fetch_thread_issue_metadata(thread, db)
    tags = []
    if user_id:
        tags_map = await TagInheritanceService(db).get_threads_direct_tags(user_id, [thread.id])
        tags = tags_map.get(thread.id, [])
    return ActiveThreadInfo(
        id=thread.id,
        title=thread.title,
        format=normalize_format_value(thread.format),
        issues_remaining=issues_remaining,
        queue_position=await display_position(db, thread),
        last_rolled_result=event.result,
        total_issues=thread.total_issues,
        reading_progress=thread.reading_progress,
        issue_id=issue_id,
        issue_number=issue_number,
        next_issue_id=issue_id,
        next_issue_number=issue_number,
        tags=tags,
    )


async def get_active_thread_info(
    session_id: int, db: AsyncSession
) -> tuple[int | None, ActiveThreadInfo | None]:
    """Get the most recently rolled thread info for the session.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        Tuple of (thread_id, ActiveThreadInfo or None).
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    event = result.scalars().first()

    if not event or not event.selected_thread_id:
        return None, None

    thread = await db.get(Thread, event.selected_thread_id)
    if not thread:
        return event.selected_thread_id, None

    return event.selected_thread_id, ActiveThreadInfo(
        id=thread.id,
        title=thread.title,
        format=normalize_format_value(thread.format),
        issues_remaining=thread.issues_remaining,
        queue_position=await display_position(db, thread),
        last_rolled_result=event.result,
    )


async def load_queue_position_map(db: AsyncSession, user_id: int) -> dict[int, int]:
    """Return the reader's dense 1..N Queue ordinals in one whole-queue read.

    Session history rows resolve their active thread's displayed position from
    this single map, so a page of sessions never issues one position lookup per
    row. The lookup itself belongs to the service layer; routers only consume
    the returned mapping.

    Args:
        db: Database session.
        user_id: Authenticated owner of the queue.

    Returns:
        Mapping of active thread ID to its 1-based Queue ordinal.
    """
    return await display_positions(db, user_id)


async def build_narrative_summary(session_id: int, db: AsyncSession) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events.

    Canonical logic lives in :mod:`app.services.summary_service`; this wrapper
    is retained for backwards compatibility.

    Args:
        session_id: The session ID to build summary for.
        db: Database session.

    Returns:
        Dictionary with keys "read", "skipped", and "completed", each containing
        a list of formatted strings.
    """
    from app.services.summary_service import (
        build_narrative_summary as build_canonical_summary,
    )

    return await build_canonical_summary(session_id, db)


def _event_thread_id(event: Event) -> int | None:
    """Return the thread referenced by a session event, if any.

    Roll events record their pick in ``selected_thread_id``; every other type
    uses ``thread_id``. Undo events may carry either (undoing a roll preserves
    the roll's selected reference), so ``thread_id`` is preferred with a
    fallback to ``selected_thread_id``.

    Args:
        event: The session event to inspect.

    Returns:
        The referenced thread ID, or None when the event names no thread.
    """
    if event.type == "roll":
        return event.selected_thread_id
    if event.thread_id is not None:
        return event.thread_id
    return event.selected_thread_id


async def build_session_event_details(
    db: AsyncSession,
    session_id: int,
    events: Sequence[Event],
) -> list[EventDetail]:
    """Format session events for the history timeline.

    Live threads are loaded with the same thread-id resolution the timeline
    uses, so an event can never be flagged ``thread_deleted`` just because a
    caller forgot to prefetch its reference. Events that reference a deleted
    thread resolve their title from the session's snapshots when possible and
    are flagged with ``thread_deleted`` so the timeline can render a graceful
    placeholder instead of an error-like missing state (#3265). Session-level
    events such as ``session_mode`` never reference a thread and instead
    describe the state change directly (#3574).

    Args:
        db: Database session.
        session_id: Session whose snapshots provide last-known titles.
        events: Session events in display order.

    Returns:
        EventDetail list with titles, deletion flags, and reader-language
        descriptions.
    """
    thread_ids: set[int] = set()
    for event in events:
        thread_id = _event_thread_id(event)
        if thread_id is not None:
            thread_ids.add(thread_id)
    threads_by_id = await thread_repository.threads_by_ids(db, thread_ids)
    missing_ids = {thread_id for thread_id in thread_ids if thread_id not in threads_by_id}
    snapshot_titles: dict[int, str] = {}
    if missing_ids:
        recovered = await reading_session_repository.snapshot_thread_titles(db, session_id)
        snapshot_titles = {tid: title for tid, title in recovered.items() if tid in missing_ids}

    formatted_events: list[EventDetail] = []
    for event in events:
        thread_id = _event_thread_id(event)
        thread_title: str | None = None
        thread_deleted = False
        if thread_id is not None:
            thread = threads_by_id.get(thread_id)
            if thread is not None:
                thread_title = thread.title
            else:
                thread_deleted = True
                thread_title = snapshot_titles.get(thread_id)

        event_data = EventDetail(
            id=event.id,
            type=event.type,
            timestamp=event.timestamp,
            thread_title=thread_title,
            thread_deleted=thread_deleted,
            issue_number=event.issue_number,
        )

        if event.type == "roll":
            event_data.die = event.die
            event_data.result = event.result
            event_data.selection_method = event.selection_method
            if thread_deleted:
                event_data.description = f"Selected {_deleted_title(thread_title)}"
            else:
                event_data.description = f"Selected {thread_title or 'a thread'}"
        elif event.type == "rate":
            event_data.die = event.die
            event_data.rating = event.rating
            event_data.issues_read = event.issues_read
            event_data.queue_move = event.queue_move
            event_data.die_after = event.die_after
            parts = ["Rated"]
            if thread_title:
                parts.append(thread_title if not thread_deleted else _deleted_title(thread_title))
            elif thread_deleted:
                parts.append("deleted thread")
            if event.issues_read:
                noun = "issue" if event.issues_read == 1 else "issues"
                parts.append(f"{event.issues_read} {noun} read")
            if event.rating is not None:
                parts.append(f"{event.rating:.1f}/5")
            event_data.description = " · ".join(parts)
        elif event.type == "snooze":
            event_data.die = event.die
            event_data.die_after = event.die_after
            if thread_deleted:
                event_data.description = f"Snoozed {_deleted_title(thread_title)}"
            else:
                event_data.description = f"Snoozed {thread_title or 'thread'}"
        elif event.type == "unsnooze":
            event_data.die = event.die
            event_data.die_after = event.die_after
            if thread_deleted:
                event_data.description = f"Unsnoozed {_deleted_title(thread_title)}"
            else:
                event_data.description = f"Unsnoozed {thread_title or 'thread'}"
        elif event.type == "dismiss":
            word = _event_word(event.type)
            if thread_deleted:
                event_data.description = f"{word} {_deleted_title(thread_title)}"
            else:
                event_data.description = f"{word} {thread_title or 'thread'}"
        elif event.type == "skip" or event.type == "rolled_but_skipped":
            event_data.die = event.die
            event_data.die_after = event.die_after
            word = _event_word(event.type)
            if thread_deleted:
                event_data.description = f"{word} {_deleted_title(thread_title)}"
            else:
                event_data.description = f"{word} {thread_title or 'thread'}"
        elif event.type == "move":
            event_data.die = event.die
            event_data.die_after = event.die_after
            if thread_deleted:
                event_data.description = f"Moved {_deleted_title(thread_title)}"
            else:
                event_data.description = f"Moved {thread_title or 'thread'}"
        elif event.type == "shuffle":
            event_data.die = event.die
            event_data.die_after = event.die_after
            if thread_deleted:
                event_data.description = f"Shuffled {_deleted_title(thread_title)}"
            else:
                event_data.description = f"Shuffled {thread_title or 'thread'}"
        elif event.type == "session_mode":
            event_data.description = _session_mode_description(event)
        elif event.type in ("reorder", "undo", "restore"):
            event_data.rating = event.rating
            word = _event_word(event.type)
            if thread_deleted:
                desc_parts = [f"{word} {_deleted_title(thread_title)}"]
            else:
                desc_parts = [f"{word} {thread_title or 'thread'}"]
            if event.rating is not None:
                desc_parts.append(f"rating {event.rating:.1f}")
            if event.issue_number:
                desc_parts.append(f"#{event.issue_number}")
            event_data.description = " · ".join(desc_parts)

        formatted_events.append(event_data)
    return formatted_events


async def build_session_response(
    session: ReadingSession,
    db: AsyncSession,
    *,
    current_die: int | None = None,
    active_thread_id: int | None = None,
    active_thread_info: ActiveThreadInfo | None = None,
    ladder_path: str | None = None,
    snapshot_count: int | None = None,
    snoozed_threads: list[SnoozedThreadInfo] | None = None,
    snoozed_thread_ids: list[int] | None = None,
    skipped_threads: list[SnoozedThreadInfo] | None = None,
    skipped_thread_ids: list[int] | None = None,
    correction: SnoozeCorrectionInfo | None = None,
) -> SessionResponse:
    """Build a SessionResponse from a session model.

    When pre-loaded values are provided, avoids redundant database queries.
    Callers that already computed die, active thread, or ladder path should
    pass them in to reduce round trips.

    Args:
        session: The session model.
        db: Database session.
        current_die: Pre-computed current die value (skips get_current_die query).
        active_thread_id: Pre-fetched active thread ID (skips event lookup).
        active_thread_info: Pre-fetched active thread info (skips thread lookup).
        ladder_path: Pre-computed ladder path string (skips event re-read).
        snapshot_count: Pre-computed snapshot count (skips COUNT query).
        snoozed_threads: Pre-fetched snoozed thread info (skips snoozed thread query).
        snoozed_thread_ids: Pre-fetched snoozed thread IDs (avoids expired session read).
        skipped_threads: Pre-fetched skipped thread info (skips skipped thread query).
        skipped_thread_ids: Pre-fetched skipped thread IDs (avoids expired session read).
        correction: Structured correction result from the most recent Snooze.

    Returns:
        A SessionResponse with all required fields populated.
    """
    if active_thread_id is not None and active_thread_info is None:
        thread = await db.get(Thread, active_thread_id)
        if thread:
            active_thread_info = ActiveThreadInfo(
                id=thread.id,
                title=thread.title,
                format=normalize_format_value(thread.format),
                issues_remaining=thread.issues_remaining,
                queue_position=await display_position(db, thread),
                last_rolled_result=None,
            )

    if snapshot_count is None:
        result = await db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
        )
        snapshot_count = result.scalar() or 0

    if snoozed_threads is not None and snoozed_thread_ids is not None:
        resolved_ids = snoozed_thread_ids
    else:
        snoozed_ids = session.snoozed_thread_ids or []
        resolved_ids = [sid for sid in snoozed_ids if isinstance(sid, int)]
        snoozed_threads = []
        if resolved_ids:
            result = await db.execute(select(Thread).where(Thread.id.in_(resolved_ids)))
            threads_by_id = {thread.id: thread for thread in result.scalars().all()}
            snoozed_threads = [
                SnoozedThreadInfo(id=thread_id, title=threads_by_id[thread_id].title)
                for thread_id in resolved_ids
                if thread_id in threads_by_id
            ]

    if skipped_threads is not None and skipped_thread_ids is not None:
        resolved_skipped_ids = skipped_thread_ids
        resolved_skipped_threads = skipped_threads
    else:
        skipped_ids_list = session.skipped_thread_ids or []
        resolved_skipped_ids = [sid for sid in skipped_ids_list if isinstance(sid, int)]
        resolved_skipped_threads = []
        if resolved_skipped_ids:
            result = await db.execute(select(Thread).where(Thread.id.in_(resolved_skipped_ids)))
            threads_by_id = {thread.id: thread for thread in result.scalars().all()}
            resolved_skipped_threads = [
                SnoozedThreadInfo(id=thread_id, title=threads_by_id[thread_id].title)
                for thread_id in resolved_skipped_ids
                if thread_id in threads_by_id
            ]

    if current_die is None:
        current_die = await get_current_die(session.id, db)
    if ladder_path is None:
        ladder_path = await build_ladder_path(session.id, db, session=session)

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=ladder_path,
        active_thread=active_thread_info,
        current_die=current_die,
        last_rolled_result=active_thread_info.last_rolled_result if active_thread_info else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
        snoozed_thread_ids=resolved_ids,
        snoozed_threads=snoozed_threads,
        skipped_thread_ids=resolved_skipped_ids,
        skipped_threads=resolved_skipped_threads,
        pending_thread_id=session.pending_thread_id,
        timezone=session.timezone,
        reading_bandwidth=session.reading_bandwidth,
        reading_intent=session.reading_intent,
        reading_mode_source=session.reading_mode_source,
        reading_mode_suggested=session.reading_mode_suggested,
        bandwidth=build_session_bandwidth_state(
            predicted_bandwidth=session.predicted_bandwidth,
            active_bandwidth=session.active_bandwidth,
            confidence=session.bandwidth_confidence,
            source=session.bandwidth_source,
            mode_version=session.bandwidth_version,
        ),
        intent=build_session_intent_state(
            predicted_intent=session.predicted_intent,
            active_intent=session.active_intent,
            confidence=session.intent_confidence,
            source=session.intent_source,
            mode_version=session.intent_version,
        ),
        correction=correction,
    )
