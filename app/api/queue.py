"""Queue API routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Thread
from app.schemas import ThreadResponse
from comic_pile.queue import move_to_back, move_to_front, move_to_position

router = APIRouter()

try:
    from app.main import clear_cache
except ImportError:
    clear_cache = None


class PositionRequest(BaseModel):
    """Schema for position update request."""

    new_position: int = Field(..., ge=0)


@router.put("/threads/{thread_id}/position/", response_model=ThreadResponse)
def move_thread_position(
    thread_id: int, request: PositionRequest, db: Session = Depends(get_db)
) -> ThreadResponse:
    """Move thread to specific position."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    move_to_position(thread_id, request.new_position, db)
    db.refresh(thread)

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
        created_at=thread.created_at,
    )


@router.put("/threads/{thread_id}/front/", response_model=ThreadResponse)
def move_thread_front(thread_id: int, db: Session = Depends(get_db)) -> ThreadResponse:
    """Move thread to front of queue."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    move_to_front(thread_id, db)
    db.refresh(thread)

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
        created_at=thread.created_at,
    )


@router.put("/threads/{thread_id}/back/", response_model=ThreadResponse)
def move_thread_back(thread_id: int, db: Session = Depends(get_db)) -> ThreadResponse:
    """Move thread to back of queue."""
    thread = db.get(Thread, thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    move_to_back(thread_id, db)
    db.refresh(thread)

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
        created_at=thread.created_at,
    )
