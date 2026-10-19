"""Public Queue positions without rewriting persistence ordering."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from app.repositories.queue_ordering import dense_positions
from app.services.reading_eligibility_service import get_execution_eligibility


async def display_positions(db: AsyncSession, user_id: int) -> dict[int, int]:
    """Return the reader's current dense Queue positions."""
    eligibility = await get_execution_eligibility(db, user_id)
    return await dense_positions(db, user_id, eligibility)


async def display_position(db: AsyncSession, thread: Thread) -> int:
    """Return a current Queue ordinal, or zero for a thread outside the Queue."""
    positions = await display_positions(db, thread.user_id)
    return positions.get(thread.id, 0)
