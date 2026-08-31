"""Tests for the dev-flagged local Redis client path (issues #1716, #1752).

Issue #1752 trims the ``redis`` package from deployed environments: Upstash is
the only supported Redis client path in production, so the local redis-py
client is a dev-only escape hatch and the package is a dev dependency.
"""

from __future__ import annotations

import builtins
import sys
import tomllib
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.cache import CacheRouter, UpstashCache, _create_local_redis_client
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


def test_redis_is_dev_only_dependency() -> None:
    """The redis package is trimmed from deployed environments (issue #1752)."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    core_redis = [
        dep for dep in pyproject["project"]["dependencies"] if dep.startswith("redis")
    ]
    assert core_redis == []
    assert "redis>=5.0.0" in pyproject["dependency-groups"]["dev"]


def test_create_local_redis_client_imports_redis_lazily(monkeypatch) -> None:
    """The dev client factory imports redis only when the local path runs."""
    local_client = AsyncMock()
    from_url = Mock(return_value=local_client)

    fake_redis = types.ModuleType("redis")
    fake_asyncio = types.ModuleType("redis.asyncio")
    fake_client = type("Redis", (), {"from_url": staticmethod(from_url)})
    fake_asyncio.__dict__["Redis"] = fake_client
    fake_redis.__dict__["asyncio"] = fake_asyncio
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_asyncio)

    client = _create_local_redis_client("redis://localhost:6379/0")

    assert client is local_client
    from_url.assert_called_once_with(
        "redis://localhost:6379/0",
        decode_responses=True,
        socket_connect_timeout=5.0,
        socket_timeout=5.0,
    )


def test_local_redis_path_requires_dev_redis_package(monkeypatch) -> None:
    """The dev local path surfaces a clear error when redis is not installed."""
    real_import = builtins.__import__

    def _guard_redis(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis" or name.startswith("redis."):
            raise ModuleNotFoundError("No module named 'redis'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guard_redis)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        _create_local_redis_client("redis://localhost:6379/0")


async def test_upstash_configure_path_does_not_import_redis(monkeypatch) -> None:
    """The deployed Upstash path operates without the dev-only redis package."""
    from app import cache as cache_module

    real_import = builtins.__import__

    def _guard_redis(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis" or name.startswith("redis."):
            raise ModuleNotFoundError("No module named 'redis'")
        return real_import(name, globals, locals, fromlist, level)

    remote_client = AsyncMock()
    monkeypatch.setattr(builtins, "__import__", _guard_redis)
    monkeypatch.setattr(cache_module, "UpstashRedis", lambda **_: remote_client)

    backend = _fresh_upstash()
    await backend.initialize(url="https://example.upstash.io", token="secret")

    assert backend.is_initialized
    remote_client.ping.assert_not_awaited()
