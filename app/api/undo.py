"""Undo API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.schemas.thread import SessionResponse
from comic_pile.session import get_current_die

router = APIRouter(tags=["undo"])

clear_cache = None


@router.post("/{session_id}/undo/{snapshot_id}")
def undo_to_snapshot(
    session_id: int, snapshot_id: int, db: Session = Depends(get_db)
) -> SessionResponse:
    """Undo session state to a specific snapshot with deadlock retry handling."""
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

            from sqlalchemy import delete, or_, update

            snapshot_thread_ids = {int(tid) for tid in snapshot.thread_states.keys()}

            current_threads = db.execute(select(Thread)).scalars().all()
            current_thread_ids = {thread.id for thread in current_threads}

            threads_to_delete = current_thread_ids - snapshot_thread_ids
            if threads_to_delete:
                db.execute(
                    update(SessionModel)
                    .where(SessionModel.id == session_id)
                    .where(SessionModel.pending_thread_id.in_(threads_to_delete))
                    .values(pending_thread_id=None)
                )
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
                db.expire_all()

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

            if clear_cache:
                clear_cache()

            active_thread = (
                db.execute(
                    select(Event)
                    .where(Event.session_id == session_id)
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

            snapshot_count = (
                db.execute(
                    select(func.count())
                    .select_from(Snapshot)
                    .where(Snapshot.session_id == session_id)
                ).scalar()
                or 0
            )

            return SessionResponse(
                id=session_id,
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
                current_die=get_current_die(session_id, db),
                last_rolled_result=active_thread.result if active_thread else None,
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

    raise RuntimeError(f"Failed to undo to snapshot after {max_retries} retries")


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
