"""Async repository tests for inferred Taste Bank persistence (issue #1745).

These cover the verdict-preserving persistence path that the pure unit tests
do not reach: a recomputed inferred signal must refresh derived columns while
leaving an explicit user verdict untouched, and confirmed/sometimes/rejected
verdicts must survive recomputation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.taste_signal import TasteSignal
from app.models.user import User
from app.repositories import taste_signal as taste_signal_repository
from app.services.taste_inference import InferredSignal

pytestmark = pytest.mark.asyncio


async def _seed_signal(
    async_db: AsyncSession,
    user_id: int,
    user_verdict: str | None,
) -> TasteSignal:
    signal = TasteSignal(
        user_id=user_id,
        signal_type="creator",
        external_key="creator:writer:alan-moore",
        display_name="Alan Moore",
        affinity_estimate=0.2,
        confidence=0.2,
        evidence_count=1,
        distinct_thread_count=1,
        user_verdict=user_verdict,
    )
    async_db.add(signal)
    await async_db.commit()
    await async_db.refresh(signal)
    return signal


@pytest.mark.parametrize("verdict", ["confirmed", "sometimes", "rejected"])
async def test_apply_inferred_signal_preserves_explicit_verdict(
    async_db: AsyncSession,
    default_user: User,
    verdict: str,
) -> None:
    signal = await _seed_signal(async_db, default_user.id, verdict)

    inferred = InferredSignal(
        affinity_estimate=0.9,
        confidence=0.95,
        evidence_count=12,
        distinct_thread_count=9,
    )
    updated = await taste_signal_repository.apply_inferred_signal(
        async_db,
        user_id=default_user.id,
        signal_type="creator",
        external_key="creator:writer:alan-moore",
        display_name="Alan Moore",
        inferred=inferred,
        now=datetime.now(UTC),
    )
    await async_db.commit()
    await async_db.refresh(updated)

    assert updated.user_verdict == verdict
    assert updated.affinity_estimate == 0.9
    assert updated.confidence == 0.95
    assert updated.evidence_count == 12
    assert updated.distinct_thread_count == 9


async def test_apply_inferred_signal_creates_row_without_verdict(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    inferred = InferredSignal(
        affinity_estimate=0.5,
        confidence=0.7,
        evidence_count=4,
        distinct_thread_count=3,
    )
    await taste_signal_repository.apply_inferred_signal(
        async_db,
        user_id=default_user.id,
        signal_type="character",
        external_key="character:42",
        display_name="Swamp Thing",
        inferred=inferred,
        now=datetime.now(UTC),
    )
    await async_db.commit()

    result = await async_db.execute(
        select(TasteSignal).where(
            TasteSignal.user_id == default_user.id,
            TasteSignal.signal_type == "character",
            TasteSignal.external_key == "character:42",
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_verdict is None
    assert row.affinity_estimate == 0.5
    assert row.first_observed_at is not None


async def test_inferred_only_signal_has_no_verdict_written(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    inferred = InferredSignal(
        affinity_estimate=-0.8,
        confidence=0.9,
        evidence_count=10,
        distinct_thread_count=8,
    )
    await taste_signal_repository.apply_inferred_signal(
        async_db,
        user_id=default_user.id,
        signal_type="team",
        external_key="team:7",
        display_name="The League",
        inferred=inferred,
        now=datetime.now(UTC),
    )
    await async_db.commit()

    result = await async_db.execute(
        select(TasteSignal).where(
            TasteSignal.user_id == default_user.id,
            TasteSignal.signal_type == "team",
            TasteSignal.external_key == "team:7",
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_verdict is None
    assert row.affinity_estimate == -0.8
