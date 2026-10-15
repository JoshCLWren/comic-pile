"""Preferences query construction and persistence.

All SQLAlchemy access for the ``UserPreferences`` model family lives here.
Functions return ORM models or plain values; callers (services) own
transaction boundaries.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserPreferences


async def get_theme(db: AsyncSession, user_id: int) -> str | None:
    """Return a user's persisted theme id, or None when no row exists.

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.

    Returns:
        The persisted theme id, or None when the user has no preference row.
    """
    result = await db.execute(
        select(UserPreferences.theme).where(UserPreferences.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def upsert_theme(db: AsyncSession, user_id: int, theme: str) -> str:
    """Atomically insert or update a user's theme and return the persisted value.

    The upsert avoids a select-then-insert race: overlapping first-time writes
    (issue #1872) conflict on the unique ``user_id`` and resolve as updates
    instead of surfacing a unique-violation failure.

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.
        theme: Theme id to persist when the row is inserted or updated.

    Returns:
        The persisted theme value.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        pg_insert(UserPreferences)
        .values(user_id=user_id, theme=theme, updated_at=now)
        .on_conflict_do_update(
            index_elements=[UserPreferences.__table__.c.user_id],
            set_={"theme": theme, "updated_at": now},
        )
        .returning(UserPreferences.theme)
    )
    return result.scalar_one()


async def seed_default_theme(db: AsyncSession, user_id: int, default_theme: str) -> str:
    """Seed the default theme row when absent, then return the persisted theme.

    An existing row is never clobbered; a missing row is inserted with
    ``on_conflict_do_nothing`` before the persisted value is read back.

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.
        default_theme: Theme id to persist only when the row does not exist.

    Returns:
        The persisted theme value.
    """
    now = datetime.now(UTC)
    await db.execute(
        pg_insert(UserPreferences)
        .values(user_id=user_id, theme=default_theme, updated_at=now)
        .on_conflict_do_nothing(index_elements=[UserPreferences.__table__.c.user_id])
    )
    result = await db.execute(
        select(UserPreferences.theme).where(UserPreferences.user_id == user_id)
    )
    return result.scalar_one()

async def get_excluded_tag_ids(db: AsyncSession, user_id: int) -> list[int]:
    """Return a user's persisted excluded tag IDs (empty when unset).

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.

    Returns:
        List of excluded tag IDs, or an empty list when no row exists.
    """
    result = await db.execute(
        select(UserPreferences.excluded_tag_ids).where(UserPreferences.user_id == user_id)
    )
    value = result.scalar_one_or_none()
    if value is None:
        return []
    return [int(tag_id) for tag_id in value]


async def set_excluded_tag_ids(db: AsyncSession, user_id: int, tag_ids: list[int]) -> list[int]:
    """Persist the complete excluded tag ID list for a user.

    Overlapping first-time writes resolve as updates on the unique user_id.

    Args:
        db: Database session.
        user_id: Owning user id for the preference row.
        tag_ids: Tag IDs to persist (duplicates are removed).

    Returns:
        The persisted excluded tag ID list.
    """
    normalized = sorted({int(tag_id) for tag_id in tag_ids})
    now = datetime.now(UTC)
    result = await db.execute(
        pg_insert(UserPreferences)
        .values(user_id=user_id, excluded_tag_ids=normalized, updated_at=now)
        .on_conflict_do_update(
            index_elements=[UserPreferences.__table__.c.user_id],
            set_={"excluded_tag_ids": normalized, "updated_at": now},
        )
        .returning(UserPreferences.excluded_tag_ids)
    )
    value = result.scalar_one()
    if value is None:
        return []
    return [int(tag_id) for tag_id in value]
