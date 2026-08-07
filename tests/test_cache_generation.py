"""Tests for bounded user-scoped cache generation primitives."""

from types import SimpleNamespace

import pytest

from app.cache_generation import (
    CacheCommandBudget,
    bump_user_generation,
    command_budget,
    generation_key,
    get_user_generation,
    invalidate_user_cache,
    namespaced_cache_key,
    user_id_from_arguments,
)


class FakeGenerationClient:
    """Minimal in-memory generation client for command-bound tests."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.get_calls = 0
        self.incr_calls = 0

    async def get(self, key: str) -> int | None:
        """Return a stored generation and record one GET."""
        self.get_calls += 1
        return self.values.get(key)

    async def incr(self, key: str) -> int:
        """Increment a generation and record one INCR."""
        self.incr_calls += 1
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]


def test_generation_key_is_user_scoped() -> None:
    """Generation counters must be deterministic and isolated per user."""
    assert generation_key(7) == "cache:generation:user:7"
    assert generation_key(8) == "cache:generation:user:8"


def test_generation_key_rejects_invalid_user() -> None:
    """Invalid user identifiers must not create shared cache namespaces."""
    with pytest.raises(ValueError, match="user_id must be positive"):
        generation_key(0)


def test_namespaced_cache_key_changes_with_generation() -> None:
    """A generation bump must make every prior logical key unreachable."""
    first = namespaced_cache_key(7, 2, "cache:list_threads:User:7:")
    second = namespaced_cache_key(7, 3, "cache:list_threads:User:7:")

    assert first == "cache:user:7:g2:list_threads:User:7:"
    assert second == "cache:user:7:g3:list_threads:User:7:"
    assert first != second


def test_namespaced_cache_keys_are_isolated_between_users() -> None:
    """Two users must never share a generation-scoped value key."""
    first = namespaced_cache_key(7, 4, "cache:list_threads:")
    second = namespaced_cache_key(8, 4, "cache:list_threads:")

    assert first != second


def test_user_id_from_arguments_supports_current_cache_signatures() -> None:
    """Cached functions can expose ownership as an ID or user model argument."""
    user = SimpleNamespace(id=42)

    assert user_id_from_arguments({"user_id": 41}) == 41
    assert user_id_from_arguments({"user": user}) == 42
    assert user_id_from_arguments({"current_user": user}) == 42
    assert user_id_from_arguments({"thread_id": 99}) is None


def test_command_budget_counts_only_commands() -> None:
    """Instrumentation tracks command totals without needing cache-key contents."""
    budget = CacheCommandBudget()

    budget.record("generation_get")
    budget.record("value_get")
    budget.record("value_set", 2)

    assert budget.total == 4
    assert budget.counts == {
        "generation_get": 1,
        "value_get": 1,
        "value_set": 2,
    }


def test_command_budget_rejects_negative_counts() -> None:
    """Instrumentation must not permit impossible negative command totals."""
    budget = CacheCommandBudget()

    with pytest.raises(ValueError, match="cannot be negative"):
        budget.record("value_get", -1)


@pytest.mark.asyncio
async def test_generation_read_defaults_to_zero_with_one_command() -> None:
    """A first cache read needs one GET and no initialization write."""
    client = FakeGenerationClient()
    command_budget.counts.clear()

    generation = await get_user_generation(client, 7)

    assert generation == 0
    assert client.get_calls == 1
    assert client.incr_calls == 0
    assert command_budget.counts == {"generation_get": 1}


@pytest.mark.asyncio
async def test_generation_bump_invalidates_user_with_one_command() -> None:
    """Each mutation can invalidate every user-scoped value with one INCR."""
    client = FakeGenerationClient()
    command_budget.counts.clear()

    first = await bump_user_generation(client, 7)
    second = await bump_user_generation(client, 7)

    assert first == 1
    assert second == 2
    assert client.get_calls == 0
    assert client.incr_calls == 2
    assert command_budget.counts == {"generation_incr": 2}


@pytest.mark.asyncio
async def test_generation_commands_remain_isolated_between_users() -> None:
    """Invalidating one user must not alter another user's cache generation."""
    client = FakeGenerationClient()
    command_budget.counts.clear()

    await bump_user_generation(client, 7)

    assert await get_user_generation(client, 7) == 1
    assert await get_user_generation(client, 8) == 0
    assert client.values == {generation_key(7): 1}
    assert command_budget.total == 3


@pytest.mark.asyncio
async def test_invalidate_user_cache_is_noop_when_remote_cache_is_disabled(monkeypatch) -> None:
    """Disabled remote caching must not create commands merely to invalidate."""
    from app.cache_generation import cache

    monkeypatch.setattr(cache, "_initialized", False)
    monkeypatch.setattr(cache, "_client", None)
    command_budget.counts.clear()

    assert await invalidate_user_cache(7) is False
    assert command_budget.total == 0


@pytest.mark.asyncio
async def test_invalidate_user_cache_uses_exactly_one_remote_command(monkeypatch) -> None:
    """The production invalidation entrypoint must remain one bounded INCR."""
    from app.cache_generation import cache

    client = FakeGenerationClient()
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_client", client)
    command_budget.counts.clear()

    assert await invalidate_user_cache(7) is True
    assert client.values == {generation_key(7): 1}
    assert client.get_calls == 0
    assert client.incr_calls == 1
    assert command_budget.counts == {"generation_incr": 1}
