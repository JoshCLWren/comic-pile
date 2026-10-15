"""Regression tests for the default-off performance-to-GitHub boundary (#3726)."""

import asyncio
import logging
from collections.abc import Coroutine
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppSettings, clear_settings_cache
from app.middleware.request_logging import add_request_logging_middleware
from app.performance_budgets import StartupBudgetError, run_bounded
from app.services import performance_issue_service as perf_issues


@pytest.fixture(autouse=True)
def disable_performance_github_filing(monkeypatch: pytest.MonkeyPatch):
    """Default every policy-boundary test to explicit filing opt-out."""
    monkeypatch.setenv("PERF_ALARM_GITHUB_ISSUES_ENABLED", "false")
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_absent_configuration_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Filing must be off when the deployment omits the setting entirely."""
    monkeypatch.delenv("PERF_ALARM_GITHUB_ISSUES_ENABLED", raising=False)
    assert AppSettings(_env_file=None).perf_alarm_github_issues_enabled is False


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("true", True), ("TRUE", True), ("false", False), ("FALSE", False)],
)
def test_explicit_boolean_configuration(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: bool
) -> None:
    """Only unambiguous opt-in and opt-out strings are valid."""
    monkeypatch.setenv("PERF_ALARM_GITHUB_ISSUES_ENABLED", configured)
    assert AppSettings(_env_file=None).perf_alarm_github_issues_enabled is expected


@pytest.mark.parametrize("invalid", ["1", "0", "on", "off", "yes", "no", "", "maybe"])
def test_ambiguous_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    """Do not accidentally enable GitHub filing with loose bool coercion."""
    monkeypatch.setenv("PERF_ALARM_GITHUB_ISSUES_ENABLED", invalid)
    with pytest.raises(ValidationError, match="perf_alarm_github_issues_enabled"):
        AppSettings(_env_file=None)


@pytest.mark.parametrize(
    ("duration_ms", "cold"),
    [(1001.0, False), (30000.0, False), (1962.0, True), (575.0, False)],
)
def test_disabled_requests_do_not_schedule_or_count(
    duration_ms: float, cold: bool
) -> None:
    """Neither marginal nor severe samples create background evaluation."""
    with (
        patch.object(perf_issues, "_spawn_background") as spawn,
        patch.object(perf_issues, "_open_production_store", new_callable=AsyncMock) as store,
    ):
        for _ in range(4):
            perf_issues.handle_request_telemetry(
                method="PUT",
                route_template="/api/v1/threads/{thread_id}",
                duration_ms=duration_ms,
                cold=cold,
                db_queries=6,
                db_time_ms=26.3,
                request_id="req-disabled",
                deployment_id="dpl-disabled",
            )
        spawn.assert_not_called()
        store.assert_not_called()


def test_disabled_coroutine_timeout_never_schedules() -> None:
    """Even the legacy immediate-filing exception must respect opt-out."""
    with patch.object(perf_issues, "_spawn_background") as spawn:
        perf_issues.handle_coroutine_timeout(
            operation="startup.neon_monitor",
            elapsed_ms=5000.0,
            deadline_ms=500.0,
            exception_type="TimeoutError",
        )
        spawn.assert_not_called()


def test_disabled_schedule_filing_does_not_queue_work() -> None:
    """A direct filing decision cannot circumvent the public handler gate."""
    decision = perf_issues.FilingDecision(
        action="file",
        fingerprint="disabled",
        canonical="request|PUT|/api/v1/threads/{thread_id}",
        high_priority=True,
        reason="test",
    )
    with patch.object(perf_issues, "_spawn_background") as spawn:
        perf_issues.schedule_filing(
            decision=decision, title="slow", body="evidence", labels=["performance"]
        )
        spawn.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_background_paths_do_not_open_store_or_access_github() -> None:
    """Already-enqueued workers, direct calls and filing helpers also fail closed."""
    decision = perf_issues.FilingDecision(
        action="file",
        fingerprint="disabled",
        canonical="request|GET|/api/v1/creators",
        high_priority=True,
        reason="test",
    )
    store = MagicMock()
    with (
        patch.object(perf_issues, "_open_production_store", new_callable=AsyncMock) as open_store,
        patch.object(perf_issues, "_resolve_store") as resolve_store,
        patch(
            "app.services.github_service.create_performance_issue",
            new_callable=AsyncMock,
        ) as create_issue,
        patch(
            "app.services.github_service.find_open_issue_by_fingerprint",
            new_callable=AsyncMock,
        ) as lookup,
        patch(
            "app.services.github_service.add_performance_issue_comment",
            new_callable=AsyncMock,
        ) as comment,
    ):
        await perf_issues._handle_request_background(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=30000.0,
            cold=False,
            dominant_phase=None,
            db_queries=0,
            db_time_ms=0.0,
            request_id="req",
            deployment_id="dpl",
            server_timing="app;dur=30000",
        )
        await perf_issues._handle_coroutine_background(
            operation="startup.neon_monitor",
            elapsed_ms=5000.0,
            deadline_ms=500.0,
            exception_type="TimeoutError",
            deployment_id="dpl",
        )
        await perf_issues._file_decision_background(
            decision=decision, title="slow", body="evidence", labels=["performance"]
        )
        await perf_issues._file_new_issue(
            store=store, decision=decision, title="slow", body="evidence",
            labels=["performance"],
        )
        result = await perf_issues._comment_if_throttled(
            store=store,
            fingerprint="disabled",
            issue_number=10,
            comment="recurrence",
        )

    assert result is None
    open_store.assert_not_called()
    resolve_store.assert_not_called()
    store.try_claim_filing.assert_not_called()
    store.try_claim_comment.assert_not_called()
    create_issue.assert_not_called()
    lookup.assert_not_called()
    comment.assert_not_called()


def test_startup_failure_keeps_warning_without_filing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Readiness timing remains observable at the hard failure threshold."""
    with (
        caplog.at_level(logging.WARNING, logger=perf_issues.logger.name),
        patch.object(perf_issues, "_spawn_background") as spawn,
    ):
        perf_issues.handle_startup_telemetry(
            duration_ms=59404.0,
            operation="startup.readiness",
            deployment_id="dpl",
        )
    spawn.assert_not_called()
    assert any(
        record.__dict__.get("startup_performance_violation") is True
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_hard_timeout_still_logs_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Disabling GitHub never weakens the actual startup deadline."""
    with (
        caplog.at_level(logging.ERROR, logger="app.performance_budgets"),
        patch.object(perf_issues, "_spawn_background") as spawn,
        pytest.raises(StartupBudgetError),
    ):
        await run_bounded(
            "startup.neon_monitor", asyncio.sleep(0.05),
            warning_ms=0.0, timeout_ms=1.0,
        )
    spawn.assert_not_called()
    assert any("exceeded its hard budget" in r.getMessage() for r in caplog.records)


def test_request_diagnostics_remain_active_without_filing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Structured warm timing, Server-Timing and request ids stay observable."""
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "1")
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/slow-without-github")
    async def slow_without_github() -> dict[str, str]:
        await asyncio.sleep(0.01)
        return {"status": "ok"}

    with (
        caplog.at_level(logging.WARNING, logger="app.middleware.request_logging"),
        patch.object(perf_issues, "_spawn_background") as spawn,
    ):
        response = TestClient(app).get("/slow-without-github")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["X-App-DB-Queries"] == "0"
    assert "app;dur=" in response.headers["Server-Timing"]
    assert any("Performance warning" in r.getMessage() for r in caplog.records)
    spawn.assert_not_called()


def test_explicit_opt_in_restores_request_and_coroutine_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy filing path still schedules under affirmative opt-in."""
    monkeypatch.setenv("PERF_ALARM_GITHUB_ISSUES_ENABLED", "true")
    clear_settings_cache()
    scheduled = 0

    def capture_and_close(coroutine: Coroutine[object, object, None]) -> None:
        nonlocal scheduled
        scheduled += 1
        coroutine.close()

    with patch.object(perf_issues, "_spawn_background", side_effect=capture_and_close):
        perf_issues.handle_request_telemetry(
            method="GET",
            route_template="/api/v1/creators",
            duration_ms=1200.0,
            cold=False,
        )
        perf_issues.handle_coroutine_timeout(
            operation="startup.neon_monitor",
            elapsed_ms=500.0,
            deadline_ms=500.0,
        )
    assert scheduled == 2
