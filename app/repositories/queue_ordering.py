"""Reader-scoped display positions, independent of stored ordering keys."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from app.services.reading_eligibility_service import ReadingEligibilitySnapshot


async def dense_positions(
    db: AsyncSession,
    user_id: int,
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> dict[int, int]:
    """Return whole-Queue ordinals before search, pagination, or roll exclusions."""
    from app.services.queue_pagination import build_sort_order

    ids = await db.scalars(
        select(Thread.id)
        .where(Thread.user_id == user_id, Thread.status == "active")
        .order_by(*build_sort_order("position", eligibility))
    )
    return {thread_id: index for index, thread_id in enumerate(ids, start=1)}
