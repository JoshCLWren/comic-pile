"""Seeded regression tests for the recommendation selection control path.

Issue #1717: preserve exact legacy selection for balanced and pure-random
modes. The legacy draw is ``random.randint(0, pool_size - 1)`` over the
already-bounded die pool (app/api/roll.py). Every control-mode draw here is
compared against that exact stream under shared seeds.
"""

import math
import random
from collections.abc import Sequence
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from comic_pile.recommendation_selection import (
    Bandwidth,
    Intent,
    SelectionMode,
    normalize_weights,
    resolve_selection_mode,
    select_from_pool,
)

POOL_SIZES = [1, 4, 6, 8, 20, 100]


def _legacy_stream(seed: int, pool_size: int, draws: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.randint(0, pool_size - 1) for _ in range(draws)]


class DeterministicRandom:
    """Test double emitting scripted values from the RandomSource protocol."""

    def __init__(
        self,
        random_values: list[float] | None = None,
        randint_values: list[int] | None = None,
    ) -> None:
        """Script both RNG streams; empty scripts raise on unexpected calls."""
        self.random_values = list(random_values or [])
        self.randint_values = list(randint_values or [])
        self.randint_calls: list[tuple[int, int]] = []

    def random(self) -> float:
        """Emit the next scripted uniform float."""
        if not self.random_values:
            raise AssertionError("unexpected random() call")
        return self.random_values.pop(0)

    def randint(self, low: int, high: int) -> int:
        """Record bounds and emit the next scripted integer."""
        self.randint_calls.append((low, high))
        if not self.randint_values:
            raise AssertionError("unexpected randint() call")
        return self.randint_values.pop(0)


@pytest.mark.parametrize("pool_size", POOL_SIZES)
@pytest.mark.parametrize("seed", range(25))
def test_balanced_default_matches_legacy_stream_exactly(seed: int, pool_size: int) -> None:
    """Balanced/default draws reproduce the legacy randint stream under shared seeds."""
    expected = _legacy_stream(seed, pool_size, draws=40)

    control_rng = random.Random(seed)
    outcomes = [
        select_from_pool(pool_size, rng=control_rng) for _ in range(len(expected))
    ]

    assert [outcome.index for outcome in outcomes] == expected
    assert [outcome.result for outcome in outcomes] == [value + 1 for value in expected]
    assert all(outcome.mode is SelectionMode.LEGACY_UNIFORM for outcome in outcomes)
    assert all(not outcome.weights_applied for outcome in outcomes)
    assert all(outcome.bandwidth is Bandwidth.BALANCED for outcome in outcomes)
    assert all(outcome.intent is Intent.BALANCED for outcome in outcomes)


def test_balanced_default_distribution_is_uniform() -> None:
    """Balanced/default draws stay uniformly distributed across the bounded pool."""
    pool_size = 6
    draws = 6000
    expected_per_bucket = draws / pool_size

    rng = random.Random(1717)
    counts = [0] * pool_size
    for _ in range(draws):
        outcome = select_from_pool(pool_size, rng=rng)
        counts[outcome.index] += 1

    for count in counts:
        assert abs(count - expected_per_bucket) < expected_per_bucket * 0.15


def test_random_intent_bypasses_contextual_weights_completely() -> None:
    """The random intent ignores adversarial weights and matches the legacy stream."""
    adversarial_weights = [0.000001] * 9 + [1000000000.0]

    for seed in range(10):
        expected = _legacy_stream(seed, 10, draws=30)

        bypass_rng = random.Random(seed)
        outcomes = [
            select_from_pool(
                10,
                bandwidth=Bandwidth.DEEP,
                intent=Intent.RANDOM,
                weights=adversarial_weights,
                rng=bypass_rng,
            )
            for _ in range(len(expected))
        ]

        assert [outcome.index for outcome in outcomes] == expected
        assert all(outcome.mode is SelectionMode.PURE_RANDOM_BYPASS for outcome in outcomes)
        assert all(not outcome.weights_applied for outcome in outcomes)
        assert all(outcome.bandwidth is Bandwidth.DEEP for outcome in outcomes)
        assert all(outcome.intent is Intent.RANDOM for outcome in outcomes)


def test_effort_biased_context_cannot_bias_balanced_mode() -> None:
    """Effort-biased weights cannot change balanced/default draw counts."""
    pool_size = 8
    draws = 4000
    effort_biased_weights = [float(position**4) for position in range(1, pool_size + 1)]

    legacy_counts = [0] * pool_size
    for value in _legacy_stream(97, pool_size, draws):
        legacy_counts[value] += 1

    balanced_rng = random.Random(97)
    counts = [0] * pool_size
    outcomes = []
    for _ in range(draws):
        outcome = select_from_pool(
            pool_size,
            bandwidth="balanced",
            intent="balanced",
            weights=effort_biased_weights,
            rng=balanced_rng,
        )
        counts[outcome.index] += 1
        outcomes.append(outcome)

    assert counts == legacy_counts
    assert all(not outcome.weights_applied for outcome in outcomes)


def test_context_data_recorded_without_influencing_selection() -> None:
    """Context values are recorded on the outcome without changing the draw stream."""
    contexts: list[tuple[str | None, str | None]] = [
        (None, None),
        ("light", "momentum"),
        ("deep", "explore"),
    ]
    expected = _legacy_stream(5150, 12, draws=30)

    for bandwidth, intent in contexts:
        context_rng = random.Random(5150)
        outcomes = [
            select_from_pool(12, bandwidth=bandwidth, intent=intent, rng=context_rng)
            for _ in range(len(expected))
        ]

        assert [outcome.index for outcome in outcomes] == expected

        resolved_mode = outcomes[0].mode
        assert resolved_mode in (
            SelectionMode.LEGACY_UNIFORM,
            SelectionMode.CONTEXTUAL_WEIGHTED,
        )
        assert all(outcome.mode is resolved_mode for outcome in outcomes)
        assert all(outcome.weights_applied is False for outcome in outcomes)
        assert outcomes[0].bandwidth.value == (bandwidth or "balanced")
        assert outcomes[0].intent.value == (intent or "balanced")


def test_weighted_path_applies_valid_weights_when_explicitly_active() -> None:
    """Valid weights shape a contextual-weighted draw toward the heavy candidates."""
    pool_size = 4
    draws = 2400
    weights = [8.0, 1.0, 1.0, 2.0]

    rng = random.Random(424242)
    counts = [0] * pool_size
    applied = True
    for _ in range(draws):
        outcome = select_from_pool(
            pool_size,
            bandwidth=Bandwidth.DEEP,
            intent=Intent.MOMENTUM,
            weights=weights,
            rng=rng,
        )
        counts[outcome.index] += 1
        applied = applied and outcome.weights_applied
        assert outcome.mode is SelectionMode.CONTEXTUAL_WEIGHTED

    assert applied
    assert counts[0] > draws * 0.6
    assert counts[3] > draws * 0.1


def test_weighted_boundary_mapping_is_exact() -> None:
    """Weighted cumulative mapping places boundary floats in the expected buckets."""
    deterministic = DeterministicRandom(random_values=[0.0])
    outcome = select_from_pool(
        3,
        bandwidth="deep",
        intent="explore",
        weights=[1.0, 2.0, 3.0],
        rng=deterministic,
    )
    assert outcome.index == 0
    assert outcome.result == 1

    near_total = 0.9999999999
    deterministic = DeterministicRandom(random_values=[near_total])
    outcome = select_from_pool(
        3,
        bandwidth="deep",
        intent="explore",
        weights=[1.0, 2.0, 3.0],
        rng=deterministic,
    )
    assert outcome.index == 2
    assert outcome.result == 3


@pytest.mark.parametrize(
    "weights",
    [
        None,
        [],
        [1.0, 2.0],
        [1.0, 2.0, 3.0, 4.0],
        [5.0, 0.0, 5.0],
        [5.0, -1.0, 5.0],
        [float("nan"), 1.0, 1.0],
        [float("inf"), 1.0, 1.0],
        "121",
        {"0": 1.0, "1": 1.0, "2": 1.0},
        [True, 1.0, 1.0],
        [None, 1.0, 1.0],
    ],
)
def test_invalid_weights_fall_back_to_uniform_safely(weights: object) -> None:
    """Invalid weights safely fall back to the exact legacy uniform draw."""
    seed = 808
    pool_size = 3
    draws = 20
    expected = _legacy_stream(seed, pool_size, draws)

    fallback_rng = random.Random(seed)
    outcomes = [
        select_from_pool(
            pool_size,
            bandwidth="light",
            intent="familiar",
            weights=cast("Sequence[float] | None", weights),
            rng=fallback_rng,
        )
        for _ in range(draws)
    ]

    assert [outcome.index for outcome in outcomes] == expected
    assert all(outcome.mode is SelectionMode.CONTEXTUAL_WEIGHTED for outcome in outcomes)
    assert all(not outcome.weights_applied for outcome in outcomes)


def test_normalize_weights_accepts_numeric_sequences_only() -> None:
    """Weight normalization accepts only finite positive numeric sequences of exact length."""
    assert normalize_weights(None, 3) is None
    assert normalize_weights((2, 4, 6), 3) == [2.0, 4.0, 6.0]
    assert normalize_weights([0.5, 0.25, 0.25], 3) == [0.5, 0.25, 0.25]
    assert normalize_weights([1, 2], 3) is None
    generator: Sequence[float] = (value for value in [1.0, 1.0, 1.0])
    assert normalize_weights(generator, 3) is None


def test_single_candidate_pool_always_selects_first() -> None:
    """Every selection mode picks the only candidate of a size-one pool."""
    uniform_outcome = select_from_pool(1, rng=random.Random(1))
    bypass_outcome = select_from_pool(1, bandwidth=None, intent="random", rng=random.Random(2))
    weighted_outcome = select_from_pool(
        1,
        bandwidth="deep",
        intent="momentum",
        weights=[42.0],
        rng=random.Random(3),
    )

    assert uniform_outcome.index == 0
    assert bypass_outcome.index == 0
    assert weighted_outcome.index == 0
    assert weighted_outcome.weights_applied is True


def test_selection_stays_inside_bounded_pool() -> None:
    """Weighted draws never select outside the bounded candidate pool."""
    for pool_size in range(1, 50):
        rng = random.Random(pool_size)
        for _ in range(50):
            outcome = select_from_pool(
                pool_size,
                bandwidth="light",
                intent="momentum",
                weights=[1.0] * pool_size,
                rng=rng,
            )
            assert 0 <= outcome.index < pool_size
            assert 1 <= outcome.result <= pool_size


@pytest.mark.parametrize("pool_size", [0, -3])
def test_non_positive_pool_size_raises(pool_size: int) -> None:
    """Non-positive pool sizes are rejected with a ValueError."""
    with pytest.raises(ValueError, match="pool_size"):
        select_from_pool(pool_size)


@pytest.mark.parametrize(
    ("bandwidth", "intent", "expected"),
    [
        (None, None, SelectionMode.LEGACY_UNIFORM),
        ("balanced", None, SelectionMode.LEGACY_UNIFORM),
        (None, "balanced", SelectionMode.LEGACY_UNIFORM),
        ("balanced", "balanced", SelectionMode.LEGACY_UNIFORM),
        (Bandwidth.BALANCED, Intent.BALANCED, SelectionMode.LEGACY_UNIFORM),
        (None, "random", SelectionMode.PURE_RANDOM_BYPASS),
        ("light", "random", SelectionMode.PURE_RANDOM_BYPASS),
        ("deep", "random", SelectionMode.PURE_RANDOM_BYPASS),
        ("light", None, SelectionMode.CONTEXTUAL_WEIGHTED),
        ("deep", "balanced", SelectionMode.CONTEXTUAL_WEIGHTED),
        ("light", "momentum", SelectionMode.CONTEXTUAL_WEIGHTED),
        ("deep", "familiar", SelectionMode.CONTEXTUAL_WEIGHTED),
        ("balanced", "momentum", SelectionMode.CONTEXTUAL_WEIGHTED),
    ],
)
def test_resolve_selection_mode_matrix(
    bandwidth: str | None, intent: str | None, expected: SelectionMode
) -> None:
    """The mode-resolution matrix maps each bandwidth/intent pair to its path."""
    assert resolve_selection_mode(bandwidth, intent) is expected


@pytest.mark.parametrize(
    ("bandwidth", "intent"),
    [("bogus", None), ("bogus", "random"), (None, "bogus"), ("deep", "teleport")],
)
def test_resolve_selection_mode_rejects_unknown_values(
    bandwidth: str | None, intent: str | None
) -> None:
    """Unknown bandwidth or intent values are rejected with a ValueError."""
    with pytest.raises(ValueError):
        resolve_selection_mode(bandwidth, intent)


def test_math_import_guard_for_finite_validation() -> None:
    """Normalized weights are finite floats usable by the weighted path."""
    normalized = normalize_weights([1.0, 1.0, 1.0], 3)
    assert normalized is not None
    assert all(math.isfinite(weight) for weight in normalized)


@pytest.mark.asyncio
async def test_roll_with_random_intent_records_bypass_without_behavior_change(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """A random-intent roll stays uniform and records an unweighted roll event."""
    response = await auth_client.post(
        "/api/roll/", json={"bandwidth": "deep", "intent": "random"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["die_size"] == 8
    assert 1 <= data["result"] <= data["die_size"]
    thread_ids = [thread.id for thread in sample_data["threads"] if thread.status == "active"]
    assert data["thread_id"] in thread_ids

    event_result = await async_db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    roll_event = event_result.scalar_one()
    assert roll_event.selection_method == "random"
    assert roll_event.selected_thread_id == data["thread_id"]
    assert roll_event.result == data["result"]


@pytest.mark.asyncio
async def test_roll_balanced_body_stays_neutral(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """An explicit balanced roll body returns the unchanged legacy response shape."""
    response = await auth_client.post(
        "/api/roll/", json={"bandwidth": "balanced", "intent": "balanced"}
    )
    assert response.status_code == 200
    assert set(response.json()) >= {
        "thread_id",
        "title",
        "format",
        "issues_remaining",
        "queue_position",
        "die_size",
        "result",
    }


@pytest.mark.asyncio
async def test_roll_light_body_records_unweighted_event(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """A light-bandwidth roll records an unweighted random roll event."""
    _ = sample_data
    response = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert response.status_code == 200

    event_result = await async_db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    roll_event = event_result.scalar_one()
    assert roll_event.selection_method == "random"


@pytest.mark.asyncio
async def test_roll_rejects_unknown_context_values(auth_client: AsyncClient) -> None:
    """Unknown intent/bandwidth values and unknown fields are rejected with 422."""
    bad_intent = await auth_client.post("/api/roll/", json={"intent": "cheat"})
    assert bad_intent.status_code == 422

    bad_bandwidth = await auth_client.post("/api/roll/", json={"bandwidth": 3})
    assert bad_bandwidth.status_code == 422

    unknown_field = await auth_client.post("/api/roll/", json={"flavor": "vanilla"})
    assert unknown_field.status_code == 422
