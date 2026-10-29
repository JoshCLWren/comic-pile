"""Cold startup telemetry must not pull in the optional GitHub alarm system."""

from __future__ import annotations

import logging
import sys

import pytest

from app.main import _log_ignored_startup_alarm_sample
from app.performance_budgets import STARTUP_TIMEOUT_MS


@pytest.mark.parametrize(
    ("duration_ms", "warning"),
    [
        (STARTUP_TIMEOUT_MS - 1.0, False),
        (STARTUP_TIMEOUT_MS, True),
        (STARTUP_TIMEOUT_MS + 1.0, True),
    ],
)
def test_ignored_startup_telemetry_preserves_log_contract_without_alarm_import(
    duration_ms: float,
    warning: bool,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve the old structured signal without even permitting the heavy import."""
    # If the optional module is used, the test must fail even on an environment
    # where another test imported that subsystem earlier.
    monkeypatch.setitem(sys.modules, "app.services.performance_issue_service", None)
    caplog.set_level(logging.INFO, logger="app.main")
    _log_ignored_startup_alarm_sample(duration_ms=duration_ms, deployment_id="dpl_profile")
    matching = [
        r for r in caplog.records if getattr(r, "event", None) == "performance_alarm_ignored_startup"
    ]
    assert len(matching) == 1
    record = matching[0]
    assert record.levelno == (logging.WARNING if warning else logging.INFO)
    assert record.operation == "startup.readiness"
    assert record.duration_ms == duration_ms
    assert record.deployment_id == "dpl_profile"
    assert record.startup_performance_violation is warning
    assert "Performance alarm ignored startup sample" in record.getMessage()
