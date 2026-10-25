"""Roll telemetry regression: bounded, read-only SQL-vs-other-wall measurements."""

import logging
from unittest.mock import patch

import pytest

from app.performance_diagnostics import (
    begin_request_diagnostics,
    end_request_diagnostics,
    record_database_query,
)
from app.services.roll_phase_trace import RollPhaseTrace


def test_phase_trace_reports_sql_and_non_sql_wall_separately(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stage totals are derived from existing counters, without new SQL."""
    token = begin_request_diagnostics(route="/api/v1/roll/")
    try:
        with patch(
            "app.services.roll_phase_trace.time.perf_counter",
            side_effect=[100.0, 100.005, 100.011, 100.012],
        ):
            trace = RollPhaseTrace()
            record_database_query(2.0)
            trace.mark("eligibility")
            record_database_query(4.0)
            trace.mark("candidate_pool")
            with caplog.at_level(logging.INFO, logger="app.api.roll"):
                trace.emit(logging.getLogger("app.api.roll"))
    finally:
        end_request_diagnostics(token)

    summary = caplog.text
    assert "roll.phase_timing" in summary
    assert "total_ms=12.00" in summary
    assert "sql_ms=6.00" in summary
    assert "non_sql_wall_ms=6.00" in summary
    assert "queries=2" in summary
    assert "eligibility:5.00/2.00/1" in summary
    assert "candidate_pool:6.00/4.00/1" in summary
    assert "user_id=" not in summary


def test_phase_trace_has_no_sql_without_request_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing diagnostics simply yields zero queries, never an exception."""
    trace = RollPhaseTrace()
    trace.mark("session")
    with caplog.at_level(logging.INFO, logger="app.api.roll"):
        trace.emit(logging.getLogger("app.api.roll"))
    assert "queries=0" in caplog.text
    assert "sql_ms=0.00" in caplog.text
