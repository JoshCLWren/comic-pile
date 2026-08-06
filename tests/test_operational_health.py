"""Tests for bounded liveness, dependency-health, and warm-up behavior."""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import health


@pytest.mark.asyncio
async def test_liveness_does_not_probe_dependencies(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify liveness remains independent from dependencies.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for replacing dependency probes.

    Returns:
        None.
    """

    async def fail_if_called() -> None:
        raise AssertionError("dependency probe must not run")

    monkeypatch.setattr(health, "_cache_probe", fail_if_called)
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_dependency_health_reports_independent_timings(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify healthy dependency responses include independent timings.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for replacing the cache probe.

    Returns:
        None.
    """

    async def healthy_cache() -> None:
        return None

    monkeypatch.setattr(health, "_cache_probe", healthy_cache)
    response = await client.get("/api/v1/health/dependencies")

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
    """Verify cache failure degrades an otherwise healthy response.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for replacing the cache probe.

    Returns:
        None.
    """

    async def unavailable_cache() -> None:
        raise ConnectionError("cache offline")

    monkeypatch.setattr(health, "_cache_probe", unavailable_cache)
    response = await client.get("/api/v1/health/dependencies")

    assert response.status_code == 207
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"]["status"] == "healthy"
    assert payload["cache"]["status"] == "unavailable"
    assert "offline" not in response.text


@pytest.mark.asyncio
async def test_dependency_health_reports_database_unavailable(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify database failure produces an unhealthy response without exception text.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for replacing dependency probes.

    Returns:
        None.
    """

    async def unavailable_database(_: AsyncSession) -> None:
        raise ConnectionError("database offline")

    async def healthy_cache() -> None:
        return None

    monkeypatch.setattr(health, "_database_probe", unavailable_database)
    monkeypatch.setattr(health, "_cache_probe", healthy_cache)
    response = await client.get("/api/v1/health/dependencies")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["database"]["status"] == "unavailable"
    assert payload["cache"]["status"] == "healthy"
    assert "database offline" not in response.text


@pytest.mark.asyncio
async def test_dependency_probe_times_out_without_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify slow dependency probes stop at the configured bound.

    Args:
        monkeypatch: Pytest fixture for overriding the timeout.

    Returns:
        None.
    """

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
    """Verify configured operational endpoints require the trusted token.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for setting the health token.

    Returns:
        None.
    """
    monkeypatch.setenv("HEALTH_CHECK_TOKEN", "trusted-monitor")

    hidden = await client.get("/api/v1/health/dependencies")
    allowed = await client.get(
        "/api/v1/health/dependencies",
        headers={"X-Health-Token": "trusted-monitor"},
    )

    assert hidden.status_code == 404
    assert allowed.status_code in (200, 207, 503)


@pytest.mark.asyncio
async def test_legacy_health_never_exposes_operational_details(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the public legacy route remains database-only when a token is configured.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for setting the health token.

    Returns:
        None.
    """
    monkeypatch.setenv("HEALTH_CHECK_TOKEN", "trusted-monitor")

    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected"}
    assert "cache" not in response.text
    assert "duration_ms" not in response.text


@pytest.mark.asyncio
async def test_warmup_uses_read_only_dependency_boundary(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify warm-up exercises the bounded database and cache path.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for replacing the cache probe.

    Returns:
        None.
    """
    calls = 0

    async def healthy_cache() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(health, "_cache_probe", healthy_cache)
    response = await client.get("/api/v1/health/warmup")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert calls == 1
