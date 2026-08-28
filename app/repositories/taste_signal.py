"""Data access for Taste Bank signals.

Isolates every SQLAlchemy query so routers stay free of schema imports and
execute calls, satisfying the router-layering conformance contract.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.taste_signal import TasteSignal


async def get_user_signals(
    db: AsyncSession,
    user_id: int,
) -> list[TasteSignal]:
    """Return every Taste Bank signal owned by ``user_id``, sorted canonically.

    Args:
        db: Async database session.
        user_id: Database primary key of the owning user.

    Returns:
        A list of persisted ``TasteSignal`` rows ordered by signal type
        then external key.
    """
    result = await db.execute(
        select(TasteSignal)
        .where(TasteSignal.user_id == user_id)
        .order_by(TasteSignal.signal_type, TasteSignal.external_key)
    )
    return list(result.scalars().all())


async def get_signal(
    db: AsyncSession,
    user_id: int,
    signal_type: str,
    external_key: str,
) -> TasteSignal | None:
    """Return the unique Taste Bank signal for the composite key, or ``None``.

    Args:
        db: Async database session.
        user_id: Database primary key of the owning user.
        signal_type: Category slug of the signal.
        external_key: Stable normalized key of the external feature.

    Returns:
        The matching ``TasteSignal`` row, or ``None`` when absent.
    """
    result = await db.execute(
        select(TasteSignal).where(
            TasteSignal.user_id == user_id,
            TasteSignal.signal_type == signal_type,
            TasteSignal.external_key == external_key,
        )
    )
    return result.scalar_one_or_none()


async def upsert_signal(
    db: AsyncSession,
    user_id: int,
    signal_type: str,
    external_key: str,
    display_name: str,
    verdict: str,
    now,
) -> TasteSignal:
    """Record a user verdict for a Taste Bank signal.

    When no row already exists for the ``(user_id, signal_type, external_key)``
    composite key a new row is inserted with zero inferred evidence columns so
    the explicit verdict survives even when the source data has disappeared.

    Args:
        db: Async database session.
        user_id: Database primary key of the owning user.
        signal_type: Category slug of the signal.
        external_key: Stable normalized key of the external feature.
        display_name: Human-readable label shown in prompts.
        verdict: Stable user decision (``confirmed``, ``sometimes``, or
            ``rejected``).
        now: Timezone-aware UTC timestamp to record as ``verdict_at``.

    Returns:
        The persisted ``TasteSignal`` row after the verdict has been applied.
    """
    signal = await get_signal(db, user_id, signal_type, external_key)

    if signal is None:
        signal = TasteSignal(
            user_id=user_id,
            signal_type=signal_type,
            external_key=external_key,
            display_name=display_name,
            user_verdict=verdict,
            verdict_at=now,
            first_observed_at=now,
            last_observed_at=now,
            evidence_count=0,
            distinct_thread_count=0,
        )
        db.add(signal)
    else:
        signal.user_verdict = verdict
        signal.verdict_at = now

    return signal