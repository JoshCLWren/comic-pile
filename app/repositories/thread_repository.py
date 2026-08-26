"""Thread query construction and persistence.

All SQLAlchemy access for the ``Thread`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from app.services.queue_pagination import QueueCursor, QueueSort, build_cursor_filter, build_sort_order


async def get_thread(db: AsyncSession, thread_id: int) -> Thread | None:
    """Return a thread by primary key without ownership filtering.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.

    Returns:
        The thread, or None when it does not exist.
    """
    return await db.get(Thread, thread_id)


async def find_owned(
    db: AsyncSession, user_id: int, thread_id: int, *, for_update: bool = False
) -> Thread | None:
    """Find a thread by ID scoped to its owner.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread, or None when absent or foreign.
    """
    query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def threads_by_ids(db: AsyncSession, thread_ids: set[int]) -> dict[int, Thread]:
    """Load threads by primary key into a mapping.

    Args:
        db: Database session.
        thread_ids: Primary keys to load; an empty set returns an empty mapping.

    Returns:
        Mapping of thread ID to thread for every existing ID.
    """
    if not thread_ids:
        return {}
    result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
    return {thread.id: thread for thread in result.scalars().all()}


async def threads_for_user(db: AsyncSession, user_id: int) -> list[Thread]:
    """Load every thread owned by a user.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        All threads belonging to the user.
    """
    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    return list(result.scalars().all())


async def max_queue_position(db: AsyncSession, user_id: int) -> int:
    """Return the highest queue position held by a user's threads (0 if none).

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        The maximum queue position, or 0 when the user has no threads.
    """
    result = await db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position.desc())
    )
    return result.scalar() or 0


async def fetch_stale_threads(
    db: AsyncSession, user_id: int, cutoff_date: datetime
) -> list[Thread]:
    """Fetch active, unblocked threads whose last activity predates a cutoff.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        cutoff_date: Threads last read before this instant are stale.

    Returns:
        Stale threads ordered oldest activity first (nulls first).
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    return list(result.scalars().all())


async def fetch_queue_page(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: QueueSort,
    cursor: QueueCursor | None,
    limit: int,
) -> list[Thread]:
    """Fetch one deterministic page of a user's threads for the queue list.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Normalized case-insensitive title substring, or None.
        sort: Validated sort order key with deterministic tie-breakers.
        cursor: Decoded continuation cursor, or None for the first page.
        limit: Maximum number of threads to return.

    Returns:
        Threads in canonical page order, at most ``limit`` rows.
    """
    query = select(Thread).where(Thread.user_id == user_id)

    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    # Apply deterministic sort order with tie-breakers
    for col in build_sort_order(sort):
        query = query.order_by(col)

    # Apply opaque cursor-based pagination
    if cursor is not None:
        query = query.where(build_cursor_filter(cursor))

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def fetch_completed_threads(db: AsyncSession, user_id: int) -> list[Thread]:
    """Fetch a user's completed threads, newest created first.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Completed threads ordered by creation date descending.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "completed")
        .order_by(Thread.created_at.desc())
    )
    return list(result.scalars().all())


async def fetch_active_threads(db: AsyncSession, user_id: int) -> list[Thread]:
    """Fetch a user's active threads in queue order.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        Active threads ordered by queue position.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    return list(result.scalars().all())


async def insert_thread(db: AsyncSession, thread: Thread) -> None:
    """Persist a newly constructed thread.

    Args:
        db: Database session.
        thread: Thread instance to add to the session.
    """
    db.add(thread)


async def shift_active_queue_positions(db: AsyncSession, user_id: int) -> None:
    """Move every active thread of a user back by one queue position.

    Args:
        db: Database session.
        user_id: Owner of the threads.
    """
    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .values(queue_position=Thread.queue_position + 1)
    )


async def delete_thread(db: AsyncSession, thread: Thread) -> None:
    """Delete a thread row via the session.

    Args:
        db: Database session.
        thread: Thread instance to delete.
    """
    await db.delete(thread)


async def delete_threads_by_ids(db: AsyncSession, thread_ids: set[int], user_id: int) -> None:
    """Delete threads by ID, scoped to their owner.

    Args:
        db: Database session.
        thread_ids: Primary keys to delete.
        user_id: Owner that must own every deleted thread.
    """
    await db.execute(
        delete(Thread).where(Thread.id.in_(thread_ids)).where(Thread.user_id == user_id)
    )
