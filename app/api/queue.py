"""Queue API routes."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.thread import thread_to_response
from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread, User
from app.schemas import ThreadResponse
from comic_pile.queue import move_to_back, move_to_front, move_to_position, shuffle_queue

logger = logging.getLogger(__name__)


router = APIRouter()


async def _invalidate_queue_caches(user_id: int) -> None:
    """Invalidate every cached view affected by queue reordering."""
    await invalidate_user_view(user_id)


async def _active_queue_positions(user_id: int, db: AsyncSession) -> dict[int, int]:
    """Return the authenticated user's active queue positions by thread ID."""
    result = await db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )
    return {thread_id: queue_position for thread_id, queue_position in result.all()}


class PositionRequest(BaseModel):
    """Schema for position update request."""

    new_position: int


@router.put("/threads/{thread_id}/position/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_position(
    request: Request,
    thread_id: int,
    position_request: PositionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to specific position.

    Args:
        request: FastAPI request object for rate limiting.
        thread_id: The ID of the thread to move.
        position_request: Request containing the new position.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with the updated thread information.

    Raises:
        HTTPException: If thread not found or position invalid.
    """
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

    logger.info(f"Thread {thread_id} current position: {thread.queue_position}")

    try:
        changes = await move_to_position(
            thread_id,
            current_user.id,
            position_request.new_position,
            db,
        )
        await db.refresh(thread)
        logger.info(f"Thread {thread_id} refreshed, new position: {thread.queue_position}")
    except ValueError as e:
        logger.error(
            f"Invalid position {position_request.new_position} for thread {thread_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            f"Error moving thread {thread_id} to position {position_request.new_position}: {e}"
        )
        raise

    if changes:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        await db.commit()
        await db.refresh(thread)
        await _invalidate_queue_caches(current_user.id)

    return await thread_to_response(thread, db)


@router.put("/threads/{thread_id}/front/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_front(
    request: Request,
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to the front.

    Args:
        request: FastAPI request object for rate limiting.
        thread_id: The ID of the thread to move.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with the updated thread information.

    Raises:
        HTTPException: If thread not found.
    """
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == current_user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    changes = await move_to_front(thread_id, current_user.id, db)
    await db.refresh(thread)

    if changes:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        await db.commit()
        await db.refresh(thread)
        await _invalidate_queue_caches(current_user.id)

    return await thread_to_response(thread, db)


@router.put("/threads/{thread_id}/back/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_back(
    request: Request,
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to the back.

    Args:
        request: FastAPI request object for rate limiting.
        thread_id: The ID of the thread to move.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with the updated thread information.

    Raises:
        HTTPException: If thread not found.
    """
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == current_user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    changes = await move_to_back(thread_id, current_user.id, db)
    await db.refresh(thread)

    if changes:
        reorder_event = Event(
            type="reorder",
            timestamp=datetime.now(UTC),
            thread_id=thread_id,
        )
        db.add(reorder_event)
        await db.commit()
        await db.refresh(thread)
        await _invalidate_queue_caches(current_user.id)

    return await thread_to_response(thread, db)


@router.post("/shuffle/", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def shuffle_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Randomize all active queue positions for the authenticated user.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Empty response with HTTP 204 status.
    """
    logger.info(
        "API shuffle_threads: user_id=%s, request_url=%s",
        current_user.id,
        request.url,
    )

    before_positions = await _active_queue_positions(current_user.id, db)
    await shuffle_queue(current_user.id, db)
    after_positions = await _active_queue_positions(current_user.id, db)
    if after_positions != before_positions:
        await _invalidate_queue_caches(current_user.id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
