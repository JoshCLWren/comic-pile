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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_order import (
    ReadingOrderListResponse,
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


@router.get("/api/v1/reading-orders/")
async def list_reading_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadingOrderListResponse:
    """List reading orders owned by the current user, ordered by name."""
    return await reading_order_service.list_reading_orders(db, user_id=current_user.id)


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


@router.post(
    "/api/v1/reading-orders/{reading_order_id}/items",
    response_model=InsertReadingOrderItemResponse,
    status_code=201,
)
async def insert_reading_order_item(
    reading_order_id: int,
    payload: InsertReadingOrderItemRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InsertReadingOrderItemResponse:
    """Insert a thread into a reading order at a specified position.

    Shifts existing items at or after the target position to make room. If the
    thread already belongs to the reading order, it is moved to the target
    position instead of being duplicated.
    """
    try:
        resolved_order_id, resolved_thread_id, resolved_position, total = (
            await reading_order_service.insert_reading_order_item(
                db,
                user_id=current_user.id,
                reading_order_id=reading_order_id,
                thread_id=payload.thread_id,
                position=payload.position,
            )
        )
    except ServiceError as exc:
        raise _map_service_error(exc) from exc

    return InsertReadingOrderItemResponse(
        reading_order_id=resolved_order_id,
        thread_id=resolved_thread_id,
        position=resolved_position,
        total_items=total,
    )
