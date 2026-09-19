"""Reading order query construction and persistence.

All SQLAlchemy access for the ``ReadingOrder`` model family lives here.
Functions return ORM models or plain values; callers (services) own
transactions and business logic.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Issue, Thread
from app.models.reading_order import ReadingOrder, ReadingOrderItem


async def list_owned_orders(db: AsyncSession, user_id: int) -> list[ReadingOrder]:
    """List reading orders owned by a user, ordered by name.

    Args:
        db: Database session.
        user_id: Owner whose reading orders are returned.

    Returns:
        Owned reading orders with items eagerly loaded, ordered by name.
    """
    result = await db.execute(
        select(ReadingOrder)
        .where(ReadingOrder.user_id == user_id)
        .options(selectinload(ReadingOrder.items))
        .order_by(ReadingOrder.name)
    )
    return list(result.scalars().all())


async def orders_containing_thread(
    db: AsyncSession, *, user_id: int, thread_id: int
) -> list[ReadingOrder]:
    """List owned reading orders that contain a thread.

    Args:
        db: Database session.
        user_id: Owner whose reading orders are returned.
        thread_id: Thread that must appear in the order's items.

    Returns:
        Distinct owned reading orders containing the thread, with items
        eagerly loaded.
    """
    result = await db.execute(
        select(ReadingOrder)
        .join(ReadingOrderItem)
        .where(
            ReadingOrder.user_id == user_id,
            ReadingOrderItem.thread_id == thread_id,
        )
        .options(selectinload(ReadingOrder.items))
        .distinct()
    )
    return list(result.scalars().all())


async def threads_by_ids(db: AsyncSession, thread_ids: set[int]) -> dict[int, Thread]:
    """Load threads by primary key into a mapping with one query.

    Args:
        db: Database session.
        thread_ids: Primary keys to load; an empty set returns an empty mapping.

    Returns:
        Mapping of thread ID to thread for every existing ID.
    """
    if not thread_ids:
        return {}
    result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
    return {thread.id: thread for thread in result.scalars()}


async def read_issue_keys(db: AsyncSession, thread_ids: set[int]) -> set[tuple[int, str]]:
    """Load ``(thread_id, issue_number)`` pairs marked read, in one query.

    Args:
        db: Database session.
        thread_ids: Thread IDs whose read issues are relevant; an empty set
            returns an empty set without querying.

    Returns:
        Set of ``(thread_id, issue_number)`` pairs with status ``"read"``.
    """
    if not thread_ids:
        return set()
    result = await db.execute(
        select(Issue.thread_id, Issue.issue_number).where(
            Issue.thread_id.in_(thread_ids),
            Issue.status == "read",
        )
    )
    return {(row[0], row[1]) for row in result.all()}


async def get_owned_order(
    db: AsyncSession, *, order_id: int, user_id: int
) -> ReadingOrder | None:
    """Return one reading order owned by a user, or ``None``.

    Args:
        db: Database session.
        order_id: Primary key of the reading order.
        user_id: Owner that must own the reading order.

    Returns:
        The owned reading order, or ``None`` when absent or foreign.
    """
    result = await db.execute(
        select(ReadingOrder).where(
            ReadingOrder.id == order_id,
            ReadingOrder.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_owned_thread(
    db: AsyncSession, *, thread_id: int, user_id: int
) -> Thread | None:
    """Return one thread owned by a user, or ``None``.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.
        user_id: Owner that must own the thread.

    Returns:
        The owned thread, or ``None`` when absent or foreign.
    """
    result = await db.execute(
        select(Thread).where(
            Thread.id == thread_id,
            Thread.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_items(db: AsyncSession, order_id: int) -> list[ReadingOrderItem]:
    """List items of a reading order ordered by position.

    Args:
        db: Database session.
        order_id: Reading order whose items are returned.

    Returns:
        Items of the reading order ordered by position.
    """
    result = await db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order_id)
        .order_by(ReadingOrderItem.position)
    )
    return list(result.scalars().all())


async def count_items(db: AsyncSession, order_id: int) -> int:
    """Count items of a reading order with SQL ``count``.

    Args:
        db: Database session.
        order_id: Reading order whose items are counted.

    Returns:
        Number of items in the reading order.
    """
    result = await db.execute(
        select(func.count())
        .select_from(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order_id)
    )
    return int(result.scalar_one())
