"""API endpoints for reading orders.

Reading orders are a legacy compatibility surface. The canonical reader
order is the continuity plan (``ContinuityPlan``); see
``docs/READING_PLAN_CANONICAL_MODEL.md``. These endpoints remain readable
and adoptable but are not the source of truth for new ordering intent.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Issue, Thread
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.user import User
from app.services.reading_order_placement import apply_insert
from app.schemas.reading_order import (
    ReadingOrderItemResponse,
    ReadingOrderListResponse,
    ReadingOrderResponse,
    ReadingOrderSummary,
    ThreadReadingOrdersResponse,
)

router = APIRouter(tags=["reading-orders"])


@router.get("/api/v1/reading-orders/")
async def list_reading_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadingOrderListResponse:
    """List reading orders owned by the current user, ordered by name."""
    result = await db.execute(
        select(ReadingOrder)
        .where(ReadingOrder.user_id == current_user.id)
        .options(selectinload(ReadingOrder.items))
        .order_by(ReadingOrder.name)
    )
    orders = result.scalars().all()

    summaries = [
        ReadingOrderSummary(
            id=order.id,
            name=order.name,
            description=order.description,
            total_items=len(order.items),
        )
        for order in orders
    ]
    return ReadingOrderListResponse(reading_orders=summaries)


@router.get("/api/v1/threads/{thread_id}/reading-orders")
async def get_thread_reading_orders(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadReadingOrdersResponse:
    """Get reading orders that contain this thread."""
    result = await db.execute(
        select(ReadingOrder)
        .join(ReadingOrderItem)
        .where(
            ReadingOrder.user_id == current_user.id,
            ReadingOrderItem.thread_id == thread_id,
        )
        .options(selectinload(ReadingOrder.items))
        .distinct()
    )
    orders = result.scalars().all()

    order_responses = []
    for order in orders:
        items_sorted = sorted(order.items, key=lambda i: i.position)
        item_responses = []
        completed = 0
        for item in items_sorted:
            issue_result = await db.execute(
                select(Issue).where(
                    Issue.thread_id == item.thread_id,
                    Issue.status == "read",
                )
            )
            read_issues = issue_result.scalars().all()
            is_read = len(read_issues) > 0

            thread_result = await db.execute(
                select(Thread).where(Thread.id == item.thread_id)
            )
            thread = thread_result.scalar_one_or_none()

            if is_read:
                completed += 1

            item_responses.append(
                ReadingOrderItemResponse(
                    thread_id=item.thread_id,
                    thread_title=thread.title if thread else f"Thread {item.thread_id}",
                    position=item.position,
                    issue_number=item.issue_number,
                    is_read=is_read,
                )
            )

        order_responses.append(
            ReadingOrderResponse(
                id=order.id,
                name=order.name,
                description=order.description,
                total_items=len(items_sorted),
                completed_items=completed,
                items=item_responses,
            )
        )

    return ThreadReadingOrdersResponse(reading_orders=order_responses)


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
    order = (
        await db.execute(
            select(ReadingOrder).where(
                ReadingOrder.id == reading_order_id,
                ReadingOrder.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Reading order {reading_order_id} not found")

    thread = (
        await db.execute(
            select(Thread).where(
                Thread.id == payload.thread_id,
                Thread.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=404, detail=f"Thread {payload.thread_id} not found")

    existing = (
        await db.execute(
            select(ReadingOrderItem)
            .where(ReadingOrderItem.reading_order_id == reading_order_id)
            .order_by(ReadingOrderItem.position)
        )
    ).scalars().all()

    target_pos = payload.position
    apply_insert(list(existing), payload.thread_id, target_pos)

    already_present = any(item.thread_id == payload.thread_id for item in existing)
    if not already_present:
        db.add(
            ReadingOrderItem(
                reading_order_id=reading_order_id,
                thread_id=payload.thread_id,
                position=target_pos,
            )
        )
    await db.commit()

    result = await db.execute(
        select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id == reading_order_id)
    )
    total = len(result.scalars().all())

    return InsertReadingOrderItemResponse(
        reading_order_id=reading_order_id,
        thread_id=payload.thread_id,
        position=payload.position,
        total_items=total,
    )