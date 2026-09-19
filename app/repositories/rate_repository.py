"""Rate pipeline query construction and persistence.

All SQLAlchemy access for the rate/undo pipeline lives here. Functions
return ORM models, plain rows/tuples, or IDs; callers (services) own
transaction boundaries.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event


async def fetch_source_roll_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
) -> int | None:
    """Return the ID of the most recent roll event selecting a thread.

    Args:
        db: Database session.
        session_id: Session to search within.
        thread_id: Thread whose originating roll event is sought.

    Returns:
        The ID of the most recent roll event selecting this thread,
        or None when no such event exists.
    """
    result = await db.execute(
        select(Event.id)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
