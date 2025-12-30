"""Session API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Session as SessionModel, Thread
from app.schemas.thread import SessionResponse
from comic_pile.session import is_active

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
    """Get the most recently read thread for the session."""
    event = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .where(Event.type == "rate")
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
    cutoff_time = SessionModel.started_at >= None

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
        raise HTTPException(status_code=404, detail="No active session found")

    return SessionResponse(
        id=active_session.id,
        started_at=active_session.started_at,
        ended_at=active_session.ended_at,
        start_die=active_session.start_die,
        user_id=active_session.user_id,
        ladder_path=build_ladder_path(active_session, db),
        active_thread=get_active_thread(active_session, db),
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
    )
