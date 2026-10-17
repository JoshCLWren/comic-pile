"""Regression tests for cold-start startup readiness enforcement (issue #3808)."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import clear_settings_cache
from app.main import create_app
from app.performance_budgets import (
    STARTUP_TIMEOUT_MS,
    StartupBudgetError,
    enforce_startup_budget,
    get_performance_budget_manager,
)
from app.startup_diagnostics import StartupSnapshot, startup_event_snapshot

_COLD_PROCESS_AGE_MS = 563622.82
_COLD_STARTUP_DURATION_MS = 563622.37
_HEALTHY_STARTUP_DURATION_MS = 1553.0
_OVER_BUDGET_READINESS_MS = 72420.56


def _snapshot_with(process_age_ms: float, startup_duration_ms: float | None) -> StartupSnapshot:
    """Return a startup snapshot with the supplied cold-start measurements.

    Args:
        process_age_ms: Wall-clock process age including platform provisioning.
        startup_duration_ms: App-measured readiness duration, or ``None`` when uncomputed.

    Returns:
        A ``StartupSnapshot`` derived from the live process snapshot.
    """
    base = startup_event_snapshot()
    return replace(base, process_age_ms=process_age_ms, startup_duration_ms=startup_duration_ms)


def _prepare_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a production environment and clear budget state.

    Args:
        monkeypatch: Pytest monkeypatch fixture used for env and settings state.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
    clear_settings_cache()
    get_performance_budget_manager().clear_all()


def test_production_cold_start_over_budget_serves_requests_and_records_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reported 563 s cold start must serve requests, not abort initialization.

    Reproduces the live failure from issue #3808: both ``process_age_ms`` and
    ``startup_duration_ms`` blow past the 2500 ms budget because of platform
    freeze/provisioning wall clock. Startup must complete, ping must return
    200, and the violation must still be recorded for telemetry.
    """
    _prepare_production(monkeypatch)

    def _cold_start_snapshot() -> StartupSnapshot:
        return _snapshot_with(_COLD_PROCESS_AGE_MS, _COLD_STARTUP_DURATION_MS)

    monkeypatch.setattr("app.startup_diagnostics.startup_event_snapshot", _cold_start_snapshot)

    app = create_app(serve_frontend=False, defer_router_imports=True)
    try:
        with TestClient(app) as client:
            assert client.get("/api/ping").status_code == 200

        assert get_performance_budget_manager().violation_counts_by_operation() == {
            "startup.readiness": 1
        }
    finally:
        clear_settings_cache()


def test_production_startup_inside_budget_records_no_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy production startup inside budget serves requests without violations."""
    _prepare_production(monkeypatch)

    def _healthy_snapshot() -> StartupSnapshot:
        return _snapshot_with(_HEALTHY_STARTUP_DURATION_MS, _HEALTHY_STARTUP_DURATION_MS)

    monkeypatch.setattr("app.startup_diagnostics.startup_event_snapshot", _healthy_snapshot)

    app = create_app(serve_frontend=False, defer_router_imports=True)
    try:
        with TestClient(app) as client:
            assert client.get("/api/ping").status_code == 200

        assert get_performance_budget_manager().get_startup_violations() == []
    finally:
        clear_settings_cache()


def test_enforce_startup_budget_records_readiness_violation_without_raising() -> None:
    """Production readiness violations are telemetry-only, never fatal."""
    manager = get_performance_budget_manager()
    manager.clear_all()

    recorded = enforce_startup_budget(_OVER_BUDGET_READINESS_MS, environment="production")

    assert recorded is not None
    assert recorded.severity == "violation"
    assert recorded.operation == "startup.readiness"
    assert recorded.elapsed_ms == _OVER_BUDGET_READINESS_MS
    assert recorded.context["deadline_ms"] == STARTUP_TIMEOUT_MS
    assert manager.violation_counts_by_operation() == {"startup.readiness": 1}


def test_enforce_startup_budget_still_raises_for_non_readiness_operations() -> None:
    """App-controlled startup operations keep the production hard-fail contract."""
    manager = get_performance_budget_manager()
    manager.clear_all()

    with pytest.raises(StartupBudgetError) as exc_info:
        enforce_startup_budget(
            _OVER_BUDGET_READINESS_MS,
            environment="production",
            operation="startup.heavy_init",
        )

    assert exc_info.value.operation == "startup.heavy_init"
    assert exc_info.value.elapsed_ms == _OVER_BUDGET_READINESS_MS
    assert exc_info.value.timeout_ms == STARTUP_TIMEOUT_MS
