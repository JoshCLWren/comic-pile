"""Tests for generation-aware cached reads and command ceilings."""

from typing import Any

import pytest

from app.cache_generation import command_budget, generation_cached


class FakeGenerationClient:
    """Minimal client that serves only the user generation lookup."""

    def __init__(self, generation: int = 0) -> None:
        self.generation = generation
        self.get_calls = 0

    async def get(self, _key: str) -> int:
        """Return the configured generation and record one GET."""
        self.get_calls += 1
        return self.generation

    async def incr(self, _key: str) -> int:
        """Generation increments are not expected in cached read tests."""
        raise AssertionError("cached reads must not increment the generation")


@pytest.fixture
def configured_cache(monkeypatch: pytest.MonkeyPatch) -> FakeGenerationClient:
    """Configure the singleton cache with a fake generation client."""
    from app.cache_generation import cache

    client = FakeGenerationClient(generation=4)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_client", client)
    command_budget.counts.clear()
    return client


@pytest.mark.asyncio
async def test_generation_cached_hit_uses_two_commands(
    monkeypatch: pytest.MonkeyPatch,
    configured_cache: FakeGenerationClient,
) -> None:
    """A user-scoped cache hit is bounded to generation GET plus value GET."""
    from app.cache_generation import cache

    value_get_calls: list[str] = []
    value_set_calls: list[tuple[str, Any, int | None]] = []

    async def fake_get(key: str) -> dict[str, int]:
        value_get_calls.append(key)
        return {"value": 9}

    async def fake_set(key: str, value: Any, ttl: int | None = None) -> bool:
        value_set_calls.append((key, value, ttl))
        return True

    monkeypatch.setattr(cache, "get", fake_get)
    monkeypatch.setattr(cache, "set", fake_set)

    executed = 0

    @generation_cached(ttl=60)
    async def load_value(user_id: int) -> dict[str, int]:
        nonlocal executed
        executed += 1
        return {"value": user_id}

    result = await load_value(7)

    assert result == {"value": 9}
    assert executed == 0
    assert configured_cache.get_calls == 1
    assert len(value_get_calls) == 1
    assert value_set_calls == []
    assert command_budget.counts == {
        "generation_get": 1,
        "value_get": 1,
    }
    assert command_budget.total == 2


@pytest.mark.asyncio
async def test_generation_cached_stored_miss_uses_three_commands(
    monkeypatch: pytest.MonkeyPatch,
    configured_cache: FakeGenerationClient,
) -> None:
    """A stored miss is bounded to generation GET, value GET, and value SET."""
    from app.cache_generation import cache

    value_get_calls: list[str] = []
    value_set_calls: list[tuple[str, Any, int | None]] = []

    async def fake_get(key: str) -> None:
        value_get_calls.append(key)
        return None

    async def fake_set(key: str, value: Any, ttl: int | None = None) -> bool:
        value_set_calls.append((key, value, ttl))
        return True

    monkeypatch.setattr(cache, "get", fake_get)
    monkeypatch.setattr(cache, "set", fake_set)

    executed = 0

    @generation_cached(ttl=60)
    async def load_value(user_id: int) -> dict[str, int]:
        nonlocal executed
        executed += 1
        return {"value": user_id}

    result = await load_value(7)

    assert result == {"value": 7}
    assert executed == 1
    assert configured_cache.get_calls == 1
    assert len(value_get_calls) == 1
    assert len(value_set_calls) == 1
    assert value_set_calls[0][1:] == ({"value": 7}, 60)
    assert command_budget.counts == {
        "generation_get": 1,
        "value_get": 1,
        "value_set": 1,
    }
    assert command_budget.total == 3


@pytest.mark.asyncio
async def test_generation_cached_bypasses_cache_without_user_ownership(
    monkeypatch: pytest.MonkeyPatch,
    configured_cache: FakeGenerationClient,
) -> None:
    """A function without user ownership must execute without remote commands."""
    from app.cache_generation import cache

    async def unexpected_get(_key: str) -> Any:
        raise AssertionError("unowned reads must not reach the cache")

    async def unexpected_set(_key: str, _value: Any, ttl: int | None = None) -> bool:
        raise AssertionError(f"unowned reads must not set cache values with ttl={ttl}")

    monkeypatch.setattr(cache, "get", unexpected_get)
    monkeypatch.setattr(cache, "set", unexpected_set)

    executed = 0

    @generation_cached(ttl=60)
    async def load_value(thread_id: int) -> dict[str, int]:
        nonlocal executed
        executed += 1
        return {"value": thread_id}

    result = await load_value(91)

    assert result == {"value": 91}
    assert executed == 1
    assert configured_cache.get_calls == 0
    assert command_budget.total == 0
