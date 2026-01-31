"""Rate API endpoint."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.auth import get_current_user
from app.config import get_rating_settings
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import RateRequest, ThreadResponse
from app.api.thread import thread_to_response
from comic_pile.dice_ladder import step_down, step_up
from comic_pile.queue import move_to_back, move_to_front
from comic_pile.session import get_current_die

router = APIRouter()


async def snapshot_thread_states(
    db: AsyncSession, session_id: int, event: Event, user_id: int
) -> None:
    """Create a snapshot of all thread states for undo functionality."""
    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    threads = result.scalars().all()

    thread_states = {}
    for thread in threads:
        thread_states[thread.id] = {
            "title": thread.title,
            "format": thread.format,
            "issues_remaining": thread.issues_remaining,
            "last_rating": thread.last_rating,
            "last_activity_at": thread.last_activity_at.isoformat()
            if thread.last_activity_at
            else None,
            "queue_position": thread.queue_position,
            "status": thread.status,
            "review_url": thread.review_url,
            "last_review_at": thread.last_review_at.isoformat() if thread.last_review_at else None,
            "notes": thread.notes,
            "is_test": thread.is_test,
            "created_at": thread.created_at.isoformat(),
            "user_id": thread.user_id,
        }

    session = await db.get(SessionModel, session_id)
    session_state = None
    if session:
        session_state = {
            "start_die": session.start_die,
            "manual_die": session.manual_die,
        }

    snapshot = Snapshot(
        session_id=session_id,
        event_id=event.id,
        thread_states=thread_states,
        session_state=session_state,
        description=f"After rating {event.rating}/5.0",
    )
    db.add(snapshot)
    await db.commit()


clear_cache = None


def _get_rating_limits() -> tuple[float, float, float]:
    """Get rating min, max, and threshold from config."""
    settings = get_rating_settings()
    return settings.rating_min, settings.rating_max, settings.rating_threshold


@router.post("/", response_model=ThreadResponse)
@limiter.limit("60/minute")
async def rate_thread(
    request: Request,
    rate_data: RateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Rate current reading and update thread."""
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc())
    )
    current_session = result.scalars().first()

    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session. Please roll the dice first.",
        )

    current_session_id = current_session.id
    result = await db.execute(
        select(Event)
        .where(Event.session_id == current_session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    last_roll_event = result.scalars().first()

    if not last_roll_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active thread. Please roll the dice first.",
        )

    result = await db.execute(
        select(Thread)
        .where(Thread.id == last_roll_event.selected_thread_id)
        .where(Thread.user_id == current_user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {last_roll_event.selected_thread_id} not found",
        )

    current_die = await get_current_die(current_session_id, db)

    rating_min, rating_max, rating_threshold = _get_rating_limits()

    if rate_data.rating < rating_min or rate_data.rating > rating_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rating must be between {rating_min} and {rating_max}",
        )

    thread.issues_remaining -= rate_data.issues_read
    thread.last_rating = rate_data.rating
    thread.last_activity_at = datetime.now()

    if rate_data.rating >= rating_threshold:
        new_die = step_down(current_die)
    else:
        new_die = step_up(current_die)

    event = Event(
        type="rate",
        session_id=current_session_id,
        thread_id=thread.id,
        rating=rate_data.rating,
        issues_read=rate_data.issues_read,
        die=current_die,
        die_after=new_die,
    )
    db.add(event)

    if rate_data.rating >= rating_threshold:
        await move_to_front(thread.id, current_user.id, db)
    else:
        await move_to_back(thread.id, current_user.id, db)

    if rate_data.finish_session:
        current_session.ended_at = datetime.now()
        current_session.snoozed_thread_ids = None
        if thread.issues_remaining <= 0:
            thread.status = "completed"
            await move_to_back(thread.id, current_user.id, db)

    if clear_cache:
        clear_cache()

    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None

    await db.commit()

    await snapshot_thread_states(db, current_session_id, event, current_user.id)
    await db.refresh(thread)

    return thread_to_response(thread)
