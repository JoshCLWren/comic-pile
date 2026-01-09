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
