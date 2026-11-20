"""Reading order business logic.

Routers validate input and map domain errors to HTTP; all enrichment,
placement, and persistence orchestration lives here. Query construction
lives in ``app.repositories.reading_order_repository``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_order import ReadingOrderItem
from app.repositories import reading_order_repository
from app.schemas.reading_order import (
    ReadingOrderItemResponse,
    ReadingOrderListResponse,
    ReadingOrderResponse,
    ReadingOrderSummary,
    ThreadReadingOrdersResponse,
)
from app.services.errors import NotFoundError
from app.services.reading_order_placement import apply_insert


async def list_reading_orders(
    db: AsyncSession, *, user_id: int
) -> ReadingOrderListResponse:
    """List reading orders owned by the current user, ordered by name.

    Args:
        db: Database session.
        user_id: Owner whose reading orders are returned.

    Returns:
        Compact summaries of the user's reading orders.
    """
    orders = await reading_order_repository.list_owned_orders(db, user_id)
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


async def get_thread_reading_orders(
    db: AsyncSession, *, user_id: int, thread_id: int
) -> ThreadReadingOrdersResponse:
    """Get owned reading orders containing a thread with batch enrichment.

    Threads and read-issue flags for every item across all matching orders
    are resolved with two batched queries instead of per-item selects.

    Args:
        db: Database session.
        user_id: Owner whose reading orders are returned.
        thread_id: Thread that must appear in each returned order.

    Returns:
        Reading orders containing the thread with enriched item responses.
    """
    orders = await reading_order_repository.orders_containing_thread(
        db, user_id=user_id, thread_id=thread_id
    )

    thread_ids: set[int] = set()
    for order in orders:
        for item in order.items:
            thread_ids.add(item.thread_id)

    threads_by_id = await reading_order_repository.threads_by_ids(db, thread_ids)
    read_keys = await reading_order_repository.read_issue_keys(db, thread_ids)

    order_responses: list[ReadingOrderResponse] = []
    for order in orders:
        items_sorted = sorted(order.items, key=lambda i: i.position)
        item_responses: list[ReadingOrderItemResponse] = []
        completed = 0
        for item in items_sorted:
            is_read = (
                item.issue_number is not None
                and (item.thread_id, item.issue_number) in read_keys
            )
            if is_read:
                completed += 1
            thread = threads_by_id.get(item.thread_id)
            item_responses.append(
                ReadingOrderItemResponse(
                    thread_id=item.thread_id,
                    thread_title=thread.title if thread else f"Thread {item.thread_id}",
                    position=item.position,
                    issue_number=item.issue_number,
                    is_read=is_read,
                )
            )
        order_id = order.id
        order_name = order.name
        order_description = order.description
        order_responses.append(
            ReadingOrderResponse(
                id=order_id,
                name=order_name,
                description=order_description,
                total_items=len(items_sorted),
                completed_items=completed,
                items=item_responses,
            )
        )

    return ThreadReadingOrdersResponse(reading_orders=order_responses)


async def insert_reading_order_item(
    db: AsyncSession,
    *,
    user_id: int,
    reading_order_id: int,
    thread_id: int,
    position: int,
) -> tuple[int, int, int, int]:
    """Insert a thread into a reading order at a position.

    Shifts existing items at or after the target position to make room. If
    the thread already belongs to the reading order, it is moved to the
    target position instead of being duplicated. The item count is resolved
    with SQL ``count`` rather than loading every row.

    Args:
        db: Database session.
        user_id: Owner of both the reading order and the thread.
        reading_order_id: Target reading order identifier.
        thread_id: Thread being inserted or moved.
        position: Desired 1-based position after the operation.

    Returns:
        Tuple of ``(reading_order_id, thread_id, position, total_items)``
        where ``total_items`` comes from SQL ``count``.

    Raises:
        NotFoundError: When the reading order or thread is missing or foreign.
    """
    order = await reading_order_repository.get_owned_order(
        db, order_id=reading_order_id, user_id=user_id
    )
    if order is None:
        raise NotFoundError(f"Reading order {reading_order_id} not found")

    thread = await reading_order_repository.get_owned_thread(
        db, thread_id=thread_id, user_id=user_id
    )
    if thread is None:
        raise NotFoundError(f"Thread {thread_id} not found")

    existing = await reading_order_repository.list_items(db, reading_order_id)

    target_pos = position
    apply_insert(list(existing), thread_id, target_pos)

    already_present = any(item.thread_id == thread_id for item in existing)
    if not already_present:
        db.add(
            ReadingOrderItem(
                reading_order_id=reading_order_id,
                thread_id=thread_id,
                position=target_pos,
            )
        )
    await db.commit()

    total = await reading_order_repository.count_items(db, reading_order_id)
    return (reading_order_id, thread_id, target_pos, total)
