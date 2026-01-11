"""Queue API routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread
from app.schemas import ThreadResponse
from comic_pile.queue import move_to_back, move_to_front, move_to_position

router = APIRouter()

clear_cache = None


class PositionRequest(BaseModel):
    """Schema for position update request."""

    new_position: int = Field(..., ge=1)


@router.put("/threads/{thread_id}/position/", response_model=ThreadResponse)
@limiter.limit("30/minute")
def move_thread_position(
    request: Request,
    thread_id: int,
    position_request: PositionRequest,
    db: Session = Depends(get_db),
) -> ThreadResponse:
    """Move thread to specific position."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    old_position = thread.queue_position
    new_position = position_request.new_position

    if old_position != new_position:
        from comic_pile.dice_ladder import DICE_LADDER
        if new_position not in DICE_LADDER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid position: {new_position}. Valid positions are {DICE_LADDER}",
            )

    if old_position != new_position:
        reorder_event = Event(
            type="reorder",
            thread_id=thread_id,
            timestamp=datetime.now(UTC),
            old_position=old_position,
            new_position=new_position,
        )
        db.add(reorder_event)

        thread.queue_position = new_position
        db.commit()

    if clear_cache:
        clear_cache()

    db.refresh(thread)

    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        queue_position=thread.queue_position,
        status=thread.status,
        created_at=thread.created_at,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        last_review_at=thread.last_review_at,
        review_url=thread.review_url,
        notes=thread.notes,
        is_test=thread.is_test,
        user_id=thread.user_id,
        created_at=thread.created_at,
    )

    old_position = thread.queue_position
    move_to_position(thread_id, position_request.new_position, db)
    db.refresh(thread)

    if old_position != thread.queue_position:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        db.commit()

    if clear_cache:
        clear_cache()

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
        notes=thread.notes,
        is_test=thread.is_test,
        created_at=thread.created_at,
    )


@router.put("/threads/{thread_id}/front/", response_model=ThreadResponse)
@limiter.limit("30/minute")
def move_thread_front(
    request: Request, thread_id: int, db: Session = Depends(get_db)
) -> ThreadResponse:
    """Move thread to front of queue."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    old_position = thread.queue_position
    move_to_front(thread_id, db)
    db.refresh(thread)

    if old_position != thread.queue_position:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        db.commit()

    if clear_cache:
        clear_cache()

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
        notes=thread.notes,
        is_test=thread.is_test,
        created_at=thread.created_at,
    )


@router.put("/threads/{thread_id}/back/", response_model=ThreadResponse)
@limiter.limit("30/minute")
def move_thread_back(
    request: Request, thread_id: int, db: Session = Depends(get_db)
) -> ThreadResponse:
    """Move thread to back of queue."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    old_position = thread.queue_position
    move_to_back(thread_id, db)
    db.refresh(thread)

    if old_position != thread.queue_position:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        db.commit()

    if clear_cache:
        clear_cache()

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
        notes=thread.notes,
        is_test=thread.is_test,
        created_at=thread.created_at,
    )
