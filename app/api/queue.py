"""Queue API routes."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread, User
from app.schemas import ThreadResponse
from app.api.thread import thread_to_response
from comic_pile.queue import move_to_back, move_to_front, move_to_position

logger = logging.getLogger(__name__)


router = APIRouter()

clear_cache = None


class PositionRequest(BaseModel):
    """Schema for position update request."""

    new_position: int = Field(..., ge=1)


@router.put("/threads/{thread_id}/position/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_position(
    request: Request,
    thread_id: int,
    position_request: PositionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to specific position."""
    logger.info(
        f"API move_thread_position: thread_id={thread_id}, user_id={current_user.id}, "
        f"new_position={position_request.new_position}, request_url={request.url}"
    )

    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == current_user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        logger.error(f"Thread {thread_id} not found for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    old_position = thread.queue_position
    logger.info(f"Thread {thread_id} current position: {old_position}")

    try:
        await move_to_position(thread_id, current_user.id, position_request.new_position, db)
        await db.refresh(thread)
        logger.info(f"Thread {thread_id} refreshed, new position: {thread.queue_position}")
    except Exception as e:
        logger.error(
            f"Error moving thread {thread_id} to position {position_request.new_position}: {e}"
        )
        raise

    if old_position != thread.queue_position:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        await db.commit()

    if clear_cache:
        clear_cache()

    return thread_to_response(thread)


@router.put("/threads/{thread_id}/front/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_front(
    request: Request,
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to the front."""
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == current_user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    old_position = thread.queue_position
    await move_to_front(thread_id, current_user.id, db)
    await db.refresh(thread)

    if old_position != thread.queue_position:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        await db.commit()

    if clear_cache:
        clear_cache()

    return thread_to_response(thread)


@router.put("/threads/{thread_id}/back/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_back(
    request: Request,
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to the back."""
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == current_user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    old_position = thread.queue_position
    await move_to_back(thread_id, current_user.id, db)
    await db.refresh(thread)

    if old_position != thread.queue_position:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        await db.commit()

    if clear_cache:
        clear_cache()

    return thread_to_response(thread)
