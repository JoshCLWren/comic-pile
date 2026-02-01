"""Session API endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread, User
from app.models import Session as SessionModel
from app.schemas import (
    ActiveThreadInfo,
    EventDetail,
    SessionDetailsResponse,
    SessionResponse,
    SnapshotResponse,
    SnapshotsListResponse,
)
from app.schemas.session import SnoozedThreadInfo
from comic_pile.session import get_current_die, get_or_create, is_active

router = APIRouter(prefix="/sessions", tags=["sessions"])

clear_cache = None
get_current_session_cached = None


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

    # Query Event table after Session to ensure consistent lock ordering
    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    event = event_result.scalars().first()

    if not event or not event.selected_thread_id:
        return session, None

    thread = await db.get(Thread, event.selected_thread_id)
    if not thread:
        return session, None

    return session, ActiveThreadInfo(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        queue_position=thread.queue_position,
        last_rolled_result=event.result,
    )


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

    for event in events:
        thread = await db.get(Thread, event.thread_id) if event.thread_id else None
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


async def build_ladder_path(session_id: int, db: AsyncSession) -> str:
    """Build narrative summary of dice ladder from session events.

    Args:
        session_id: The session ID to build ladder path for.
        db: Database session.

    Returns:
        String representation of dice ladder path (e.g., "d4 → d6 → d8").
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        return ""

    events_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp)
    )
    events = events_result.scalars().all()

    if not events:
        return str(session.start_die)

    path = [session.start_die]
    for event in events:
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

    return ActiveThreadInfo(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        queue_position=thread.queue_position,
        last_rolled_result=event.result,
    )


@router.get("/current/")
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
            if get_current_session_cached:
                cached = get_current_session_cached(db)
                if cached:
                    return SessionResponse(**cached)

            active_sessions_result = await db.execute(
                select(SessionModel)
                .where(SessionModel.user_id == current_user.id)
                .where(SessionModel.ended_at.is_(None))
                .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
            )
            active_sessions = active_sessions_result.scalars().all()

            active_session = None
            for session in active_sessions:
                if await is_active(session.started_at, session.ended_at, db):
                    active_session = session
                    break

            if not active_session:
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
            for thread_id in active_session.snoozed_thread_ids or []:
                thread = await db.get(Thread, thread_id)
                if thread:
                    snoozed_threads.append(SnoozedThreadInfo(id=thread.id, title=thread.title))

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


@router.get("/")
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    """List all sessions (paginated).

    Args:
        current_user: The authenticated user making the request.
        limit: Maximum number of sessions to return.
        offset: Number of sessions to skip.
        db: SQLAlchemy session for database operations.

    Returns:
        List of SessionResponse objects.
    """
    sessions_result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    sessions = sessions_result.scalars().all()

    responses = []
    from sqlalchemy import func

    for session in sessions:
        _, active_thread = await get_session_with_thread_safe(session.id, db)

        snapshot_count_result = await db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
        )
        snapshot_count = snapshot_count_result.scalar() or 0

        responses.append(
            SessionResponse(
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
            )
        )
    return responses


@router.get("/{session_id}")
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
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

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
    )


@router.get("/{session_id}/details")
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
    session_obj = await db.get(SessionModel, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")

    if session_obj.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    events_result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    events = events_result.scalars().all()

    formatted_events = []
    for event in events:
        thread_title = None
        if event.type == "roll":
            thread_id = event.selected_thread_id
        else:
            thread_id = event.thread_id

        if thread_id:
            thread = await db.get(Thread, thread_id)
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
        elif event.type == "rate":
            event_data.rating = event.rating
            event_data.issues_read = event.issues_read
            event_data.queue_move = event.queue_move
            event_data.die_after = event.die_after

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
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    snapshots_result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc())
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
            session = await db.get(SessionModel, session_id)
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session {session_id} not found",
                )

            if session.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )

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
                    if "review_url" in state:
                        thread.review_url = state["review_url"]
                    if "notes" in state:
                        thread.notes = state["notes"]
                    if "is_test" in state:
                        thread.is_test = state["is_test"]
                    if state.get("last_activity_at"):
                        thread.last_activity_at = datetime.fromisoformat(state["last_activity_at"])
                    if state.get("last_review_at"):
                        thread.last_review_at = datetime.fromisoformat(state["last_review_at"])
                else:
                    new_thread = Thread(
                        id=thread_id_int,
                        title=state.get("title", "Unknown Thread"),
                        format=state.get("format", "comic"),
                        issues_remaining=state.get("issues_remaining", 0),
                        last_rating=state.get("last_rating"),
                        queue_position=state.get("queue_position", 1),
                        status=state.get("status", "active"),
                        review_url=state.get("review_url"),
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
                    if state.get("last_review_at"):
                        new_thread.last_review_at = datetime.fromisoformat(state["last_review_at"])
                    db.add(new_thread)

            if snapshot.session_state:
                session.start_die = snapshot.session_state.get("start_die", session.start_die)
                session.manual_die = snapshot.session_state.get("manual_die", session.manual_die)

            await db.commit()
            await db.refresh(session)

            if clear_cache:
                clear_cache()

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
