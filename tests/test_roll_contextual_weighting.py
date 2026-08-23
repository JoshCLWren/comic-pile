"""Phase 3 acceptance regression: contextual Roll weighting inside the die pool.

Covers issue #1720 (part of #1685):

- seeded light mode statistically favors lower-effort candidates;
- seeded deep mode follows documented higher-effort weighting without
  excluding light reads;
- no candidate outside the legacy die-bounded pool can be selected;
- balanced/default modes preserve the exact legacy unweighted behavior;
- unknown effort is neutral;
- persisted candidate weights/reasons match the actual selection inputs;
- existing blocked/snoozed/completed eligibility remains unchanged.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session as SessionModel, Thread, User
from comic_pile.recommendation_weights import (
    BANDWIDTH_DEEP,
    BANDWIDTH_LIGHT,
    NEUTRAL_WEIGHT,
    REASON_UNKNOWN_EFFORT,
    WEIGHTS_BY_MODE_AND_BAND,
    build_candidate_weights,
    choose_weighted_index,
    classify_effort_band,
    normalize_bandwidth,
)

ROLL_PATH = "/api/roll/"
DISMISS_PATH = "/api/roll/dismiss-pending"

#: Fixed seed so statistical regressions are reproducible in CI.
SEED = 1720


async def _create_weighted_pool(
    async_db: AsyncSession,
    user_id: int,
    efforts: list[float | None],
    die_size: int,
) -> list[int]:
    """Create one active thread per effort entry plus a manual-die session.

    Args:
        async_db: Test database session.
        user_id: Owner ID for the created rows.
        efforts: Estimated minutes per thread, in queue order. ``None`` means
            unknown effort. Queue positions are assigned starting at 1.
        die_size: Manual die size bounding the legacy roll pool.

    Returns:
        Created thread IDs ordered by queue position.
    """
    now = datetime.now(UTC)
    session = SessionModel(
        start_die=die_size,
        manual_die=die_size,
        user_id=user_id,
        started_at=now,
    )
    async_db.add(session)

    threads: list[Thread] = []
    for position, effort_minutes in enumerate(efforts, start=1):
        thread = Thread(
            title=f"Weighted Thread {position}",
            format="Comic",
            issues_remaining=1,
            queue_position=position,
            status="active",
            user_id=user_id,
            created_at=now,
            estimated_minutes=effort_minutes,
        )
        async_db.add(thread)
        threads.append(thread)

    await async_db.flush()
    await async_db.commit()
    return [thread.id for thread in threads]


async def _create_eligibility_pool(async_db: AsyncSession, user_id: int) -> list[int]:
    """Create a pool mixing eligible threads with blocked/completed decoys.

    Args:
        async_db: Test database session.
        user_id: Owner ID for the created rows.

    Returns:
        IDs of decoy threads that must never be selected (blocked or completed),
        ordered by queue position among all six created threads.
    """
    now = datetime.now(UTC)
    session = SessionModel(
        start_die=6,
        manual_die=6,
        user_id=user_id,
        started_at=now,
    )
    async_db.add(session)

    specs: list[tuple[str, float | None, str, bool]] = [
        ("Eligible Light", 5.0, "active", False),
        ("Blocked Light Decoy", 4.0, "active", True),
        ("Completed Heavy Decoy", 30.0, "completed", False),
        ("Eligible Heavy", 35.0, "active", False),
        ("Blocked Deep Bait", 60.0, "active", True),
        ("Eligible Medium", 14.0, "active", False),
    ]

    threads: list[Thread] = []
    for position, (title, effort_minutes, status_value, blocked) in enumerate(specs, start=1):
        thread = Thread(
            title=title,
            format="Comic",
            issues_remaining=1,
            queue_position=position,
            status=status_value,
            is_blocked=blocked,
            user_id=user_id,
            created_at=now,
            estimated_minutes=effort_minutes,
        )
        async_db.add(thread)
        threads.append(thread)

    await async_db.flush()
    await async_db.commit()
    return [
        thread.id
        for thread, (_, _, status_value, blocked) in zip(threads, specs, strict=True)
        if blocked or status_value != "active"
    ]


async def _current_user_id(async_db: AsyncSession) -> int:
    """Return the authenticated test user's ID."""
    result = await async_db.execute(select(User).where(User.id == 1))
    user = result.scalar_one()
    return user.id


async def _latest_roll_event(async_db: AsyncSession) -> Event:
    """Fetch the most recent roll event."""
    result = await async_db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    return result.scalar_one()


async def _roll_many(
    auth_client: AsyncClient,
    bandwidth: str | None,
    count: int,
) -> list[int]:
    """Perform ``count`` rolls, returning selected thread IDs in order."""
    selected: list[int] = []
    body = {"bandwidth": bandwidth} if bandwidth is not None else {}
    for _ in range(count):
        response = await auth_client.post(ROLL_PATH, json=body)
        assert response.status_code == 200, response.text
        selected.append(response.json()["thread_id"])
        dismiss = await auth_client.post(DISMISS_PATH)
        assert dismiss.status_code == 204
    return selected


@pytest.fixture
def seeded_rng(monkeypatch: pytest.MonkeyPatch) -> Callable[[], random.Random]:
    """Install a shared seeded RNG for weighted selection and return its getter."""

    def _install(seed: int = SEED) -> random.Random:
        rng = random.Random(seed)

        import app.api.roll as roll_module

        monkeypatch.setattr(roll_module, "_weighted_rng", lambda: rng)
        return rng

    return _install


# ---------------------------------------------------------------------------
# Pure weighting-function contracts (#1712)
# ---------------------------------------------------------------------------


def test_classify_effort_band_boundaries() -> None:
    """Documented evidence bands split at 12 and 18 minutes."""
    assert classify_effort_band(5.0) == "light"
    assert classify_effort_band(11.999) == "light"
    assert classify_effort_band(12.0) == "medium"
    assert classify_effort_band(17.999) == "medium"
    assert classify_effort_band(18.0) == "heavy"
    assert classify_effort_band(90.0) == "heavy"
    assert classify_effort_band(None) is None
    assert classify_effort_band(-3.0) is None


def test_normalize_bandwidth_defaults_to_balanced() -> None:
    """Absent and unrecognized modes normalize to neutral balanced."""
    assert normalize_bandwidth(BANDWIDTH_LIGHT) == "light"
    assert normalize_bandwidth(BANDWIDTH_DEEP) == "deep"
    assert normalize_bandwidth("balanced") == "balanced"
    assert normalize_bandwidth(None) == "balanced"
    assert normalize_bandwidth("warp-speed") == "balanced"


def test_light_mode_favors_lower_effort_bands() -> None:
    """Light mode weights strictly decrease with effort band."""
    weights = WEIGHTS_BY_MODE_AND_BAND["light"]
    assert weights["light"] > weights["medium"] > weights["heavy"]


def test_deep_mode_favors_higher_effort_without_excluding_light() -> None:
    """Deep mode weights strictly increase with effort but stay positive."""
    weights = WEIGHTS_BY_MODE_AND_BAND["deep"]
    assert weights["heavy"] > weights["medium"] > weights["light"]
    assert min(weights.values()) > 0


def test_unknown_effort_is_neutral_in_every_mode() -> None:
    """Missing or invalid effort always yields the neutral weight."""
    candidates = build_candidate_weights([(1, None), (2, 5.0), (3, -1.0)], BANDWIDTH_LIGHT)
    assert [candidate.weight for candidate in candidates] == [NEUTRAL_WEIGHT, 3.0, NEUTRAL_WEIGHT]
    assert candidates[0].reason == REASON_UNKNOWN_EFFORT
    assert candidates[2].reason == REASON_UNKNOWN_EFFORT
    assert candidates[0].band is None


def test_choose_weighted_index_distribution() -> None:
    """Weighted selection tracks relative weights over many draws."""
    rng = random.Random(SEED)
    draws = 20_000
    first_count = sum(1 for _ in range(draws) if choose_weighted_index([3.0, 1.0], rng) == 0)
    observed = first_count / draws
    assert 0.72 < observed < 0.78


def test_choose_weighted_index_rejects_invalid_weights() -> None:
    """Empty pools and non-positive totals are rejected."""
    rng = random.Random(SEED)
    with pytest.raises(ValueError, match="empty"):
        choose_weighted_index([], rng)
    with pytest.raises(ValueError, match="positive"):
        choose_weighted_index([0.0, 0.0], rng)


# ---------------------------------------------------------------------------
# Seeded statistical selection contracts (#1715)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_light_mode_favors_low_effort_inside_same_pool(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Seeded light mode statistically favors lower-effort candidates."""
    seeded_rng()
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, 8.0, 11.0, 25.0, 30.0, 40.0],
        die_size=6,
    )

    selected = await _roll_many(auth_client, "light", 360)

    assert set(selected).issubset(set(thread_ids))
    light_band = set(thread_ids[:3])
    heavy_band = set(thread_ids[3:])
    light_count = sum(1 for thread_id in selected if thread_id in light_band)
    heavy_count = sum(1 for thread_id in selected if thread_id in heavy_band)
    # Weighted probability of the light band is 0.75 versus uniform 0.5.
    assert light_count >= 220
    assert light_count > heavy_count


@pytest.mark.asyncio
async def test_seeded_deep_mode_favors_high_effort_but_keeps_light_reads(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Seeded deep mode favors high effort while light reads remain reachable."""
    seeded_rng()
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, 8.0, 11.0, 25.0, 30.0, 40.0],
        die_size=6,
    )

    selected = await _roll_many(auth_client, "deep", 360)

    assert set(selected).issubset(set(thread_ids))
    light_band = set(thread_ids[:3])
    heavy_band = set(thread_ids[3:])
    light_count = sum(1 for thread_id in selected if thread_id in light_band)
    heavy_count = sum(1 for thread_id in selected if thread_id in heavy_band)
    # Weighted probability of the heavy band is 0.75 versus uniform 0.5.
    assert heavy_count >= 220
    assert heavy_count > light_count
    # Light reads are weighted, never excluded.
    assert light_count > 0


@pytest.mark.asyncio
async def test_no_selection_outside_legacy_die_pool(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Weighting can never select a candidate beyond the die-bounded prefix."""
    seeded_rng()
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[4.0, 14.0, 24.0, 34.0, 6.0, 16.0, 26.0, 36.0, 9.0, 19.0],
        die_size=4,
    )
    bounded_pool = set(thread_ids[:4])
    outside_pool = set(thread_ids[4:])
    assert len(outside_pool) == 6

    selected = (
        await _roll_many(auth_client, "light", 160)
        + await _roll_many(auth_client, "deep", 160)
        + await _roll_many(auth_client, None, 80)
    )

    assert set(selected).issubset(bounded_pool)
    assert outside_pool.isdisjoint(set(selected))


# ---------------------------------------------------------------------------
# Neutral-mode legacy preservation (#1717)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_and_balanced_modes_stay_uniform(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Default (omitted) and explicit balanced rolls keep unweighted behavior."""
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, 8.0, 25.0, 40.0],
        die_size=4,
    )

    default_selected = await _roll_many(auth_client, None, 300)
    balanced_selected = await _roll_many(auth_client, "balanced", 300)

    floor = 45
    for label, selected in (("default", default_selected), ("balanced", balanced_selected)):
        assert set(selected) == set(thread_ids), label
        for thread_id in thread_ids:
            count = selected.count(thread_id)
            assert count >= floor, f"{label}: thread {thread_id} selected {count} times"


@pytest.mark.asyncio
async def test_neutral_rolls_use_exact_legacy_path(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neutral rolls call legacy randint and never construct weighted state."""
    import app.api.roll as roll_module

    randint_calls: list[tuple[int, int]] = []
    real_randint = random.randint

    def spy_randint(low: int, high: int) -> int:
        randint_calls.append((low, high))
        return real_randint(low, high)

    def forbidden_weighted_rng() -> random.Random:
        raise AssertionError("Weighted RNG must not be used for neutral rolls")

    monkeypatch.setattr(roll_module.random, "randint", spy_randint)
    monkeypatch.setattr(roll_module, "_weighted_rng", forbidden_weighted_rng)

    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, 8.0, 25.0, 40.0],
        die_size=4,
    )

    await _roll_many(auth_client, "balanced", 3)
    assert randint_calls == [(0, 3)] * 3

    randint_calls.clear()
    await _roll_many(auth_client, None, 2)
    assert randint_calls == [(0, 3)] * 2

    event = await _latest_roll_event(async_db)
    assert event.selection_method == "random"
    assert event.bandwidth_weighting_json is None
    assert event.selected_thread_id in thread_ids


@pytest.mark.asyncio
async def test_unknown_effort_threads_remain_selectable_under_light_mode(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Unknown-effort candidates keep neutral weight and stay reachable."""
    seeded_rng()
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[None, None, 5.0, 40.0],
        die_size=4,
    )
    unknown_effort_ids = set(thread_ids[:2])

    selected = await _roll_many(auth_client, "light", 300)

    # Unknown-effort threads carry weight 1.0 each versus 3.0 for the 5-minute
    # read and 1.0 for the 40-minute read, so their combined odds are 2/5.
    unknown_count = sum(1 for thread_id in selected if thread_id in unknown_effort_ids)
    assert unknown_count >= 80


# ---------------------------------------------------------------------------
# Persisted weighting evidence (#1718)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persisted_weights_and_reasons_match_selection_inputs(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """The roll event records the exact weights and reasons used to select."""
    seeded_rng(seed=20260823)
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, None, 40.0],
        die_size=3,
    )

    response = await auth_client.post(ROLL_PATH, json={"bandwidth": "light"})
    assert response.status_code == 200
    rolled = response.json()

    event = await _latest_roll_event(async_db)
    assert event.selection_method == "bandwidth_light"
    payload = event.bandwidth_weighting_json
    assert payload is not None

    assert payload["bandwidth"] == "light"
    candidates = payload["candidates"]
    assert [candidate["thread_id"] for candidate in candidates] == thread_ids
    assert [candidate["position"] for candidate in candidates] == [0, 1, 2]
    assert [candidate["effort_minutes"] for candidate in candidates] == [5.0, None, 40.0]
    assert [candidate["band"] for candidate in candidates] == ["light", None, "heavy"]
    assert [candidate["weight"] for candidate in candidates] == [3.0, 1.0, 1.0]
    assert [candidate["reason"] for candidate in candidates] == [
        "light_mode_light_effort",
        "effort_unknown_neutral",
        "light_mode_heavy_effort",
    ]

    # The recorded result points back into the weighted candidate list.
    assert rolled["thread_id"] == event.selected_thread_id
    assert candidates[event.result - 1]["thread_id"] == event.selected_thread_id


@pytest.mark.asyncio
async def test_deep_mode_persists_documented_higher_effort_weights(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Deep-mode evidence reflects the documented higher-effort weighting."""
    seeded_rng(seed=42)
    user_id = await _current_user_id(async_db)
    await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, 15.0, 40.0],
        die_size=3,
    )

    response = await auth_client.post(ROLL_PATH, json={"bandwidth": "deep"})
    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    payload = event.bandwidth_weighting_json
    assert payload is not None
    assert payload["bandwidth"] == "deep"
    assert [candidate["weight"] for candidate in payload["candidates"]] == [1.0, 2.0, 3.0]
    assert [candidate["reason"] for candidate in payload["candidates"]] == [
        "deep_mode_light_effort",
        "deep_mode_medium_effort",
        "deep_mode_heavy_effort",
    ]
    assert event.selection_method == "bandwidth_deep"


# ---------------------------------------------------------------------------
# Unchanged eligibility (#1714)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_and_completed_threads_stay_ineligible_under_weighting(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Blocked and completed threads are never selected by weighted rolls."""
    seeded_rng()
    user_id = await _current_user_id(async_db)
    ineligible_ids = await _create_eligibility_pool(async_db, user_id)
    assert len(ineligible_ids) == 3

    pool_result = await async_db.execute(select(Thread).where(Thread.user_id == user_id))
    all_ids = {thread.id for thread in pool_result.scalars().all()}
    eligible_ids = all_ids - set(ineligible_ids)

    selected = (
        await _roll_many(auth_client, "light", 120)
        + await _roll_many(auth_client, "deep", 120)
    )

    assert set(selected).issubset(eligible_ids)
    assert set(ineligible_ids).isdisjoint(set(selected))


@pytest.mark.asyncio
async def test_snoozed_threads_stay_ineligible_under_weighting(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    seeded_rng: Callable[[], random.Random],
) -> None:
    """Snoozed threads remain excluded from weighted selection."""
    seeded_rng()
    user_id = await _current_user_id(async_db)
    thread_ids = await _create_weighted_pool(
        async_db,
        user_id,
        efforts=[5.0, 8.0, 12.0, 20.0],
        die_size=4,
    )

    session_result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id)
    )
    session = session_result.scalar_one()
    snoozed_id = thread_ids[0]
    session.snoozed_thread_ids = [snoozed_id]
    await async_db.commit()

    selected = await _roll_many(auth_client, "light", 150)

    assert snoozed_id not in selected
    assert set(selected).issubset(set(thread_ids[1:]))
