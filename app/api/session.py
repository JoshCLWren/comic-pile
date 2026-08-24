"""Session API endpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache import TTL, cached
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Issue, Session as SessionModel, Snapshot, Thread, User
from app.schemas import (
    ActiveThreadInfo,
    EventDetail,
    SessionDetailsResponse,
    SessionHistoryListResponse,
    SessionListItem,
    SessionResponse,
    SnapshotResponse,
    SnapshotsListResponse,
    ModeChangeRequest,
    ModeChangeResponse,
    ModeChangeHistoryEvent,
)
from app.schemas.session import SnoozedThreadInfo
from app.services.ownership import get_owned_session_or_404
from app.services.session_history_projection import project_session_history_events
from app.services.thread_issue_stats import load_next_issue_numbers, load_unread_counts
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.session import get_current_die, get_or_create, is_active
from app.constants import EventType, ModeIntent, ModeSource

router = APIRouter(tags=["sessions"])


EVENT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "skip": "Skipped",
    "complete": "Completed",
    "completion": "Completed",
    "reorder": "Reordered",
    "undo": "Restored",
    "restore": "Restored",
}


def _event_word(event_type: str) -> str:
    """Return a reader-friendly verb for a session event type.

    Args:
        event_type: Raw event type identifier.

    Returns:
        Human-readable past-tense verb for timeline descriptions.
    """
    return EVENT_TYPE_DESCRIPTIONS.get(event_type, event_type.replace("_", " ").capitalize())


def _to_session_list_item(sr: SessionResponse) -> SessionListItem:
    """Convert a full SessionResponse to a narrow SessionListItem.

    Deliberately drops snoozed_thread_ids, snoozed_threads, and pending_thread_id
    to reduce payload size for session history list views.
    """
    return SessionListItem(
        id=sr.id,
        started_at=sr.started_at,
        ended_at=sr.ended_at,
        start_die=sr.start_die,
        manual_die=sr.manual_die,
        user_id=sr.user_id,
        ladder_path=sr.ladder_path,
        active_thread=sr.active_thread,
        current_die=sr.current_die,
        last_rolled_result=sr.last_rolled_result,
        has_restore_point=sr.has_restore_point,
        snapshot_count=sr.snapshot_count,
    )


async def _invalidate_session_caches(user_id: int) -> None:
    """Invalidate session-derived views with one bounded user generation bump."""
    await invalidate_user_view(user_id)


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
) -> tuple[SessionModel | None, ActiveThreadInfo | None]:
    """Get session and active thread with consistent lock ordering to prevent deadlocks.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        Tuple of (session or None, active_thread or None).
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        return None, None

    # Query the latest action event to determine if there's an active roll.
    # An active roll exists only if the most recent action was a "roll".
    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type.in_(["roll", "rate", "snooze", "rolled_but_skipped"]))
        .order_by(Event.timestamp.desc(), Event.id.desc())
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
            return session, ActiveThreadInfo(
                id=pending_thread.id,
                title=pending_thread.title,
                format=pending_thread.format,
                issues_remaining=issues_remaining,
                queue_position=pending_thread.queue_position,
                last_rolled_result=last_rolled_result,
                total_issues=pending_thread.total_issues,
                reading_progress=pending_thread.reading_progress,
                issue_id=issue_id,
                issue_number=issue_number,
                next_issue_id=issue_id,
                next_issue_number=issue_number,
            )
        return session, None

    if event and event.selected_thread_id:
        thread = await db.get(Thread, event.selected_thread_id)
        if thread and thread.user_id == session.user_id:
            issues_remaining = await thread.get_issues_remaining(db)
            issue_id, issue_number = await _fetch_thread_issue_metadata(thread, db)
            return session, ActiveThreadInfo(
                id=thread.id,
                title=thread.title,
                format=thread.format,
                issues_remaining=issues_remaining,
                queue_position=thread.queue_position,
                last_rolled_result=last_rolled_result,
                total_issues=thread.total_issues,
                reading_progress=thread.reading_progress,
                issue_id=issue_id,
                issue_number=issue_number,
                next_issue_id=issue_id,
                next_issue_number=issue_number,
            )

    # When a thread is just completed by rating and no pending thread is set,
    # keep that completed thread visible to the UI for follow-up actions.
    # NOTE: This behavior was removed as part of issue #297 to fix UX issue
    # where completed threads remained in the active slot without clear signal
    # that the thread was done. Now completed threads are removed from the
    # active slot and the user must roll for a new thread.
    # if latest_event and latest_event.type == "rate" and latest_event.thread_id:
    #     rated_thread = await db.get(Thread, latest_event.thread_id)
    #     if (
    #         rated_thread
    #         and rated_thread.user_id == session.user_id
    #         and rated_thread.status == "completed"
    #     ):
    #         issues_remaining = await rated_thread.get_issues_remaining(db)
    #         issue_id, issue_number = await _fetch_thread_issue_metadata(rated_thread, db)
    #         return session, ActiveThreadInfo(
    #             id=rated_thread.id,
    #             title=rated_thread.title,
    #             format=rated_thread.format,
    #             issues_remaining=issues_remaining,
    #             queue_position=rated_thread.queue_position,
    #             last_rolled_result=last_rolled_result,
    #             total_issues=rated_thread.total_issues,
    #             reading_progress=rated_thread.reading_progress,
    #             issue_id=issue_id,
    #             issue_number=issue_number,
    #             next_issue_id=issue_id,
    #             next_issue_number=issue_number,
    #         )

    return session, None


async def build_narrative_summary(session_id: int, db: AsyncSession) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events.

    Args:
        session_id: The session ID to build summary for.
        db: Database session.

    Returns:
        Dictionary with keys "read", "skipped", and "completed", each containing
        a list of formatted strings.
    """
    events_result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    events = events_result.scalars().all()

    summary = {
        "read": [],
        "skipped": [],
        "completed": [],
    }

    read_entries = []
    skipped_titles = set()
    completed_titles = set()

    thread_ids = {event.thread_id for event in events if event.thread_id}
    threads_result = await db.execute(
        select(Thread).where(Thread.id.in_(thread_ids))
        if thread_ids
        else select(Thread).where(Thread.id == -1)
    )
    threads_dict = {thread.id: thread for thread in threads_result.scalars().all()}

    for event in events:
        thread = threads_dict.get(event.thread_id) if event.thread_id else None
        title = thread.title if thread else f"Thread #{event.thread_id}"

        if event.type == "rate":
            read_entries.append(f"{title} ({event.rating}/5.0)")
            if thread and thread.status == "completed":
                completed_titles.add(title)
        elif event.type == "rolled_but_skipped":
            skipped_titles.add(title)

    summary["read"] = read_entries
    summary["skipped"] = sorted(skipped_titles)
    summary["completed"] = sorted(completed_titles)

    return summary


async def build_ladder_path(
    session_id: int,
    db: AsyncSession,
    *,
    session: SessionModel | None = None,
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
        session = await db.get(SessionModel, session_id)
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


async def get_active_thread(session_id: int, db: AsyncSession) -> ActiveThreadInfo | None:
    """Get the most recently rolled thread for the session.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        ActiveThreadInfo if found, None otherwise.
    """
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
    if not thread:
        return None

    issues_remaining = await thread.get_issues_remaining(db)
    issue_id, issue_number = await _fetch_thread_issue_metadata(thread, db)
    return ActiveThreadInfo(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=issues_remaining,
        queue_position=thread.queue_position,
        last_rolled_result=event.result,
        total_issues=thread.total_issues,
        reading_progress=thread.reading_progress,
        issue_id=issue_id,
        issue_number=issue_number,
        next_issue_id=issue_id,
        next_issue_number=issue_number,
    )


@router.get("/current/")
@cached(ttl=TTL.SHORT)
@limiter.limit("200/minute")
async def get_current_session(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Get current active session with deadlock retry handling.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse with current session details.

    Raises:
        RuntimeError: If failed after max retries.
    """
    from sqlalchemy.exc import OperationalError

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            active_session_result = await db.execute(
                select(SessionModel)
                .where(SessionModel.user_id == current_user.id)
                .where(SessionModel.ended_at.is_(None))
                .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
                .limit(1)
            )
            active_session = active_session_result.scalars().first()

            if active_session is None or not await is_active(
                active_session.started_at, active_session.ended_at, db
            ):
                active_session = await get_or_create(db, user_id=current_user.id)

            await db.refresh(active_session)
            active_session_id = active_session.id
            _, active_thread = await get_session_with_thread_safe(active_session_id, db)

            from sqlalchemy import func

            snapshot_count_result = await db.execute(
                select(func.count())
                .select_from(Snapshot)
                .where(Snapshot.session_id == active_session_id)
            )
            snapshot_count = snapshot_count_result.scalar() or 0

            snoozed_threads = []
            snoozed_ids = active_session.snoozed_thread_ids or []
            if snoozed_ids:
                snoozed_result = await db.execute(select(Thread).where(Thread.id.in_(snoozed_ids)))
                snoozed_threads = [
                    SnoozedThreadInfo(id=thread.id, title=thread.title)
                    for thread in snoozed_result.scalars().all()
                ]

            return SessionResponse(
                id=active_session_id,
                started_at=active_session.started_at,
                ended_at=active_session.ended_at,
                start_die=active_session.start_die,
                manual_die=active_session.manual_die,
                user_id=active_session.user_id,
                ladder_path=await build_ladder_path(active_session_id, db),
                active_thread=active_thread,
                current_die=await get_current_die(active_session_id, db),
                last_rolled_result=active_thread.last_rolled_result if active_thread else None,
                has_restore_point=snapshot_count > 0,
                snapshot_count=snapshot_count,
                snoozed_thread_ids=active_session.snoozed_thread_ids or [],
                snoozed_threads=snoozed_threads,
                pending_thread_id=active_session.pending_thread_id,
            )
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                await db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise
                delay = initial_delay * (2 ** (retries - 1))
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to get current session after {max_retries} retries")


@router.get("/", response_model=SessionHistoryListResponse)
@cached(ttl=TTL.SHORT)
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    page_size: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Number of sessions to return per page (default 50, max 200)",
    ),
    page_token: str | None = Query(
        default=None, description="Token for pagination continuation (started_at,session_id)"
    ),
    db: AsyncSession = Depends(get_db),
) -> SessionHistoryListResponse:
    """List sessions with cursor-based pagination.

    Args:
        current_user: The authenticated user making the request.
        page_size: Number of sessions to return per page (default 50, max 200).
        page_token: Token for pagination continuation (started_at timestamp, session_id).
        db: SQLAlchemy session for database operations.

    Returns:
        SessionHistoryListResponse with paginated sessions and next_page_token if more exist.
    """
    from fastapi import HTTPException, status
    from sqlalchemy import or_

    query = select(SessionModel).where(SessionModel.user_id == current_user.id)
    query = query.order_by(SessionModel.started_at.desc(), SessionModel.id.desc())

    if page_token:
        try:
            parts = page_token.split(",")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            cursor_started_at = datetime.fromisoformat(parts[0])
            cursor_id = int(parts[1])
            query = query.where(
                or_(
                    SessionModel.started_at < cursor_started_at,
                    (SessionModel.started_at == cursor_started_at) & (SessionModel.id > cursor_id),
                )
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid page_token format",
            ) from None

    query = query.limit(page_size + 1)
    sessions_result = await db.execute(query)
    sessions = sessions_result.scalars().all()

    has_more = len(sessions) > page_size
    sessions_to_return = sessions[:page_size]

    if not sessions_to_return:
        return SessionHistoryListResponse(sessions=[], next_page_token=None)

    session_ids = [s.id for s in sessions_to_return]

    history_events_result = await db.execute(
        select(Event)
        .where(Event.session_id.in_(session_ids))
        .where(
            or_(
                (Event.type == "roll") & (Event.selected_thread_id.is_not(None)),
                Event.type == "rate",
                (Event.type.in_(("snooze", "undo"))) & (Event.die_after.is_not(None)),
            )
        )
        .order_by(Event.session_id, Event.timestamp, Event.id)
    )
    history_events = history_events_result.scalars().all()

    rate_agg: dict[int, dict] = {}
    for ev in history_events:
        if ev.type != "rate":
            continue
        if ev.session_id not in rate_agg:
            rate_agg[ev.session_id] = {"issues_read": 0, "last_rating": None}
        if ev.issues_read is not None:
            rate_agg[ev.session_id]["issues_read"] += ev.issues_read
        if ev.rating is not None:
            rate_agg[ev.session_id]["last_rating"] = ev.rating

    projection = project_session_history_events(session_ids, history_events)

    snapshot_count_result = await db.execute(
        select(Snapshot.session_id, func.count())
        .where(Snapshot.session_id.in_(session_ids))
        .group_by(Snapshot.session_id)
    )
    snapshot_counts = {row[0]: row[1] for row in snapshot_count_result.all()}

    sessions_by_id = {s.id: s for s in sessions_to_return}

    ladder_paths: dict[int, str] = {}
    for sid in session_ids:
        session = sessions_by_id[sid]
        die_path = projection.die_path_by_session[sid]
        path = [session.start_die, *die_path]
        ladder_paths[sid] = " → ".join(str(d) for d in path)

    current_die: dict[int, int] = {}
    for sid in session_ids:
        session = sessions_by_id[sid]
        if session.manual_die:
            current_die[sid] = session.manual_die
            continue
        current_die[sid] = projection.latest_die_by_session.get(sid, session.start_die)

    thread_ids = {
        event.selected_thread_id
        for event in projection.latest_roll_by_session.values()
        if event.selected_thread_id is not None
    }

    active_threads_dict: dict[int, ActiveThreadInfo | None] = {}
    if thread_ids:
        threads_result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
        threads_by_id = {t.id: t for t in threads_result.scalars().all()}
        threads = list(threads_by_id.values())
        unread_counts = await load_unread_counts(threads, db)
        issue_numbers = await load_next_issue_numbers(threads, db)

        for sid in session_ids:
            roll_event = projection.latest_roll_by_session.get(sid)
            if roll_event is not None and roll_event.selected_thread_id is not None:
                thread = threads_by_id.get(roll_event.selected_thread_id)
                if thread:
                    if thread.uses_issue_tracking():
                        issues_remaining = unread_counts.get(thread.id, 0)
                    else:
                        issues_remaining = thread.issues_remaining
                    issue_id: int | None = None
                    issue_number: str | None = None
                    if thread.uses_issue_tracking() and thread.next_unread_issue_id is not None:
                        resolved_number = issue_numbers.get(thread.next_unread_issue_id)
                        if resolved_number is not None:
                            issue_id = thread.next_unread_issue_id
                            issue_number = resolved_number
                    agg = rate_agg.get(sid, {})
                    issues_read = agg.get("issues_read") or None
                    last_rating = agg.get("last_rating")
                    raw_result = roll_event.result
                    safe_result = raw_result if raw_result and raw_result > 0 else None
                    active_threads_dict[sid] = ActiveThreadInfo(
                        id=thread.id,
                        title=thread.title,
                        format=thread.format,
                        issues_remaining=issues_remaining,
                        queue_position=thread.queue_position,
                        last_rolled_result=safe_result,
                        total_issues=thread.total_issues,
                        reading_progress=thread.reading_progress,
                        issues_read=issues_read,
                        last_rating=last_rating,
                        issue_id=issue_id,
                        issue_number=issue_number,
                        next_issue_id=issue_id,
                        next_issue_number=issue_number,
                    )
                else:
                    active_threads_dict[sid] = None
            else:
                active_threads_dict[sid] = None

    responses: list[SessionListItem] = []
    for session in sessions_to_return:
        active_thread = active_threads_dict.get(session.id)
        snapshot_count_num = snapshot_counts.get(session.id, 0)

        sr = SessionResponse(
            id=session.id,
            started_at=session.started_at,
            ended_at=session.ended_at,
            start_die=session.start_die,
            manual_die=session.manual_die,
            user_id=session.user_id,
            ladder_path=ladder_paths[session.id],
            active_thread=active_thread,
            current_die=current_die[session.id],
            last_rolled_result=active_thread.last_rolled_result if active_thread else None,
            has_restore_point=snapshot_count_num > 0,
            snapshot_count=snapshot_count_num,
            pending_thread_id=session.pending_thread_id,
        )
        responses.append(_to_session_list_item(sr))

    next_page_token = None
    if has_more and sessions_to_return:
        last = sessions_to_return[-1]
        next_page_token = f"{last.started_at.isoformat()},{last.id}"

    return SessionHistoryListResponse(sessions=responses, next_page_token=next_page_token)


@router.get("/{session_id}")
@cached(ttl=TTL.SHORT)
async def get_session(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Get single session by ID.

    Args:
        session_id: The session ID to retrieve.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse with session details.

    Raises:
        HTTPException: If session not found.
    """
    session = await get_owned_session_or_404(db, current_user.id, session_id)

    _, active_thread = await get_session_with_thread_safe(session_id, db)

    from sqlalchemy import func

    snapshot_count_result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
    )
    snapshot_count = snapshot_count_result.scalar() or 0

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=await build_ladder_path(session.id, db),
        active_thread=active_thread,
        current_die=await get_current_die(session.id, db),
        last_rolled_result=active_thread.last_rolled_result if active_thread else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
        pending_thread_id=session.pending_thread_id,
    )


@router.get("/{session_id}/details")
@cached(ttl=TTL.SHORT)
async def get_session_details(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionDetailsResponse:
    """Get session details with all events for expanded view.

    Args:
        session_id: The session ID to retrieve details for.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionDetailsResponse with events and narrative summary.

    Raises:
        HTTPException: If session not found.
    """
    session_obj = await get_owned_session_or_404(db, current_user.id, session_id)

    events_result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    events = events_result.scalars().all()

    thread_ids = set()
    for event in events:
        if event.type == "roll":
            thread_id = event.selected_thread_id
        else:
            thread_id = event.thread_id
        if thread_id:
            thread_ids.add(thread_id)

    threads_dict = {}
    if thread_ids:
        threads_result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
        threads_dict = {thread.id: thread for thread in threads_result.scalars().all()}

    formatted_events = []
    for event in events:
        thread_title = None
        if event.type == "roll":
            thread_id = event.selected_thread_id
        else:
            thread_id = event.thread_id

        if thread_id:
            thread = threads_dict.get(thread_id)
            if thread:
                thread_title = thread.title

        event_data = EventDetail(
            id=event.id,
            type=event.type,
            timestamp=event.timestamp,
            thread_title=thread_title,
        )

        if event.type == "roll":
            event_data.die = event.die
            event_data.result = event.result
            event_data.selection_method = event.selection_method
            event_data.description = f"Selected {thread_title or 'a thread'}"
        elif event.type == "rate":
            event_data.rating = event.rating
            event_data.issues_read = event.issues_read
            event_data.queue_move = event.queue_move
            event_data.die_after = event.die_after
            parts = ["Rated"]
            if thread_title:
                parts.append(thread_title)
            if event.issues_read:
                noun = "issue" if event.issues_read == 1 else "issues"
                parts.append(f"{event.issues_read} {noun} read")
            if event.rating is not None:
                parts.append(f"{event.rating:.1f}/5")
            event_data.description = " · ".join(parts)
        elif event.type == "snooze":
            event_data.die = event.die
            event_data.die_after = event.die_after
            event_data.description = f"Snoozed {thread_title or 'thread'}"
        elif event.type == "unsnooze":
            event_data.die = event.die
            event_data.die_after = event.die_after
            event_data.description = f"Unsnoozed {thread_title or 'thread'}"
        elif event.type in ("skip", "complete", "completion"):
            event_data.die = event.die
            event_data.die_after = event.die_after
            word = _event_word(event.type)
            event_data.description = f"{word} {thread_title or 'thread'}"
        elif event.type == "move":
            event_data.die = event.die
            event_data.die_after = event.die_after
            event_data.description = f"Moved {thread_title or 'thread'}"
        elif event.type == "shuffle":
            event_data.die = event.die
            event_data.die_after = event.die_after
            event_data.description = f"Shuffled {thread_title or 'thread'}"
        elif event.type in ("reorder", "undo", "restore"):
            word = _event_word(event.type)
            event_data.description = f"{word} {thread_title or 'thread'}"

        formatted_events.append(event_data)

    return SessionDetailsResponse(
        session_id=session_obj.id,
        started_at=session_obj.started_at,
        ended_at=session_obj.ended_at,
        start_die=session_obj.start_die,
        ladder_path=await build_ladder_path(session_obj.id, db),
        narrative_summary=await build_narrative_summary(session_id, db),
        current_die=await get_current_die(session_obj.id, db),
        events=formatted_events,
    )


@router.get("/{session_id}/snapshots")
@cached(ttl=TTL.SHORT)
async def get_session_snapshots(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SnapshotsListResponse:
    """Get session snapshots list.

    Args:
        session_id: The session ID to get snapshots for.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SnapshotsListResponse with list of snapshots.

    Raises:
        HTTPException: If session not found.
    """
    await get_owned_session_or_404(db, current_user.id, session_id)

    snapshots_result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    snapshots = snapshots_result.scalars().all()

    return SnapshotsListResponse(
        session_id=session_id,
        snapshots=[
            SnapshotResponse(
                id=s.id,
                session_id=s.session_id,
                created_at=s.created_at,
                description=s.description,
            )
            for s in snapshots
        ],
    )


@router.post("/{session_id}/restore-session-start")
async def restore_session_start(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Restore session to its initial state at session start.

    Args:
        session_id: The session ID to restore.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse with restored session details.

    Raises:
        HTTPException: If session or snapshot not found.
        RuntimeError: If failed after max retries.
    """
    from sqlalchemy.exc import OperationalError

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            session = await get_owned_session_or_404(db, current_user.id, session_id)

            snapshot_result = await db.execute(
                select(Snapshot)
                .where(Snapshot.session_id == session_id)
                .where(Snapshot.description == "Session start")
                .order_by(Snapshot.created_at)
            )
            snapshot = snapshot_result.scalars().first()

            if not snapshot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No session start snapshot found for session {session_id}",
                )

            from sqlalchemy import delete, or_, update

            snapshot_thread_ids = {int(tid) for tid in snapshot.thread_states.keys()}

            current_threads_result = await db.execute(
                select(Thread).where(Thread.user_id == current_user.id)
            )
            current_threads = current_threads_result.scalars().all()
            current_thread_ids = {thread.id for thread in current_threads}

            threads_to_delete = current_thread_ids - snapshot_thread_ids
            if threads_to_delete:
                await db.execute(
                    update(Event)
                    .where(
                        or_(
                            Event.thread_id.in_(threads_to_delete),
                            Event.selected_thread_id.in_(threads_to_delete),
                        )
                    )
                    .values(thread_id=None, selected_thread_id=None)
                )
                await db.execute(
                    delete(Thread)
                    .where(Thread.id.in_(threads_to_delete))
                    .where(Thread.user_id == current_user.id)
                )

            threads_to_recount: list[Thread] = []
            for thread_id, state in snapshot.thread_states.items():
                thread_id_int = int(thread_id)
                thread = await db.get(Thread, thread_id_int)
                if thread:
                    if "title" in state:
                        thread.title = state["title"]
                    if "format" in state:
                        thread.format = state["format"]
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

                    if "issue_states" in state and state["issue_states"] is not None:
                        await db.execute(delete(Issue).where(Issue.thread_id == thread_id_int))

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
                        if thread.uses_issue_tracking():
                            threads_to_recount.append(thread)
                    else:
                        # Clear migrated state when restoring to legacy
                        await db.execute(delete(Issue).where(Issue.thread_id == thread_id_int))
                        thread.total_issues = None
                        thread.next_unread_issue_id = None
                        thread.reading_progress = None
                        thread.issues_remaining = state.get(
                            "issues_remaining", thread.issues_remaining
                        )
                else:
                    new_thread = Thread(
                        id=thread_id_int,
                        title=state.get("title", "Unknown Thread"),
                        format=state.get("format", "comic"),
                        issues_remaining=state.get("issues_remaining", 0),
                        last_rating=state.get("last_rating"),
                        queue_position=state.get("queue_position", 1),
                        status=state.get("status", "active"),
                        notes=state.get("notes"),
                        is_test=state.get("is_test", False),
                        user_id=state.get("user_id", session.user_id),
                        created_at=datetime.fromisoformat(state["created_at"])
                        if state.get("created_at")
                        else datetime.now(UTC),
                    )
                    if state.get("last_activity_at"):
                        new_thread.last_activity_at = datetime.fromisoformat(
                            state["last_activity_at"]
                        )
                    db.add(new_thread)

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
                        if new_thread.uses_issue_tracking():
                            threads_to_recount.append(new_thread)
                    else:
                        new_thread.issues_remaining = state.get("issues_remaining", 0)

            if threads_to_recount:
                await db.flush()
                unread_counts = await load_unread_counts(threads_to_recount, db)
                for thread_obj in threads_to_recount:
                    thread_obj.issues_remaining = unread_counts.get(thread_obj.id, 0)

            if snapshot.session_state:
                session.start_die = snapshot.session_state.get("start_die", session.start_die)
                session.manual_die = snapshot.session_state.get("manual_die", session.manual_die)

            await db.commit()
            await db.refresh(session)
            await refresh_user_blocked_status(current_user.id, db)
            await db.commit()
            await db.refresh(session)

            await invalidate_user_view(current_user.id)

            from sqlalchemy import func

            active_thread = await get_active_thread(session.id, db)

            snapshot_count_result = await db.execute(
                select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
            )
            snapshot_count = snapshot_count_result.scalar() or 0

            return SessionResponse(
                id=session.id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                start_die=session.start_die,
                manual_die=session.manual_die,
                user_id=session.user_id,
                ladder_path=await build_ladder_path(session.id, db),
                active_thread=active_thread,
                current_die=await get_current_die(session.id, db),
                last_rolled_result=active_thread.last_rolled_result if active_thread else None,
                has_restore_point=snapshot_count > 0,
                snapshot_count=snapshot_count,
                pending_thread_id=session.pending_thread_id,
            )
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                await db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise
                delay = initial_delay * (2 ** (retries - 1))
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to restore session after {max_retries} retries")


@router.post("/mode/", response_model=ModeChangeResponse)
async def set_session_mode(
    request: ModeChangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ModeChangeResponse:
    """Set bandwidth and/or intent for the active session.

    Accepts optional bandwidth (die size) and/or intent changes against the
    active session. Unspecified dimensions are preserved (not reset). Changed
    dimensions are marked with source `manual` and appropriate confidence
    semantics. Invalid values fail safely with 422 validation.

    Args:
        request: The mode change request containing optional bandwidth and intent.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        The canonical updated mode state.

    Raises:
        HTTPException: If no active session exists.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    current_session_id = current_session.id

    # Determine which dimensions are being changed.
    changed_bandwidth = request.bandwidth is not None
    changed_intent = request.intent is not None

    # If neither dimension is provided, return current state without changes.
    if not changed_bandwidth and not changed_intent:
        return ModeChangeResponse(
            bandwidth=current_session.bandwidth,
            intent=current_session.intent,
            source=current_session.source or ModeSource.MANUAL,
            confidence=current_session.confidence or 1.0,
            session_id=current_session_id,
            updated_at=datetime.now(UTC).isoformat(),
        )

    # Track old values for reference.
    old_bandwidth = current_session.bandwidth
    old_intent = current_session.intent

    if changed_bandwidth:
        current_session.bandwidth = request.bandwidth

    if changed_intent:
        current_session.intent = request.intent

    # Mark changed dimensions with source=manual and confidence semantics.
    source = ModeSource.MANUAL
    confidence = 1.0  # Manual changes have full confidence
    current_session.source = source
    current_session.confidence = confidence

    # Record a compact mode-change event for later analytics.
    event = Event(
        type=EventType.MODE_CHANGE,
        session_id=current_session_id,
        die=request.bandwidth if changed_bandwidth else None,
        selection_method=request.intent if changed_intent else None,
    )
    db.add(event)

    # Extract all needed session attributes BEFORE commit to avoid MissingGreenlet.
    updated_bandwidth = current_session.bandwidth
    updated_intent = current_session.intent
    updated_source = source
    updated_confidence = confidence

    await db.commit()

    await _invalidate_session_caches(user_id)

    return ModeChangeResponse(
        bandwidth=updated_bandwidth,
        intent=updated_intent,
        source=updated_source,
        confidence=updated_confidence,
        session_id=current_session_id,
        updated_at=datetime.now(UTC).isoformat(),
    )
