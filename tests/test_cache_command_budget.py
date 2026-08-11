"""Upper-bound tests for privacy-safe production cache command budgets."""

from __future__ import annotations

import json

import pytest

from app.cache import cache
from app.cache_generation import bump_user_generation, generation_cached, generation_key
from app.cache_metrics import (
    CACHE_FLOW_COMMAND_CEILINGS,
    CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
    MONTHLY_HEADROOM_COMMANDS,
    UPSTASH_FREE_MONTHLY_COMMANDS,
    cache_command_metrics,
)


class BudgetRedisClient:
    """Minimal in-memory Upstash-shaped client for command-envelope tests."""

    def __init__(self) -> None:
        """Initialize generation-zero state and an empty value store."""
        self.generation = 0
        self.values: dict[str, str] = {}

    async def eval(
        self,
        script: str,
        keys: list[str],
        args: list[str],
    ) -> list[object | None]:
        """Return one atomic generation/value snapshot."""
        assert "redis.call('GET', KEYS[1])" in script
        assert keys == [generation_key(7)]
        value_key = f"{args[0]}{self.generation}:{args[1]}"
        return [str(self.generation), self.values.get(value_key)]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Store one serialized generation-scoped value."""
        _ = ex
        self.values[key] = value

    async def incr(self, key: str) -> int:
        """Advance the single test user's generation."""
        assert key == generation_key(7)
        self.generation += 1
        return self.generation


@pytest.fixture(autouse=True)
def reset_cache_metrics() -> None:
    """Reset shared production command instrumentation before each test."""
    cache_command_metrics.reset()


@pytest.fixture
def budget_cache(monkeypatch: pytest.MonkeyPatch) -> BudgetRedisClient:
    """Install an Upstash-shaped client behind the production cache singleton."""
    client = BudgetRedisClient()
    monkeypatch.setattr(cache, "_client", client)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_is_upstash", True)
    return client


@pytest.mark.asyncio
async def test_bootstrap_cold_cache_stays_within_four_commands(
    budget_cache: BudgetRedisClient,
) -> None:
    """Bootstrap's two generation-scoped reads cost at most EVAL+SET each."""

    @generation_cached(ttl=60)
    async def load_session(user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    @generation_cached(ttl=60)
    async def load_die(user_id: int) -> dict[str, int]:
        return {"die": 8, "user_id": user_id}

    await load_session(7)
    await load_die(7)

    assert cache_command_metrics.snapshot() == {"generation_value_get": 2, "value_set": 2}
    assert cache_command_metrics.total() == CACHE_FLOW_COMMAND_CEILINGS["bootstrap"]
    cache_command_metrics.assert_within_flow_ceiling("bootstrap")


@pytest.mark.asyncio
async def test_queue_load_cold_cache_stays_within_two_commands(
    budget_cache: BudgetRedisClient,
) -> None:
    """A cold queue read costs one atomic lookup and one value write."""

    @generation_cached(ttl=60)
    async def load_queue(user_id: int) -> list[int]:
        return [user_id]

    await load_queue(7)

    assert cache_command_metrics.snapshot() == {"generation_value_get": 1, "value_set": 1}
    assert cache_command_metrics.total() == CACHE_FLOW_COMMAND_CEILINGS["queue_load"]
    cache_command_metrics.assert_within_flow_ceiling("queue_load")


@pytest.mark.asyncio
async def test_roll_cold_cache_and_invalidation_stay_within_five_commands(
    budget_cache: BudgetRedisClient,
) -> None:
    """Roll allows two cold reads plus one bounded generation invalidation."""

    @generation_cached(ttl=60)
    async def load_die(user_id: int) -> int:
        return user_id + 1

    @generation_cached(ttl=60)
    async def load_pool(user_id: int) -> list[int]:
        return [user_id]

    await load_die(7)
    await load_pool(7)
    await bump_user_generation(budget_cache, 7)

    assert cache_command_metrics.snapshot() == {
        "generation_value_get": 2,
        "value_set": 2,
        "generation_incr": 1,
    }
    assert cache_command_metrics.total() == CACHE_FLOW_COMMAND_CEILINGS["roll"]
    cache_command_metrics.assert_within_flow_ceiling("roll")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flow",
    [
        "snooze",
        "rating",
        "thread_mutation",
        "issue_mutation",
        "continuity_mutation",
    ],
)
async def test_mutation_flows_use_one_bounded_generation_invalidation(flow: str) -> None:
    """Mutation families stay at one remote INCR after SCAN removal."""
    client = BudgetRedisClient()

    await bump_user_generation(client, 7)

    assert cache_command_metrics.snapshot() == {"generation_incr": 1}
    assert cache_command_metrics.total() == CACHE_FLOW_COMMAND_CEILINGS[flow]
    cache_command_metrics.assert_within_flow_ceiling(flow)


def test_metrics_never_expose_cache_payloads() -> None:
    """Snapshots contain command families and aggregate counts only."""
    cache_command_metrics.record("GET")
    cache_command_metrics.record("SET", count=2)

    snapshot = cache_command_metrics.snapshot()

    assert snapshot == {"get": 1, "set": 2}
    serialized = json.dumps(snapshot)
    assert "cache:user" not in serialized
    assert "token" not in serialized
    assert "credential" not in serialized


def test_monthly_budget_reserves_thirty_percent_provider_headroom() -> None:
    """The application budget remains conservatively below Upstash Free capacity."""
    assert UPSTASH_FREE_MONTHLY_COMMANDS == 500_000
    assert CONSERVATIVE_MONTHLY_COMMAND_BUDGET == 350_000
    assert MONTHLY_HEADROOM_COMMANDS == 150_000
    assert MONTHLY_HEADROOM_COMMANDS / UPSTASH_FREE_MONTHLY_COMMANDS == pytest.approx(0.30)
