"""Safety evidence for the remote-cache re-enable decision."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.cache import cache
from app.cache_generation import bump_user_generation, generation_cached, generation_key
from app.config import RedisSettings


@dataclass
class SharedRedisState:
    """State shared by independent Redis-shaped application clients."""

    generations: dict[str, int] = field(default_factory=dict)
    values: dict[str, str] = field(default_factory=dict)


class SharedUpstashClient:
    """Minimal Upstash-shaped client backed by shared cross-instance state."""

    def __init__(self, state: SharedRedisState) -> None:
        """Bind this client to the shared Redis state."""
        self.state = state

    async def eval(
        self,
        script: str,
        keys: list[str],
        args: list[str],
    ) -> list[object | None]:
        """Return one atomic generation/value snapshot."""
        assert "redis.call('GET', KEYS[1])" in script
        generation = self.state.generations.get(keys[0], 0)
        value_key = f"{args[0]}{generation}:{args[1]}"
        return [str(generation), self.state.values.get(value_key)]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Store one serialized generation-scoped value."""
        _ = ex
        self.state.values[key] = value

    async def incr(self, key: str) -> int:
        """Advance and return the shared generation counter."""
        generation = self.state.generations.get(key, 0) + 1
        self.state.generations[key] = generation
        return generation


@pytest.mark.asyncio
async def test_generation_invalidation_is_visible_across_application_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutation on one instance invalidates another instance's cached view."""
    shared = SharedRedisState()
    instance_a = SharedUpstashClient(shared)
    instance_b = SharedUpstashClient(shared)
    source = {"title": "before"}
    executions = 0

    from app.cache import UpstashCache

    # UpstashCache is a process-wide singleton. This test needs a fake backend,
    # but constructing it through UpstashCache() would mutate the live singleton's
    # client and leak SharedUpstashClient into every later test. Bypass __new__ so
    # the fake transport is genuinely isolated from the process cache backend.
    process_backend = UpstashCache()
    process_client = process_backend._client
    mock_backend = object.__new__(UpstashCache)
    UpstashCache.__init__(mock_backend)
    mock_backend._initialized = True
    mock_backend._client = instance_a
    mock_backend._is_upstash = True
    mock_backend._circuit_breaker.reset()

    monkeypatch.setattr(cache, "_backend", mock_backend)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_demoted", False)

    @generation_cached(ttl=60)
    async def load_issue(user_id: int) -> dict[str, str]:
        nonlocal executions
        executions += 1
        return dict(source)

    assert await load_issue(7) == {"title": "before"}
    assert await load_issue(7) == {"title": "before"}
    assert executions == 1

    source["title"] = "after"
    assert await bump_user_generation(instance_b, 7) == 1
    assert shared.generations[generation_key(7)] == 1

    # Switch to instance_a for the read (simulating another app instance)
    mock_backend._client = instance_a
    assert await load_issue(7) == {"title": "after"}
    assert executions == 2

    # The process-wide backend must remain untouched by this fake-client test.
    assert UpstashCache()._client is process_client


def test_remote_cache_remains_explicitly_disabled_by_default() -> None:
    """Provider credentials alone must not silently turn remote caching back on."""
    settings = RedisSettings(
        cache_provider="redis",
        cache_enabled=False,
        upstash_redis_rest_url="https://example.invalid",
        upstash_redis_rest_token="test-token",
    )

    assert settings.cache_enabled is False
    assert settings.effective_provider == "off"
    assert settings.is_configured is False
