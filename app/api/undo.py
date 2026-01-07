"""Undo API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.schemas.thread import SessionResponse
from comic_pile.session import get_current_die

router = APIRouter(tags=["undo"])

try:
    from app.main import clear_cache
except ImportError:
    clear_cache = None


@router.post("/{session_id}/undo/{snapshot_id}")
def undo_to_snapshot(
    session_id: int, snapshot_id: int, db: Session = Depends(get_db)
) -> SessionResponse:
    """Undo session state to a specific snapshot."""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    snapshot = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session_id)
            .where(Snapshot.id == snapshot_id)
        )
        .scalars()
        .first()
    )

    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found for session {session_id}",
        )

    thread_states = snapshot.thread_states
    for thread_id, state in thread_states.items():
        thread = db.get(Thread, thread_id)
        if thread:
            thread.issues_remaining = state.get("issues_remaining", thread.issues_remaining)
            thread.last_rating = state.get("last_rating", thread.last_rating)
            thread.queue_position = state.get("queue_position", thread.queue_position)
            thread.status = state.get("status", thread.status)
            if state.get("last_activity_at"):
                thread.last_activity_at = datetime.fromisoformat(state["last_activity_at"])

    db.commit()

    if clear_cache:
        clear_cache()

    active_thread = (
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

    thread = None
    if active_thread and active_thread.selected_thread_id:
        thread = db.get(Thread, active_thread.selected_thread_id)

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=str(session.start_die),
        active_thread={
            "id": thread.id if thread else None,
            "title": thread.title if thread else "",
            "format": thread.format if thread else "",
            "issues_remaining": thread.issues_remaining if thread else 0,
            "position": thread.queue_position if thread else 0,
            "last_rolled_result": active_thread.result if active_thread else None,
        }
        if thread
        else None,
        current_die=get_current_die(session.id, db),
        last_rolled_result=active_thread.result if active_thread else None,
    )


@router.get("/{session_id}/snapshots")
def list_session_snapshots(session_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """List all snapshots for a session."""
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    snapshots = (
        db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session_id)
            .order_by(Snapshot.created_at.desc())
        )
        .scalars()
        .all()
    )

    return [
        {
            "id": s.id,
            "created_at": s.created_at,
            "description": s.description,
            "event_id": s.event_id,
        }
        for s in snapshots
    ]
