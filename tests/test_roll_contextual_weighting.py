"""Acceptance regression for contextual bandwidth weighting (issue #1720).

Phase 3 acceptance contract for wiring ``build_candidate_weights`` (bandwidth)
into the Roll selection path inside the already-bounded die pool:

- ``light`` bandwidth favors lower-effort candidates.
- ``deep`` bandwidth gently favors higher-effort candidates while never
  excluding light reads (all weights remain strictly positive).
- ``balanced``/default bandwidth stays exactly neutral, preserving the legacy
  momentum-selection behavior byte-for-byte.
- Unknown effort stays exactly neutral for any bandwidth.
- Selection always lands inside the bounded pool.
- The ``random`` intent bypasses all contextual weighting.
- Persisted candidate weights and reason codes match the actual selection
  inputs (the #1718 records weights/reason-codes scope).

Depends on closed #1712/#1714/#1715/#1717; this file is the acceptance
regression for the final integration.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models import Event, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    ThreadExternalSeriesMapping,
)
from app.models.recommendation_context import RecommendationContext
from app.services.bandwidth_selection import select_bandwidth_weighted
from comic_pile.recommendation_selection import SelectionMode


async def _add_thread(
    db: AsyncSession,
    user: User,
    title: str,
    *,
    queue_position: int,
) -> Thread:
    """Create one active reading thread for the user."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _confirm_series_era(
    db: AsyncSession, thread: Thread, cover_date: str
) -> None:
    """Attach confirmed series metadata so era-prior effort is derived."""
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=f"4050-{thread.id}",
        metadata_json={"cover_date": cover_date},
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await db.flush()


async def _add_observed_effort(
    db: AsyncSession,
    thread: Thread,
    *,
    minutes: float,
    count: int,
) -> None:
    """Seed ``count`` linked roll -> rate observations of ``minutes`` each."""
    base = datetime.now(UTC) - timedelta(days=7)
    for index in range(count):
        rolled_at = base + timedelta(days=index)
        roll_event = Event(
            type="roll",
            selected_thread_id=thread.id,
            die=8,
            result=1,
            selection_method="random",
            timestamp=rolled_at,
        )
        db.add(roll_event)
        await db.flush()
        rate_event = Event(
            type="rate",
            thread_id=thread.id,
            source_roll_event_id=roll_event.id,
            rating=4.0,
            issues_read=1,
            die=8,
            die_after=8,
            timestamp=rolled_at + timedelta(minutes=minutes),
        )
        db.add(rate_event)
        await db.flush()


def _pool_rows(threads: list[Thread]) -> list[object]:
    """Build production-shaped bounded pool rows ``(Thread, unread, num)``."""
    return [(thread, 5, None) for thread in threads]


def _weights_by_candidate(selection) -> dict[int, float]:
    """Map candidate id to its combined weight from a selection result."""
    return {entry.candidate_id: entry.weight for entry in selection.weights}


def _factors_by_candidate(selection) -> dict[int, tuple[str, ...]]:
    """Map candidate id to its reason codes from a selection result."""
    return {entry.candidate_id: entry.factors for entry in selection.weights}


@pytest.mark.asyncio
async def test_balanced_bandwidth_stays_neutral(
    async_db: AsyncSession, default_user: User
) -> None:
    """Balanced bandwidth contributes an exactly neutral 1.0 factor."""
    light = await _add_thread(
        async_db, default_user, "Classic Light", queue_position=1
    )
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(
        async_db, default_user, "Heavy Read", queue_position=2
    )
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    selection = await select_bandwidth_weighted(
        async_db,
        bounded_rows=_pool_rows([light, heavy]),
        user_id=default_user.id,
        bandwidth="balanced",
        intent="balanced",
    )

    weights = _weights_by_candidate(selection)
    assert weights[light.id] == pytest.approx(1.0)
    assert weights[heavy.id] == pytest.approx(1.0)
    assert selection.weights_applied is False
    # No bandwidth reason code is persisted for an exactly neutral draw.
    assert _factors_by_candidate(selection)[light.id] == ()


@pytest.mark.asyncio
async def test_light_bandwidth_favors_low_effort_candidates(
    async_db: AsyncSession, default_user: User
) -> None:
    """Light bandwidth reweights candidates toward lower reading effort."""
    light = await _add_thread(
        async_db, default_user, "Classic Light", queue_position=1
    )
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(
        async_db, default_user, "Heavy Read", queue_position=2
    )
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    selection = await select_bandwidth_weighted(
        async_db,
        bounded_rows=_pool_rows([light, heavy]),
        user_id=default_user.id,
        bandwidth="light",
        intent="balanced",
    )

    weights = _weights_by_candidate(selection)
    assert weights[light.id] == pytest.approx(1.5)
    assert weights[heavy.id] == pytest.approx(0.75)
    assert selection.weights_applied is True
    # Reason codes name the applied bandwidth bias for both candidates.
    factors = _factors_by_candidate(selection)
    assert "bandwidth_light_favors_low_effort" in factors[light.id]
    assert "bandwidth_light_dampens_high_effort" in factors[heavy.id]


@pytest.mark.asyncio
async def test_deep_bandwidth_favors_high_effort_without_excluding_light(
    async_db: AsyncSession, default_user: User
) -> None:
    """Deep bandwidth nudges toward heavier reads but never removes light ones."""
    light = await _add_thread(
        async_db, default_user, "Classic Light", queue_position=1
    )
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(
        async_db, default_user, "Heavy Read", queue_position=2
    )
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    selection = await select_bandwidth_weighted(
        async_db,
        bounded_rows=_pool_rows([light, heavy]),
        user_id=default_user.id,
        bandwidth="deep",
        intent="balanced",
    )

    weights = _weights_by_candidate(selection)
    assert weights[heavy.id] == pytest.approx(1.25)
    # The light candidate stays strictly positive (0.9) and selectable.
    assert weights[light.id] == pytest.approx(0.9)
    assert weights[light.id] > 0.0
    assert selection.weights_applied is True
    factors = _factors_by_candidate(selection)
    assert "bandwidth_deep_permits_high_effort" in factors[heavy.id]
    assert "bandwidth_deep_dampens_low_effort" in factors[light.id]


@pytest.mark.asyncio
async def test_unknown_effort_is_neutral_for_light_bandwidth(
    async_db: AsyncSession, default_user: User
) -> None:
    """Missing effort metadata never distorts a light-bandwidth draw."""
    first = await _add_thread(async_db, default_user, "No Effort A", queue_position=1)
    second = await _add_thread(async_db, default_user, "No Effort B", queue_position=2)
    await async_db.commit()

    selection = await select_bandwidth_weighted(
        async_db,
        bounded_rows=_pool_rows([first, second]),
        user_id=default_user.id,
        bandwidth="light",
        intent="balanced",
    )

    assert _weights_by_candidate(selection)[first.id] == pytest.approx(1.0)
    assert _weights_by_candidate(selection)[second.id] == pytest.approx(1.0)
    assert selection.weights_applied is False
    assert _factors_by_candidate(selection)[first.id] == ()


@pytest.mark.asyncio
async def test_selection_stays_inside_bounded_pool(
    async_db: AsyncSession, default_user: User
) -> None:
    """Weighted selection never leaves the bounded candidate pool."""
    threads = []
    for index in range(4):
        thread = await _add_thread(
            async_db, default_user, f"Thread {index}", queue_position=index + 1
        )
        await _confirm_series_era(async_db, thread, "1965-01-01")
        threads.append(thread)
    await async_db.commit()

    rows = _pool_rows(threads)
    for _ in range(50):
        selection = await select_bandwidth_weighted(
            async_db,
            bounded_rows=rows,
            user_id=default_user.id,
            bandwidth="light",
            intent="balanced",
        )
        assert 0 <= selection.selected_index < len(rows)


@pytest.mark.asyncio
async def test_random_intent_bypasses_bandwidth_weighting(
    async_db: AsyncSession, default_user: User
) -> None:
    """The random intent escapes contextual weighting even with known effort."""
    light = await _add_thread(
        async_db, default_user, "Classic Light", queue_position=1
    )
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(
        async_db, default_user, "Heavy Read", queue_position=2
    )
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    selection = await select_bandwidth_weighted(
        async_db,
        bounded_rows=_pool_rows([light, heavy]),
        user_id=default_user.id,
        bandwidth="deep",
        intent="random",
    )

    assert selection.mode is SelectionMode.PURE_RANDOM_BYPASS
    assert selection.weights_applied is False
    assert _weights_by_candidate(selection)[light.id] == pytest.approx(1.0)
    assert _weights_by_candidate(selection)[heavy.id] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_light_bandwidth_roll_persists_bandwidth_context(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A light-bandwidth roll persists matching weights and bandwidth reason."""
    light = await _add_thread(
        async_db, default_user, "Classic Light", queue_position=1
    )
    await _confirm_series_era(async_db, light, "1965-01-01")
    medium = await _add_thread(
        async_db, default_user, "Modern Medium", queue_position=2
    )
    await _confirm_series_era(async_db, medium, "2010-01-01")
    await async_db.commit()

    response = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert response.status_code == 200
    roll_data = response.json()
    assert roll_data["thread_id"] in {light.id, medium.id}

    event_result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .order_by(Event.id.desc())
        .limit(1)
    )
    roll_event = event_result.scalar_one()
    assert roll_event.selected_thread_id == roll_data["thread_id"]
    # Bandwidth weighting was actually applied, so the event is labeled
    # "bandwidth" rather than "random"/"momentum".
    assert roll_event.selection_method == "bandwidth"
    assert roll_event.recommendation_reason_codes == ["bandwidth_weighted"]

    context_result = await async_db.execute(
        select(RecommendationContext).where(
            RecommendationContext.event_id == roll_event.id
        )
    )
    context = context_result.scalar_one()
    assert context.random_bypass is False
    assert context.balanced_neutrality is False
    assert context.candidate_factors is not None

    factors = {factor["candidate_id"]: factor for factor in context.candidate_factors}
    assert set(factors) == {light.id, medium.id}
    # The classic (light-effort) candidate is favored by light bandwidth.
    assert factors[light.id]["weight"] == pytest.approx(1.5)
    assert "bandwidth_light_favors_low_effort" in factors[light.id]["factors"]
    # The modern candidate is a medium effort band, exactly neutral.
    assert factors[medium.id]["weight"] == pytest.approx(1.0)
    assert factors[medium.id]["factors"] == []

    # Persisted final weight equals the chooser weight of the selected thread.
    assert context.final_weight == factors[roll_data["thread_id"]]["weight"]
