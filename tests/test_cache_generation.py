"""Regression tests for bounded generation-scoped cache primitives."""

from __future__ import annotations

import json

import pytest

from app.cache_generation import (
    _atomic_generation_value_get,
    bump_user_generation,
    command_budget,
    generation_key,
    get_user_generation,
)
from app.cache import cache


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
async def test_atomic_read_keeps_generation_and_value_in_one_snapshot(monkeypatch) -> None:
    """Prevent invalidation from interleaving generation and value lookups."""
    client = AtomicReadClient()
    monkeypatch.setattr(cache, "_client", client)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_is_upstash", True)

    generation, value = await _atomic_generation_value_get(7, "cache:load:7:")

    assert generation == 0
    assert value == {"title": "old"}
    assert client.generation == 1
    assert client.eval_calls == 1
    assert command_budget.counts == {"generation_value_get": 1}
