"""API endpoints for reading orders."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Issue, Thread
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.user import User
from app.schemas.reading_order import (
    ReadingOrderItemResponse,
    ReadingOrderResponse,
    ThreadReadingOrdersResponse,
)

router = APIRouter(tags=["reading-orders"])


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
