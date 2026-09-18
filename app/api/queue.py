"""Queue API routes.

Thin routing layer: authentication, request/response schema validation, HTTP
status mapping, and rate limiting. Business logic lives in
``app/services/queue_service.py``; persistence lives in
``app/repositories/queue_repository.py`` and ``comic_pile.queue``.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models.user import User
from app.schemas import ThreadResponse
from app.services.errors import InvalidRequestError, NotFoundError, ServiceError
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)


router = APIRouter()

_ERROR_STATUS: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidRequestError: status.HTTP_400_BAD_REQUEST,
}


def _map_service_error(exc: ServiceError) -> HTTPException:
    """Translate a domain error into its HTTP equivalent.

    Args:
        exc: Domain error raised by a queue service method.

    Returns:
        HTTPException carrying the mapped status code and client-safe detail.
    """
    return HTTPException(status_code=_ERROR_STATUS[type(exc)], detail=exc.detail)


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
        "API move_thread_position: thread_id=%d, user_id=%d, "
        "new_position=%d, request_url=%s",
        thread_id,
        current_user.id,
        position_request.new_position,
        request.url,
    )
    try:
        service = QueueService(db)
        return await service.move_to_position(
            current_user.id, thread_id, position_request.new_position
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


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
    try:
        service = QueueService(db)
        return await service.move_to_front(current_user.id, thread_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


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
    try:
        service = QueueService(db)
        return await service.move_to_back(current_user.id, thread_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


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
    logger.info("API shuffle_threads: user_id=%s, request_url=%s", current_user.id, request.url)
    try:
        service = QueueService(db)
        await service.shuffle(current_user.id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)