"""Queue persistence and position-map query construction.

All SQLAlchemy access for queue position maps and reorder-event writes lives
here. Functions return ORM models or plain values; callers (services) own
transactions and cache invalidation.
"""

from datetime import UTC, datetime

from sqlalchemy import select
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