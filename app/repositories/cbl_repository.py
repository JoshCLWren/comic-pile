"""CBL query construction and persistence.

All SQLAlchemy access for the ``CBL`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource


async def list_cbl_sources(db: AsyncSession) -> list[tuple[int, str]]:
    """List all CBL sources with their id and name.
    
    Args:
        db: Database session.
        
    Returns:
        List of tuples containing (id, name) for each CBL source.
    """
    result = await db.execute(
        select(CBLSource.id, CBLSource.repository.label("name"))
    )
    return [(row.id, row.name) for row in result]