"""Query construction and persistence for Taste Bank signals.

This repository owns every SQLAlchemy query for the ``taste_signals`` table so
routers and services stay free of query construction per the house layering
standard. It returns ORM models only; response shaping lives in services.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.taste_signal import TasteSignal


async def list_for_user(db: AsyncSession, user_id: int) -> list[TasteSignal]:
    """Return every taste signal owned by one user.

    Args:
        db: Async database session.
        user_id: Owning user id.

    Returns:
        All signals for the user, newest first for stable discovery ranking.
    """
    result = await db.execute(
        select(TasteSignal)
        .where(TasteSignal.user_id == user_id)
        .order_by(TasteSignal.updated_at.desc(), TasteSignal.id.desc())
    )
    return list(result.scalars().all())


async def commit(db: AsyncSession) -> None:
    """Commit the session after repository mutations.

    Args:
        db: Async database session.
    """
    await db.commit()
