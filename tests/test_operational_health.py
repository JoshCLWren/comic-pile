"""Tests for bounded liveness, dependency-health, and warm-up behavior."""

import asyncio

import pytest
from httpx import AsyncClient

from app.api import health


@pytest.mark.asyncio
async def test_liveness_does_not_probe_dependencies(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Liveness remains independent from database and cache availability."""

    async def fail_if_called() -> None:
        raise AssertionError("dependency probe must not run")

    monkeypatch.setattr(health, "_cache_probe", fail_if_called)
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_dependency_health_reports_independent_timings(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy dependencies return searchable per-dependency timing fields."""

    async def healthy_cache() -> None:
        return None

    monkeypatch.setattr(health, "_cache_probe", healthy_cache)
    response = await client.get("/health/dependencies")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["database"]["status"] == "healthy"
    assert payload["cache"]["status"] == "healthy"
    assert payload["database"]["duration_ms"] >= 0
    assert payload["cache"]["duration_ms"] >= 0
    assert payload["total_duration_ms"] >= 0


@pytest.mark.asyncio
async def test_dependency_health_reports_partial_failure(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache failure is degraded while the independently healthy database stays visible."""

    async def unavailable_cache() -> None:
        raise ConnectionError("cache offline")

    monkeypatch.setattr(health, "_cache_probe", unavailable_cache)
    response = await client.get("/health/dependencies")

    assert response.status_code == 207
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"]["status"] == "healthy"
    assert payload["cache"]["status"] == "unavailable"
    assert "offline" not in response.text


@pytest.mark.asyncio
async def test_dependency_probe_times_out_without_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow dependencies stop at the configured bound and expose timeout state."""

    async def slow_operation() -> None:
        await asyncio.sleep(0.05)

    monkeypatch.setattr(health, "DEPENDENCY_TIMEOUT_SECONDS", 0.001)
    result = await health._timed_probe(slow_operation)

    assert result.status == "timeout"
    assert result.duration_ms < 50


@pytest.mark.asyncio
async def test_operational_token_hides_detailed_endpoints(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured operational endpoints return 404 without the trusted token."""
    monkeypatch.setenv("HEALTH_CHECK_TOKEN", "trusted-monitor")

    hidden = await client.get("/health/dependencies")
    allowed = await client.get(
        "/health/dependencies",
        headers={"X-Health-Token": "trusted-monitor"},
    )

    assert hidden.status_code == 404
    assert allowed.status_code in (200, 207, 503)


@pytest.mark.asyncio
async def test_warmup_uses_read_only_dependency_boundary(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm-up exercises the same bounded database and cache read path."""
    calls = 0

    async def healthy_cache() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(health, "_cache_probe", healthy_cache)
    response = await client.get("/health/warmup")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert calls == 1
