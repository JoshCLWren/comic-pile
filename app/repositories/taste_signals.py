"""Query construction and persistence for Taste Bank signals.

This repository owns every SQLAlchemy query for the ``taste_signals`` table so
routers and services stay free of query construction per the house layering
standard. It returns ORM models only; response shaping lives in services.
"""

from __future__ import annotations

from datetime import UTC, datetime

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


async def get_owned(
    db: AsyncSession, *, signal_id: int, user_id: int
) -> TasteSignal | None:
    """Return one signal by id scoped to its owner.

    Args:
        db: Async database session.
        signal_id: Primary key of the signal.
        user_id: Authenticated owner id.

    Returns:
        The owned signal, or ``None`` when missing or foreign.
    """
    result = await db.execute(
        select(TasteSignal).where(
            TasteSignal.id == signal_id,
            TasteSignal.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def commit(db: AsyncSession) -> None:
    """Commit the session after repository mutations.

    Args:
        db: Async database session.
    """
    await db.commit()


def utc_now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware UTC datetime.
    """
    return datetime.now(UTC)
