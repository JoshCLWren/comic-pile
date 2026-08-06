"""Regression tests for the explicit Redis cache feature gate."""

from unittest.mock import AsyncMock

import pytest

from app.cache import UpstashCache, cached
from app.config import RedisSettings


def test_cache_defaults_to_disabled_with_remote_credentials_present() -> None:
    """Credentials alone must not make deployed caching active."""
    settings = RedisSettings(
        _env_file=None,
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="test-token",
    )

    assert settings.cache_enabled is False
    assert settings.is_configured is False


def test_remote_redis_url_defaults_to_disabled() -> None:
    """A remote Redis URL cannot activate caching without explicit opt-in."""
    settings = RedisSettings(
        _env_file=None,
        redis_url="rediss://default:test-token@example.upstash.io:6379/0",
    )

    assert settings.is_configured is False


def test_local_cache_configuration_requires_explicit_enablement() -> None:
    """Disposable local Redis remains available when tests opt in."""
    settings = RedisSettings(
        _env_file=None,
        cache_enabled=True,
        redis_url="redis://localhost:6379/0",
    )

    assert settings.is_configured is True


def test_incomplete_upstash_configuration_stays_disabled() -> None:
    """The feature gate cannot activate a partially configured remote cache."""
    settings = RedisSettings(
        _env_file=None,
        cache_enabled=True,
        upstash_redis_rest_url="https://example.upstash.io",
    )

    assert settings.is_configured is False


@pytest.mark.asyncio
async def test_disabled_cache_reads_fall_through_without_remote_commands(monkeypatch) -> None:
    """Decorated reads execute directly when the cache is uninitialized."""
    from app import cache as cache_module

    remote_client = AsyncMock()
    monkeypatch.setattr(cache_module.cache, "_initialized", False)
    monkeypatch.setattr(cache_module.cache, "_client", remote_client)
    wrapped = AsyncMock(return_value={"source": "database"})

    @cached(ttl=60)
    async def load_value() -> dict[str, str]:
        return await wrapped()

    assert await load_value() == {"source": "database"}
    wrapped.assert_awaited_once_with()
    remote_client.get.assert_not_awaited()
    remote_client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_uninitialized_cache_invalidation_makes_no_remote_calls() -> None:
    """Disabled invalidation remains a safe no-op."""
    cache_client = UpstashCache()
    remote_client = AsyncMock()
    cache_client._initialized = False
    cache_client._client = remote_client

    assert await cache_client.delete("cache:key") is False
    assert await cache_client.clear_pattern("cache:*") == 0
    remote_client.delete.assert_not_awaited()
    remote_client.scan.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_skips_redis_with_credentials_when_gate_is_disabled(monkeypatch) -> None:
    """Cold startup never initializes or pings Redis when the gate is off."""
    from app import main

    disabled_settings = RedisSettings(
        _env_file=None,
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="test-token",
    )
    initialize = AsyncMock()
    monkeypatch.setattr(main, "get_redis_settings", lambda: disabled_settings)
    monkeypatch.setattr(main.cache, "initialize", initialize)
    monkeypatch.setattr(main, "init_database", AsyncMock())

    application = main.create_app(serve_frontend=False)
    startup_handler = next(
        handler for handler in application.router.on_startup if handler.__name__ == "startup_event"
    )
    await startup_handler()

    initialize.assert_not_awaited()
