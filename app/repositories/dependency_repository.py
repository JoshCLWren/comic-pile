"""Dependency query construction and persistence.

All SQLAlchemy access for the ``Dependency`` model family lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency


async def get_dependencies_by_user_and_note_prefix(
    db: AsyncSession, user_id: int, note_prefix: str
) -> list[Dependency]:
    """Return dependencies for a user with note starting with given prefix.

    Args:
        db: Database session.
        user_id: Owner of the dependencies.
        note_prefix: Prefix to match on the note field.

    Returns:
        List of dependencies matching the criteria.
    """
    result = await db.execute(
        select(Dependency).where(
            Dependency.user_id == user_id, Dependency.note.like(f"{note_prefix}%")
        )
    )
    return list(result.scalars().all())


async def delete_dependencies_by_user_and_note_prefix(
    db: AsyncSession, user_id: int, note_prefix: str
) -> None:
    """Delete dependencies for a user with note starting with given prefix.

    Args:
        db: Database session.
        user_id: Owner of the dependencies.
        note_prefix: Prefix to match on the note field.
    """
    await db.execute(
        delete(Dependency).where(
            Dependency.user_id == user_id, Dependency.note.like(f"{note_prefix}%")
        )
    )