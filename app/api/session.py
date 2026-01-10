"""Session API endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.schemas.thread import (
    EventDetail,
    SessionDetailsResponse,
    SessionResponse,
    SnapshotResponse,
    SnapshotsListResponse,
)
from comic_pile.session import get_current_die, get_or_create, is_active

router = APIRouter(prefix="/sessions", tags=["sessions"])

clear_cache = None
get_current_session_cached = None


def build_narrative_summary(session_id: int, db: Session) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events."""
    events = (
        db.execute(select(Event).where(Event.session_id == session_id).order_by(Event.timestamp))
        .scalars()
        .all()
    )

    summary = {
        "read": [],
        "skipped": [],
        "completed": [],
    }

    read_entries = []
    skipped_titles = set()
    completed_titles = set()

    for event in events:
        thread = db.get(Thread, event.thread_id) if event.thread_id else None
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


def build_ladder_path(session: SessionModel, db: Session) -> str:
    """Build narrative summary of dice ladder from session events."""
    events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .where(Event.type == "rate")
            .order_by(Event.timestamp)
        )
        .scalars()
        .all()
    )

    if not events:
        return str(session.start_die)

    path = [session.start_die]
    for event in events:
        if event.die_after:
            path.append(event.die_after)

    return " → ".join(str(d) for d in path)


def get_active_thread(session: SessionModel, db: Session) -> dict[str, Any] | None:
    """Get the most recently rolled thread for the session."""
    event = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .where(Event.type == "roll")
            .where(Event.selected_thread_id.is_not(None))
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if not event or not event.selected_thread_id:
        return None

    thread = db.get(Thread, event.selected_thread_id)
    if not thread:
        return None

    return {
        "id": thread.id,
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": thread.issues_remaining,
        "position": thread.queue_position,
        "last_rolled_result": event.result,
    }


@router.get("/current/")
@limiter.limit("200/minute")
def get_current_session(request: Request, db: Session = Depends(get_db)) -> SessionResponse:
    """Get current active session."""
    if get_current_session_cached:
        cached = get_current_session_cached(db)
        if cached:
            return SessionResponse(**cached)

    active_sessions = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .all()
    )

    active_session = None
    for session in active_sessions:
        if is_active(session.started_at, session.ended_at, db):
            active_session = session
            break

    if not active_session:
        active_session = get_or_create(db, user_id=1)

    active_thread = get_active_thread(active_session, db)

    from sqlalchemy import func

    snapshot_count = (
        db.execute(
            select(func.count())
            .select_from(Snapshot)
            .where(Snapshot.session_id == active_session.id)
        ).scalar()
        or 0
    )

    return SessionResponse(
        id=active_session.id,
        started_at=active_session.started_at,
        ended_at=active_session.ended_at,
        start_die=active_session.start_die,
        manual_die=active_session.manual_die,
        user_id=active_session.user_id,
        ladder_path=build_ladder_path(active_session, db),
        active_thread=active_thread,
        current_die=get_current_die(active_session.id, db),
        last_rolled_result=active_thread.get("last_rolled_result") if active_thread else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
    )


@router.get("/")
def list_sessions(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[SessionResponse]:
    """List all sessions (paginated)."""
    sessions = (
        db.execute(
            select(SessionModel)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )

    responses = []
    from sqlalchemy import func

    for session in sessions:
        active_thread = get_active_thread(session, db)

        snapshot_count = (
            db.execute(
                select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
            ).scalar()
            or 0
        )

        responses.append(
            SessionResponse(
                id=session.id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                start_die=session.start_die,
                manual_die=session.manual_die,
                user_id=session.user_id,
                ladder_path=build_ladder_path(session, db),
                active_thread=active_thread,
                current_die=get_current_die(session.id, db),
                last_rolled_result=active_thread.get("last_rolled_result")
                if active_thread
                else None,
                has_restore_point=snapshot_count > 0,
                snapshot_count=snapshot_count,
            )
        )
    return responses


@router.get("/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)) -> SessionResponse:
    """Get single session by ID."""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    active_thread = get_active_thread(session, db)

    from sqlalchemy import func

    snapshot_count = (
        db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
        ).scalar()
        or 0
    )

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=build_ladder_path(session, db),
        active_thread=active_thread,
        current_die=get_current_die(session.id, db),
        last_rolled_result=active_thread.get("last_rolled_result") if active_thread else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
    )


@router.get("/{session_id}/details")
def get_session_details(session_id: int, db: Session = Depends(get_db)) -> SessionDetailsResponse:
    """Get session details with all events for expanded view."""
    session_obj = db.get(SessionModel, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")

    events = (
        db.execute(select(Event).where(Event.session_id == session_id).order_by(Event.timestamp))
        .scalars()
        .all()
    )

    formatted_events = []
    for event in events:
        thread_title = None
        if event.type == "roll":
            thread_id = event.selected_thread_id
        else:
            thread_id = event.thread_id

        if thread_id:
            thread = db.get(Thread, thread_id)
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
        ladder_path=build_ladder_path(session_obj, db),
        narrative_summary=build_narrative_summary(session_id, db),
        current_die=get_current_die(session_obj.id, db),
        events=formatted_events,
    )


@router.get("/{session_id}/snapshots")
def get_session_snapshots(session_id: int, db: Session = Depends(get_db)) -> SnapshotsListResponse:
    """Get session snapshots list."""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    snapshots = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session_id)
            .order_by(Snapshot.created_at.desc())
        )
        .scalars()
        .all()
    )

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
def restore_session_start(session_id: int, db: Session = Depends(get_db)) -> SessionResponse:
    """Restore session to its initial state at session start."""
    from sqlalchemy.exc import OperationalError
    import time

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            session = db.get(SessionModel, session_id, with_for_update=True)
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session {session_id} not found",
                )

            snapshot = (
                db.execute(
                    select(Snapshot)
                    .where(Snapshot.session_id == session_id)
                    .where(Snapshot.description == "Session start")
                    .order_by(Snapshot.created_at)
                )
                .scalars()
                .first()
            )

            if not snapshot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No session start snapshot found for session {session_id}",
                )

            from sqlalchemy import delete, or_, update

            snapshot_thread_ids = {int(tid) for tid in snapshot.thread_states.keys()}

            current_threads = db.execute(select(Thread)).scalars().all()
            current_thread_ids = {thread.id for thread in current_threads}

            threads_to_delete = current_thread_ids - snapshot_thread_ids
            if threads_to_delete:
                db.execute(
                    update(Event)
                    .where(
                        or_(
                            Event.thread_id.in_(threads_to_delete),
                            Event.selected_thread_id.in_(threads_to_delete),
                        )
                    )
                    .values(thread_id=None, selected_thread_id=None)
                )
                db.execute(delete(Thread).where(Thread.id.in_(threads_to_delete)))

            for thread_id, state in snapshot.thread_states.items():
                thread_id_int = int(thread_id)
                thread = db.get(Thread, thread_id_int)
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
                        id=thread_id,
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
                        else datetime.now(),
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

            db.commit()
            db.refresh(session)

            if clear_cache:
                clear_cache()

            from sqlalchemy import func

            active_thread = get_active_thread(session, db)

            snapshot_count = (
                db.execute(
                    select(func.count())
                    .select_from(Snapshot)
                    .where(Snapshot.session_id == session.id)
                ).scalar()
                or 0
            )

            return SessionResponse(
                id=session.id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                start_die=session.start_die,
                manual_die=session.manual_die,
                user_id=session.user_id,
                ladder_path=build_ladder_path(session, db),
                active_thread=active_thread,
                current_die=get_current_die(session.id, db),
                last_rolled_result=active_thread.get("last_rolled_result")
                if active_thread
                else None,
                has_restore_point=snapshot_count > 0,
                snapshot_count=snapshot_count,
            )
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise
                delay = initial_delay * (2 ** (retries - 1))
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to restore session after {max_retries} retries")
