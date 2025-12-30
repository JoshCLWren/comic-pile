"""Rate API endpoint."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Thread
from app.models import Session as SessionModel
from app.schemas import RateRequest, ThreadResponse
from comic_pile.dice_ladder import step_down, step_up
from comic_pile.queue import move_to_back

router = APIRouter()


@router.post("/rate/", response_model=ThreadResponse)
def rate_thread(request: RateRequest, db: Session = Depends(get_db)) -> ThreadResponse:
    """Rate current reading and update thread."""
    current_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .first()
    )

    if not current_session:
        raise HTTPException(status_code=400, detail="No active session")

    last_roll_event = (
        db.execute(
            select(Event)
            .where(Event.session_id == current_session.id)
            .where(Event.type == "roll")
            .where(Event.selected_thread_id.is_not(None))
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if not last_roll_event:
        raise HTTPException(status_code=400, detail="No active thread")

    thread = db.get(Thread, last_roll_event.selected_thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    current_die = current_session.start_die
    last_rate_event = (
        db.execute(
            select(Event)
            .where(Event.session_id == current_session.id)
            .where(Event.type == "rate")
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if last_rate_event and last_rate_event.die_after:
        current_die = last_rate_event.die_after

    thread.issues_remaining -= request.issues_read
    thread.last_rating = request.rating
    thread.last_activity_at = datetime.now()

    if request.rating >= 3.5:
        new_die = step_up(current_die)
    else:
        new_die = step_down(current_die)

    event = Event(
        type="rate",
        session_id=current_session.id,
        thread_id=thread.id,
        rating=request.rating,
        issues_read=request.issues_read,
        die=current_die,
        die_after=new_die,
    )
    db.add(event)

    if thread.issues_remaining <= 0:
        thread.status = "completed"
        move_to_back(thread.id, db)
        current_session.ended_at = datetime.now()

    db.commit()
    db.refresh(thread)

    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        position=thread.queue_position,
        created_at=thread.created_at,
    )
