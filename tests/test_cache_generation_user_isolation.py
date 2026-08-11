"""Focused isolation coverage for generation-scoped user caches."""

from __future__ import annotations

from collections import defaultdict

import pytest

from app.cache import cache, cached
from app.cache_generation import generation_key, invalidate_user_cache


class IsolatedGenerationClient:
    """Minimal Upstash-compatible client with per-user generation state."""

    def __init__(self) -> None:
        """Initialize isolated generation counters and cached values."""
        self.generations: dict[str, int] = {}
        self.values: dict[str, str] = {}

    async def eval(
        self,
        script: str,
        keys: list[str],
        args: list[str],
    ) -> list[object | None]:
        """Return the generation and value from one user-scoped snapshot."""
        assert "redis.call('GET', KEYS[1])" in script
        generation = self.generations.get(keys[0], 0)
        value_key = f"{args[0]}{generation}:{args[1]}"
        return [str(generation), self.values.get(value_key)]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Persist one serialized cache value."""
        assert ex == 300
        self.values[key] = value

    async def incr(self, key: str) -> int:
        """Increment only the requested user's generation counter."""
        generation = self.generations.get(key, 0) + 1
        self.generations[key] = generation
        return generation


@pytest.mark.asyncio
async def test_generation_invalidation_isolated_between_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalidating one user must not evict or recompute another user's cached view."""
    client = IsolatedGenerationClient()
    monkeypatch.setattr(cache, "_client", client)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_is_upstash", True)

    executions: defaultdict[int, int] = defaultdict(int)

    @cached(ttl=300)
    async def load_user_view(user_id: int) -> str:
        executions[user_id] += 1
        return f"user-{user_id}-v{executions[user_id]}"

    assert await load_user_view(7) == "user-7-v1"
    assert await load_user_view(11) == "user-11-v1"
    assert await load_user_view(7) == "user-7-v1"
    assert await load_user_view(11) == "user-11-v1"

    assert await invalidate_user_cache(7) is True

    assert await load_user_view(7) == "user-7-v2"
    assert await load_user_view(11) == "user-11-v1"
    assert executions == {7: 2, 11: 1}
    assert client.generations == {generation_key(7): 1}
    assert any(key.startswith("cache:user:7:g1:") for key in client.values)
    assert any(key.startswith("cache:user:11:g0:") for key in client.values)
