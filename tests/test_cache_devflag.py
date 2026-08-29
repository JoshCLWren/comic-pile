"""Tests for the dev-flagged local Redis client path (issue #1716)."""

from __future__ import annotations

import pytest

from app.cache import CacheRouter, UpstashCache
from app.config import RedisSettings


def _fresh_upstash() -> UpstashCache:
    """Return a re-initializable UpstashCache singleton for transport tests."""
    backend = UpstashCache()
    backend._initialized = False
    backend._client = None
    return backend


def test_effective_provider_refuses_local_redis_without_dev_flag() -> None:
    """A bare REDIS_URL does not enable caching unless CACHE_LOCAL_REDIS_DEV is set."""
    settings = RedisSettings(
        cache_provider="redis",
        cache_enabled=True,
        redis_url="redis://localhost:6379/0",
        cache_local_redis_dev=False,
    )

    assert settings.effective_provider == "off"


def test_effective_provider_allows_local_redis_with_dev_flag() -> None:
    """The local path is selectable only when the dev flag is explicit."""
    settings = RedisSettings(
        cache_provider="redis",
        cache_enabled=True,
        redis_url="redis://localhost:6379/0",
        cache_local_redis_dev=True,
    )

    assert settings.effective_provider == "redis"


def test_effective_provider_prefers_upstash_regardless_of_dev_flag() -> None:
    """Upstash credentials still enable caching without the local dev flag."""
    settings = RedisSettings(
        cache_provider="redis",
        cache_enabled=True,
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="secret",
        cache_local_redis_dev=False,
    )

    assert settings.effective_provider == "redis"


async def test_upstash_initialize_refuses_local_url_without_allow_local() -> None:
    """The transport refuses a local URL unless allow_local is explicit."""
    backend = _fresh_upstash()

    with pytest.raises(ValueError, match="CACHE_LOCAL_REDIS_DEV"):
        await backend.initialize(local_url="redis://localhost:6379/0", allow_local=False)


async def test_upstash_initialize_accepts_local_url_with_allow_local() -> None:
    """allow_local=True permits the dev-only local Redis transport."""
    backend = _fresh_upstash()

    await backend.initialize(local_url="redis://localhost:6379/0", allow_local=True)

    assert backend.is_initialized
    assert backend._is_upstash is False


async def test_router_configure_refuses_local_redis_without_allow_local() -> None:
    """CacheRouter.configure propagates the dev-flag gate to the transport."""
    router = CacheRouter()

    with pytest.raises(ValueError):
        await router.configure("redis", local_url="redis://localhost:6379/0")
