"""Rate API endpoint."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Settings, Thread
from app.models import Session as SessionModel
from app.schemas import RateRequest, ThreadResponse
from comic_pile.dice_ladder import step_down, step_up
from comic_pile.queue import move_to_back, move_to_front

router = APIRouter()

try:
    from app.main import clear_cache
except ImportError:
    clear_cache = None


def _get_settings(db: Session) -> Settings:
    """Get settings record, creating with defaults if needed."""
    settings = db.execute(select(Settings)).scalars().first()
    if not settings:
        settings = Settings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.post("/", response_model=ThreadResponse)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session. Please roll the dice first.",
        )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active thread. Please roll the dice first.",
        )

    thread = db.get(Thread, last_roll_event.selected_thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {last_roll_event.selected_thread_id} not found",
        )

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

    settings = _get_settings(db)

    if request.rating < settings.rating_min or request.rating > settings.rating_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rating must be between {settings.rating_min} and {settings.rating_max}",
        )

    thread.issues_remaining -= request.issues_read
    thread.last_rating = request.rating
    thread.last_activity_at = datetime.now()

    if request.rating >= settings.rating_threshold:
        new_die = step_down(current_die)
    else:
        new_die = step_up(current_die)

    current_session.manual_die = new_die

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

    if request.rating >= settings.rating_threshold:
        move_to_front(thread.id, db)
    else:
        move_to_back(thread.id, db)

    if thread.issues_remaining <= 0:
        thread.status = "completed"
        move_to_back(thread.id, db)
        current_session.ended_at = datetime.now()

    if clear_cache:
        clear_cache()

    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None

    db.commit()
    db.refresh(thread)

    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        position=thread.queue_position,
        status=thread.status,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        review_url=thread.review_url,
        last_review_at=thread.last_review_at,
        created_at=thread.created_at,
    )
