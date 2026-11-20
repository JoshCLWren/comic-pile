"""API endpoints for reading orders.

Reading orders are a legacy compatibility surface. The canonical reader
order is the continuity plan (``ContinuityPlan``); see
``docs/READING_PLAN_CANONICAL_MODEL.md``. These endpoints remain readable
and adoptable but are not the source of truth for new ordering intent.

Thin routing layer: authentication, request/response schema validation, and
HTTP status mapping. Business logic lives in
``app/services/reading_order_service.py``; query construction lives in
``app/repositories/reading_order_repository.py``.
"""


from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_order import (
    ThreadReadingOrdersResponse,
)
from app.services import reading_order_service
from app.services.errors import NotFoundError, ServiceError

router = APIRouter(tags=["reading-orders"])

_ERROR_STATUS: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
}


def _map_service_error(exc: ServiceError) -> HTTPException:
    """Translate a domain error into its HTTP equivalent.

    Args:
        exc: Domain error raised by a service function.

    Returns:
        HTTPException carrying the mapped status code and client-safe detail.
    """
    return HTTPException(status_code=_ERROR_STATUS[type(exc)], detail=exc.detail)


@router.get("/api/v1/threads/{thread_id}/reading-orders")
async def get_thread_reading_orders(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadReadingOrdersResponse:
    """Get reading orders that contain this thread."""
    return await reading_order_service.get_thread_reading_orders(
        db, user_id=current_user.id, thread_id=thread_id
    )


class InsertReadingOrderItemRequest(BaseModel):
    """Request schema for inserting an item into a reading order."""

    thread_id: int = Field(..., gt=0)
    position: int = Field(..., ge=1)


class InsertReadingOrderItemResponse(BaseModel):
    """Response schema for inserting an item into a reading order."""

    reading_order_id: int
    thread_id: int
    position: int
    total_items: int
