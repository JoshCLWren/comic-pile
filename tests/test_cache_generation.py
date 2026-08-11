"""Regression tests for bounded generation-scoped cache primitives."""

from __future__ import annotations

import json

import pytest

from app import cache_generation
from app.cache import cache, cached
from app.cache_generation import (
    _atomic_generation_value_get,
    bump_user_generation,
    command_budget,
    generation_cached,
    generation_key,
    get_user_generation,
)


class GenerationClient:
    """Minimal generation client for command-budget tests."""

    async def get(self, key: str) -> str | None:
        """Return a fixed generation.

        Args:
            key: Redis key.

        Returns:
            Fixed generation text.
        """
        return "2"

    async def incr(self, key: str) -> int:
        """Return a fixed incremented generation.

        Args:
            key: Redis key.

        Returns:
            Fixed incremented generation.
        """
        return 3


class AtomicReadClient:
    """Fake Redis client that exposes only one atomic read operation."""

    def __init__(self) -> None:
        """Initialize fake generation and value state."""
        self.generation = 0
        self.values = {
            "cache:user:7:g0:load:7:": json.dumps({"title": "old"}),
            "cache:user:7:g1:load:7:": json.dumps({"title": "new"}),
        }
        self.eval_calls = 0

    async def eval(
        self,
        script: str,
        keys: list[str],
        args: list[str],
    ) -> list[object | None]:
        """Return one generation/value snapshot, then advance the generation.

        Args:
            script: Lua script under test.
            keys: Redis keys supplied to the script.
            args: Script arguments used to construct the value key.

        Returns:
            Generation and serialized value from one atomic snapshot.
        """
        assert "redis.call('GET', KEYS[1])" in script
        assert keys == [generation_key(7)]
        self.eval_calls += 1
        generation = self.generation
        value = self.values[f"{args[0]}{generation}:{args[1]}"]

        # Model an invalidation that becomes visible immediately after the atomic
        # read. A split generation-GET/value-GET implementation would be able to
        # mix these states; the script returns one coherent snapshot instead.
        self.generation = 1
        return [str(generation), value]


class NullValueClient:
    """Fake Upstash client that can store and return a JSON null cache entry."""

    def __init__(self) -> None:
        """Initialize an empty generation-zero cache."""
        self.value: str | None = None
        self.eval_calls = 0
        self.set_calls = 0

    async def eval(
        self,
        script: str,
        keys: list[str],
        args: list[str],
    ) -> list[object | None]:
        """Return the current generation and stored serialized value."""
        assert "redis.call('GET', KEYS[1])" in script
        assert keys == [generation_key(7)]
        self.eval_calls += 1
        return ["0", self.value]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Store serialized cache data exactly as the cache wrapper supplies it."""
        assert key.startswith("cache:user:7:g0:")
        assert ex == 30
        self.set_calls += 1
        self.value = value


@pytest.fixture(autouse=True)
def reset_command_budget() -> None:
    """Reset command instrumentation before each test.

    Returns:
        ``None``.
    """
    command_budget.counts.clear()


@pytest.mark.asyncio
async def test_invalid_user_id_does_not_consume_generation_budget() -> None:
    """Reject invalid generation keys before recording remote commands."""
    client = GenerationClient()

    with pytest.raises(ValueError, match="user_id must be positive"):
        await get_user_generation(client, 0)
    with pytest.raises(ValueError, match="user_id must be positive"):
        await bump_user_generation(client, -1)

    assert command_budget.total == 0


@pytest.mark.asyncio
async def test_atomic_read_keeps_generation_and_value_in_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent invalidation from interleaving generation and value lookups."""
    client = AtomicReadClient()
    monkeypatch.setattr(cache, "_client", client)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_is_upstash", True)

    generation, cache_hit, value = await _atomic_generation_value_get(7, "cache:load:7:")

    assert generation == 0
    assert cache_hit is True
    assert value == {"title": "old"}
    assert client.generation == 1
    assert client.eval_calls == 1
    assert command_budget.counts == {"generation_value_get": 1}


@pytest.mark.asyncio
async def test_generation_cached_preserves_cached_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat a stored JSON null as a cache hit when falsy caching is enabled."""
    client = NullValueClient()
    monkeypatch.setattr(cache, "_client", client)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_is_upstash", True)

    executions = 0

    @generation_cached(ttl=300, falsy_ttl=30)
    async def load_optional(user_id: int) -> None:
        nonlocal executions
        executions += 1
        return None

    assert await load_optional(7) is None
    assert await load_optional(7) is None

    assert executions == 1
    assert client.eval_calls == 2
    assert client.set_calls == 1
    assert client.value == "null"


@pytest.mark.asyncio
async def test_cached_routes_user_scoped_calls_to_generation_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing @cached endpoints should gain generation semantics without rewrites."""
    routed_user_ids: list[int] = []

    def fake_generation_cached(ttl, *, falsy_ttl=None):
        assert ttl == 300
        assert falsy_ttl is None

        def decorator(func):
            async def wrapper(*args, **kwargs):
                user = kwargs.get("current_user")
                if user is None and args:
                    user = args[0]
                routed_user_ids.append(user.id)
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    monkeypatch.setattr(cache_generation, "generation_cached", fake_generation_cached)

    class User:
        id = 7

    executions = 0

    @cached(ttl=300)
    async def load(current_user: User) -> int:
        nonlocal executions
        executions += 1
        return current_user.id

    assert await load(User()) == 7
    assert await load(User()) == 7
    assert executions == 2
    assert routed_user_ids == [7, 7]


@pytest.mark.asyncio
async def test_cached_keeps_non_user_calls_on_legacy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-user cache consumers must not be forced into a shared user namespace."""
    routed = False

    def fake_generation_cached(ttl, *, falsy_ttl=None):
        nonlocal routed
        routed = True
        raise AssertionError("generation cache should not be constructed")

    monkeypatch.setattr(cache_generation, "generation_cached", fake_generation_cached)
    monkeypatch.setattr(cache, "_initialized", False)

    @cached(ttl=300)
    async def load_global(slug: str) -> str:
        return slug.upper()

    assert await load_global("comic-pile") == "COMIC-PILE"
    assert routed is False
