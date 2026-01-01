"""Session API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Thread
from app.models import Session as SessionModel
from app.schemas.thread import SessionResponse
from comic_pile.session import get_current_die, is_active

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/sessions", tags=["sessions"])

try:
    from app.main import clear_cache, get_current_session_cached
except ImportError:
    clear_cache = None
    get_current_session_cached = None


def build_narrative_summary(session_id: int, db: Session) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events."""
    events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.timestamp)
        )
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

    # Consolidate (optional, but following PRD example)
    summary["read"] = read_entries
    summary["skipped"] = sorted(list(skipped_titles))
    summary["completed"] = sorted(list(completed_titles))

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

    if not event or not event.thread_id:
        return None

    thread = db.get(Thread, event.thread_id)
    if not thread:
        return None

    return {
        "id": thread.id,
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": thread.issues_remaining,
        "position": thread.queue_position,
    }


@router.get("/current/")
def get_current_session(db: Session = Depends(get_db)) -> SessionResponse:
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
        if is_active(session):
            active_session = session
            break

    if not active_session:
        raise HTTPException(
            status_code=404,
            detail="No active session found",
        )

    return SessionResponse(
        id=active_session.id,
        started_at=active_session.started_at,
        ended_at=active_session.ended_at,
        start_die=active_session.start_die,
        user_id=active_session.user_id,
        ladder_path=build_ladder_path(active_session, db),
        active_thread=get_active_thread(active_session, db),
        current_die=get_current_die(active_session.id, db),
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

    return [
        SessionResponse(
            id=session.id,
            started_at=session.started_at,
            ended_at=session.ended_at,
            start_die=session.start_die,
            user_id=session.user_id,
            ladder_path=build_ladder_path(session, db),
            active_thread=get_active_thread(session, db),
            current_die=get_current_die(session.id, db),
        )
        for session in sessions
    ]


@router.get("/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)) -> SessionResponse:
    """Get single session by ID."""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        user_id=session.user_id,
        ladder_path=build_ladder_path(session, db),
        active_thread=get_active_thread(session, db),
        current_die=get_current_die(session.id, db),
    )


@router.get("/{session_id}/details", response_class=HTMLResponse)
def get_session_details(
    session_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
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
        if event.thread_id:
            thread = db.get(Thread, event.thread_id)
            if thread:
                thread_title = thread.title

        event_data = {
            "id": event.id,
            "type": event.type,
            "timestamp": event.timestamp,
            "thread_title": thread_title,
        }

        if event.type == "roll":
            event_data.update(
                {
                    "die": event.die,
                    "result": event.result,
                    "selection_method": event.selection_method,
                }
            )
        elif event.type == "rate":
            event_data.update(
                {
                    "rating": event.rating,
                    "issues_read": event.issues_read,
                    "queue_move": event.queue_move,
                    "die_after": event.die_after,
                }
            )

        formatted_events.append(event_data)

    return templates.TemplateResponse(
        "session_details.html",
        {
            "request": request,
            "session_id": session_obj.id,
            "started_at": session_obj.started_at,
            "ended_at": session_obj.ended_at,
            "start_die": session_obj.start_die,
            "ladder_path": build_ladder_path(session_obj, db),
            "narrative_summary": build_narrative_summary(session_id, db),
            "current_die": get_current_die(session_obj.id, db),
            "events": formatted_events,
        },
    )
