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
from app.schemas.reading_boundary import ReadingBoundaryExplanationV2
from app.services import reading_boundary_service
from app.services.errors import NotFoundError, ServiceError

v2_router = APIRouter(prefix="/reading-boundaries", tags=["reading-boundaries-v2"])

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


@v2_router.get("/{thread_id}", response_model=ReadingBoundaryExplanationV2)
async def get_reading_boundary_v2(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingBoundaryExplanationV2:
    """Explain live canonical constraints without querying historical rows."""
    try:
        result = await reading_boundary_service.get_reading_boundary_explanation(
            db,
            user_id=current_user.id,
            thread_id=thread_id,
            include_historical=False,
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
    return ReadingBoundaryExplanationV2.model_validate(
        result.model_dump(exclude={"historical"})
    )
