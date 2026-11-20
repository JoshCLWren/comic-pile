"""Tests for the bounded dependency probe and the instance warm-up handler."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import health_probe
from app.startup_diagnostics import StartupSnapshot


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

    monkeypatch.setattr(health_probe, "DEPENDENCY_TIMEOUT_SECONDS", 0.001)
    result = await health_probe._timed_probe(slow_operation)

    assert result.status == "timeout"
    assert result.duration_ms < 50


def _make_mock_request(invocation: int = 1) -> MagicMock:
    """Create a mock Request with startup_snapshot."""
    mock_request = MagicMock()
    mock_request.state = MagicMock()
    mock_request.state.startup_snapshot = StartupSnapshot(
        invocation=invocation,
        cold=invocation == 1,
        process_age_ms=100.0,
        process_to_startup_ms=100.0,
        startup_cpu_ms=25.0,
        startup_complete=True,
        startup_duration_ms=50.0,
        application_import_ms=10.0,
        application_creation_ms=20.0,
        lifespan_ms=20.0,
        heavy_initialized=False,
        heavy_init_duration_ms=None,
        heavy_init_process_age_ms=None,
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
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

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
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = datetime.now(UTC)
    mock_db.execute = AsyncMock(return_value=mock_result)

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
    mock_db.execute = AsyncMock()

    result = await health_module.warm_endpoint(mock_request, mock_db)

    assert result.status == "no_activity"
    assert result.has_active_session is False
    assert result.request_count_today == 10
    assert result.instance.request_count == 10
