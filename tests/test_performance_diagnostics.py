"""Tests for request, database, and cache performance diagnostics."""

import asyncio
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.cache import UpstashCache
from app.database import AsyncSessionLocal
from app.middleware.request_logging import add_request_logging_middleware
from app.performance_diagnostics import (
    begin_request_diagnostics,
    end_request_diagnostics,
    get_request_diagnostics,
    install_cache_instrumentation,
    record_cache_operation,
    record_database_query,
)


@pytest.mark.asyncio
async def test_request_middleware_emits_performance_headers() -> None:
    """Responses should expose a request ID and timing breakdown."""
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/diagnostics")
    async def diagnostics_route() -> dict[str, str]:
        """Return a response after recording synthetic request activity."""
        record_cache_operation("hit", 12.5)
        record_database_query(8.25)
        return {"status": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/diagnostics")

    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 32
    assert response.headers["x-app-cache"] == "hit"
    assert response.headers["x-app-db-queries"] == "1"
    server_timing = response.headers["server-timing"]
    assert "app;dur=" in server_timing
    assert 'db;dur=8.25;desc="1 queries"' in server_timing
    assert 'cache;dur=12.50;desc="hit"' in server_timing


@pytest.mark.asyncio
async def test_database_events_record_a_real_async_query() -> None:
    """SQLAlchemy execution events should update the active request context."""
    token = begin_request_diagnostics()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        diagnostics = get_request_diagnostics()
    finally:
        end_request_diagnostics(token)

    assert diagnostics.database_queries >= 1
    assert diagnostics.database_time_ms >= 0


def test_diagnostics_aggregate_mixed_cache_activity() -> None:
    """A request with cache hits and misses should report a mixed result."""
    token = begin_request_diagnostics()
    try:
        record_cache_operation("hit", 2.0)
        record_cache_operation("miss", 3.0)
        record_database_query(4.0)
        diagnostics = get_request_diagnostics()

        assert diagnostics.cache_status == "mixed"
        assert diagnostics.cache_calls == 2
        assert diagnostics.cache_time_ms == 5.0
        assert diagnostics.database_queries == 1
        assert diagnostics.database_time_ms == 4.0
    finally:
        end_request_diagnostics(token)


class _FakeCircuitBreaker:
    """Minimal circuit breaker used by the cache timeout test."""

    def __init__(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        """Record one wrapper-level timeout."""
        self.failures += 1


class _SlowCache:
    """Cache-shaped object whose reads exceed the configured timeout."""

    def __init__(self) -> None:
        self.is_initialized = True
        self._circuit_breaker = _FakeCircuitBreaker()

    async def get(self, key: str) -> object | None:
        """Return too slowly for the timeout wrapper."""
        del key
        await asyncio.sleep(0.05)
        return {"cached": True}

    async def set(self, key: str, value: object, ttl: int | None = None) -> bool:
        """Pretend to write successfully."""
        del key, value, ttl
        return True

    async def delete(self, key: str) -> bool:
        """Pretend to delete successfully."""
        del key
        return True

    async def clear_pattern(self, pattern: str) -> int:
        """Pretend to clear one key."""
        del pattern
        return 1


@pytest.mark.asyncio
async def test_cache_timeout_fails_open_and_records_failure(monkeypatch) -> None:
    """A stalled cache read should return a miss rather than delaying the request."""
    monkeypatch.setenv("CACHE_OPERATION_TIMEOUT_SECONDS", "0.001")
    fake_cache = _SlowCache()
    cache = cast(UpstashCache, fake_cache)
    install_cache_instrumentation(cache)

    token = begin_request_diagnostics()
    try:
        result = await cache.get("slow-key")
        diagnostics = get_request_diagnostics()
    finally:
        end_request_diagnostics(token)

    assert result is None
    assert diagnostics.cache_status == "timeout"
    assert diagnostics.cache_timeouts == 1
    assert fake_cache._circuit_breaker.failures == 1
