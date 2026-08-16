"""Tests for bounded liveness, dependency-health, and warm-up behavior."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import health
from app.models import Event
from app.startup_diagnostics import StartupSnapshot


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
async def test_legacy_health_is_dependency_free(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the public legacy route never opens database or cache connections.

    Args:
        client: Async HTTP client for the test application.
        monkeypatch: Pytest fixture for replacing dependency probes.

    Returns:
        None.
    """

    async def fail_if_called(*_: object) -> None:
        raise AssertionError("legacy liveness must not probe dependencies")

    monkeypatch.setattr(health, "_database_probe", fail_if_called)
    monkeypatch.setattr(health, "_cache_probe", fail_if_called)

    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


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


def _make_mock_request(invocation: int = 1) -> MagicMock:
    """Create a mock Request with startup_snapshot."""
    mock_request = MagicMock()
    mock_request.state = MagicMock()
    mock_request.state.startup_snapshot = StartupSnapshot(
        invocation=invocation,
        cold=invocation == 1,
        process_age_ms=100.0,
        startup_complete=True,
        startup_duration_ms=50.0,
        application_import_ms=10.0,
        application_creation_ms=20.0,
        lifespan_ms=20.0,
        deployment_id="test-deployment",
        process_started_at_ns=1_000_000_000,
    )
    return mock_request


@pytest.mark.asyncio
async def test_warm_endpoint_handler_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify warm endpoint handler returns no_activity when disabled.

    Args:
        monkeypatch: Pytest fixture for setting environment variables.

    Returns:
        None.
    """
    monkeypatch.setenv("WARM_ENDPOINT_ENABLED", "false")

    import importlib
    import app.api.health as health_module

    importlib.reload(health_module)

    mock_request = _make_mock_request()
    mock_db = AsyncMock()

    result = await health_module.warm_endpoint(mock_request, mock_db)

    assert result.status == "no_activity"
    assert result.has_active_session is False
    assert result.request_count_today == 0
    assert result.instance.request_count == 0
    assert result.instance.process_start_time_ns == 0


@pytest.mark.asyncio
async def test_warm_endpoint_handler_enabled_no_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify enabled warm endpoint handler with no recent activity returns no_activity.

    Args:
        monkeypatch: Pytest fixture for setting environment variables.

    Returns:
        None.
    """
    monkeypatch.setenv("WARM_ENDPOINT_ENABLED", "true")
    monkeypatch.setenv("WARM_ENDPOINT_MAX_DAILY_REQUESTS", "1000")
    monkeypatch.setenv("WARM_ENDPOINT_INACTIVITY_SECONDS", "1800")

    import importlib
    import app.api.health as health_module

    importlib.reload(health_module)

    mock_request = _make_mock_request(invocation=5)
    mock_db = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await health_module.warm_endpoint(mock_request, mock_db)

    assert result.status == "no_activity"
    assert result.has_active_session is False
    assert result.request_count_today == 5
    assert result.instance.request_count == 5
    assert result.instance.instance_id.startswith("instance-")
    assert result.instance.process_start_time_ns == 1_000_000_000
    assert result.instance.startup_time_ms == 50.0
    assert result.instance.process_age_ms == 100.0


@pytest.mark.asyncio
async def test_warm_endpoint_handler_with_recent_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify enabled warm endpoint handler with recent activity returns warming.

    Args:
        monkeypatch: Pytest fixture for setting environment variables.

    Returns:
        None.
    """
    monkeypatch.setenv("WARM_ENDPOINT_ENABLED", "true")
    monkeypatch.setenv("WARM_ENDPOINT_MAX_DAILY_REQUESTS", "1000")
    monkeypatch.setenv("WARM_ENDPOINT_INACTIVITY_SECONDS", "1800")

    import importlib
    import app.api.health as health_module

    importlib.reload(health_module)

    mock_request = _make_mock_request(invocation=10)
    mock_db = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none.return_value = datetime.now(UTC)
    mock_db.execute.return_value = mock_result

    result = await health_module.warm_endpoint(mock_request, mock_db)

    assert result.status == "warming"
    assert result.has_active_session is True
    assert result.request_count_today == 10
    assert result.instance.request_count == 10


@pytest.mark.asyncio
async def test_warm_endpoint_handler_rate_limit_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rate limit exceeded returns no_activity from rate limiter branch.

    Args:
        monkeypatch: Pytest fixture for setting environment variables.

    Returns:
        None.
    """
    monkeypatch.setenv("WARM_ENDPOINT_ENABLED", "true")
    monkeypatch.setenv("WARM_ENDPOINT_MAX_DAILY_REQUESTS", "5")
    monkeypatch.setenv("WARM_ENDPOINT_INACTIVITY_SECONDS", "1800")

    import importlib
    import app.api.health as health_module

    importlib.reload(health_module)

    # Request count exceeds the limit
    mock_request = _make_mock_request(invocation=10)
    mock_db = AsyncMock()

    result = await health_module.warm_endpoint(mock_request, mock_db)

    assert result.status == "no_activity"
    assert result.has_active_session is False
    assert result.request_count_today == 10
    assert result.instance.request_count == 10
