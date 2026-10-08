"""Queue persistence and position-map query construction.

All SQLAlchemy access for queue position maps and reorder-event writes lives
here. Functions return ORM models or plain values; callers (services) own
transactions and cache invalidation.
"""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread


async def active_queue_positions(db: AsyncSession, user_id: int) -> dict[int, int]:
    """Return the authenticated user's active queue positions by thread ID.

    Args:
        db: Database session.
        user_id: Owner of the queue.

    Returns:
        Mapping of thread ID to its active queue position for every positioned
        active thread.
    """
    result = await db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )
    return dict(result.tuples().all())


async def add_reorder_event(db: AsyncSession, thread_id: int) -> None:
    """Persist a reorder event for a moved thread.

    Args:
        db: Database session.
        thread_id: Thread whose queue position changed.
    """
    reorder_event = Event(
        type="reorder",
        timestamp=datetime.now(UTC),
        thread_id=thread_id,
    )
    db.add(reorder_event)


async def release_queue_slot(
    db: AsyncSession,
    user_id: int,
    released_position: int,
) -> dict[int, int]:
    """Close the gap a thread leaves behind when it leaves the active queue.

    Callers mark the leaving thread completed and assign it ``queue_position``
    ``0`` themselves; this closes the resulting hole by moving every remaining
    active queue member that sat behind the released slot forward one
    position. Blocked threads stay in the queue and are shifted too, because
    they still hold a slot.

    Args:
        db: Database session.
        user_id: Owner of the queue.
        released_position: Queue position the leaving thread used to hold.

    Returns:
        Changed thread IDs mapped to their previous queue positions. Every
        returned row moved forward exactly one slot, so undo can restore the
        pre-compaction queue by writing these positions back.
    """
    if released_position < 1:
        return {}

    result = await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.queue_position > released_position)
        .values(queue_position=Thread.queue_position - 1)
        .returning(Thread.id, Thread.queue_position)
    )
    # RETURNING yields post-update positions, and every matched row lost
    # exactly one slot, so the previous position is the new value plus one.
    changes: dict[int, int] = {}
    for row in result.tuples().all():
        changes[int(row[0])] = int(row[1]) + 1
    return changes
