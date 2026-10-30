"""Cold startup telemetry must not pull in the optional GitHub alarm system."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
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
    assert record.__dict__["operation"] == "startup.readiness"
    assert record.__dict__["duration_ms"] == duration_ms
    assert record.__dict__["deployment_id"] == "dpl_profile"
    assert record.__dict__["startup_performance_violation"] is warning
    assert "Performance alarm ignored startup sample" in record.getMessage()


def test_startup_event_records_alarm_event_without_importing_alarm_service() -> None:
    """Run real startup in a fresh worker and guard both halves of the contract.

    The negative half (no optional alarm import) and the positive half (the
    startup sample is still recorded) must be asserted together: checking only
    the import boundary would still pass if the telemetry call were deleted.
    """
    script = """
import asyncio
import logging
import sys

from app.main import create_app
from app.performance_budgets import STARTUP_TIMEOUT_MS

class Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

async def main():
    collector = Collector()
    startup_logger = logging.getLogger("app.main")
    startup_logger.setLevel(logging.INFO)
    startup_logger.addHandler(collector)
    app = create_app(serve_frontend=False, defer_router_imports=True)
    async with app.router.lifespan_context(app):
        assert "app.services.performance_issue_service" not in sys.modules
    matches = [
        record
        for record in collector.records
        if getattr(record, "event", None) == "performance_alarm_ignored_startup"
    ]
    assert len(matches) == 1, [getattr(r, "event", None) for r in collector.records]
    record = matches[0]
    assert record.__dict__["operation"] == "startup.readiness"
    assert record.__dict__["startup_performance_violation"] is (
        record.__dict__["duration_ms"] >= STARTUP_TIMEOUT_MS
    )
    expected_level = (
        logging.WARNING if record.__dict__["startup_performance_violation"] else logging.INFO
    )
    assert record.levelno == expected_level
    assert "startup.readiness" in record.getMessage()
    print("startup-import-boundary-ok")

asyncio.run(main())
"""
    environment = {
        **os.environ,
        "TEST_ENVIRONMENT": "true",
        "ENVIRONMENT": "test",
        "NEON_TOKEN": "",
        "NEON_PROJECT_ID": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "startup-import-boundary-ok" in result.stdout
