"""Authenticated Reading Boundaries explanation endpoints.

Thin routing layer: authentication, request validation, one service call, and
HTTP status mapping. Eligibility and label resolution live in
``app/services/reading_boundary_service.py`` and ``app/repositories/``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_boundary import (
    ReadingBoundaryBatchRequest,
    ReadingBoundaryBatchResponse,
    ReadingBoundaryExplanation,
)
from app.services import reading_boundary_service
from app.services.errors import NotFoundError, ServiceError

router = APIRouter(prefix="/reading-boundaries", tags=["reading-boundaries"])

_ERROR_STATUS: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
}


def _map_service_error(exc: ServiceError) -> HTTPException:
    """Translate a domain error into its HTTP equivalent.

    Args:
        exc: Domain error raised by the boundary service.

    Returns:
        HTTPException carrying the mapped status code and client-safe detail.
    """
    return HTTPException(status_code=_ERROR_STATUS[type(exc)], detail=exc.detail)


@router.post("", response_model=ReadingBoundaryBatchResponse)
async def get_reading_boundary_batch(
    payload: ReadingBoundaryBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingBoundaryBatchResponse:
    """Explain several owned series in one canonical eligibility snapshot.

    Args:
        payload: Owned Thread identifiers to explain.
        current_user: Authenticated reader making the request.
        db: Database session for the request.

    Returns:
        Explanations keyed by Thread identifier.

    Raises:
        HTTPException: With status 404 when a Thread is absent or foreign.
    """
    try:
        return await reading_boundary_service.get_reading_boundary_explanations(
            db, user_id=current_user.id, thread_ids=payload.thread_ids
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get("/{thread_id}", response_model=ReadingBoundaryExplanation)
async def get_reading_boundary(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingBoundaryExplanation:
    """Explain one owned series through the canonical Option E result.

    Args:
        thread_id: Owned Thread to explain.
        current_user: Authenticated reader making the request.
        db: Database session for the request.

    Returns:
        Named waiting Issues, live blockers, history, and editor targets.

    Raises:
        HTTPException: With status 404 when the Thread is absent or foreign.
    """
    try:
        return await reading_boundary_service.get_reading_boundary_explanation(
            db, user_id=current_user.id, thread_id=thread_id
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
