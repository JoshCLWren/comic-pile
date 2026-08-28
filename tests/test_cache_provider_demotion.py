"""Demotion policy and effective_provider coverage for #1784."""

import pytest

from app.cache import CacheRouter, CircuitBreaker, CircuitState, PostgresCache, UpstashCache
from app.config import RedisSettings


def _settings(**values: object) -> RedisSettings:
    base: dict[str, object] = {
        "cache_provider": "postgres",
        "cache_enabled": False,
        "upstash_redis_rest_url": None,
        "upstash_redis_rest_token": None,
        "redis_url": None,
    }
    base.update(values)
    return RedisSettings.model_validate(base)


def test_effective_provider_postgres_is_always_on() -> None:
    """Postgres provider is the default and does not require CACHE_ENABLED."""
    s = _settings(cache_provider="postgres")
    assert s.effective_provider == "postgres"
    assert s.is_configured is True


def test_effective_provider_redis_requires_credentials() -> None:
    """Redis provider demotes to off when credentials are absent."""
    s = _settings(cache_provider="redis", cache_enabled=True)
    assert s.effective_provider == "off"
    assert s.is_configured is False

    s2 = _settings(
        cache_provider="redis",
        cache_enabled=True,
        redis_url="redis://localhost:6379/0",
    )
    assert s2.effective_provider == "redis"
    assert s2.is_configured is True


def test_effective_provider_off_always_off() -> None:
    """CACHE_PROVIDER=off is never configured."""
    s = _settings(cache_provider="off", cache_enabled=True, redis_url="redis://localhost:6379/0")
    assert s.effective_provider == "off"
    assert s.is_configured is False


@pytest.mark.asyncio
async def test_postgres_cache_demotes_after_repeated_failures() -> None:
    """PostgresCache demotes to fail-open after circuit opens."""
    pc = PostgresCache.__new__(PostgresCache)
    # Bypass singleton state for isolated test
    pc._engine = None  # type: ignore[attr-defined]
    pc._circuit_breaker = CircuitBreaker(name="test-postgres", failure_threshold=2, reset_timeout_seconds=60)
    pc._initialized = True  # type: ignore[attr-defined]
    pc._demoted = False  # type: ignore[attr-defined]

    # Simulate repeated failures via record_failure path
    assert pc._circuit_breaker.state == CircuitState.CLOSED
    pc.record_failure()
    assert pc._demoted is False
    pc.record_failure()
    assert pc._circuit_breaker.state == CircuitState.OPEN
    assert pc._demoted is True


@pytest.mark.asyncio
async def test_router_demotes_to_fail_open_for_process_lifetime() -> None:
    """CacheRouter.demote permanently fail-opens without per-request ping-pong."""
    router = CacheRouter()
    # Install a fake backend that is initialized
    fake = UpstashCache.__new__(UpstashCache)
    fake._client = object()
    fake._initialized = True
    fake._is_upstash = True
    fake._circuit_breaker = CircuitBreaker(name="test")
    router._backend = fake  # type: ignore[attr-defined]
    router._provider_kind = "redis"
    router._demoted = False
    router._initialized = True

    assert router.is_initialized is True
    await router.demote()
    assert router.is_initialized is False
    assert router.provider_kind == "off"
    # Subsequent cache operations fail-open
    assert await router.get("cache:test:") is None
    assert await router.set("cache:test:", "v") is False


@pytest.mark.asyncio
async def test_router_startup_demote_on_postgres_init_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup demotes to off when postgres initialization raises."""
    from app import main

    settings = _settings(cache_provider="postgres")
    monkeypatch.setattr(main, "get_redis_settings", lambda: settings)
    monkeypatch.setattr(main, "init_database", pytest.importorskip("unittest.mock").AsyncMock())

    # Force CacheRouter.configure to raise
    async def failing_configure(*_a: object, **_kw: object) -> None:
        raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(main.cache, "configure", failing_configure)
    demote_mock = pytest.importorskip("unittest.mock").AsyncMock()
    monkeypatch.setattr(main.cache, "demote", demote_mock)

    # Also mock database settings to avoid needing real DATABASE_URL
    import app.config as config_module

    class _FakeDB:
        async_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/comic_pile_test"

    monkeypatch.setattr(config_module, "get_database_settings", lambda: _FakeDB())

    app_instance = main.create_app(serve_frontend=False)
    handler = next(h for h in app_instance.router.on_startup if getattr(h, "__name__", None) == "startup_event")
    await handler()
    demote_mock.assert_awaited_once()
