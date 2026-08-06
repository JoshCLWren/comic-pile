"""Tests for process-level startup and cold-request diagnostics."""

from app.startup_diagnostics import (
    mark_startup_complete,
    next_request_snapshot,
    reset_startup_diagnostics_for_test,
)


def setup_function() -> None:
    """Reset process counters before each test."""
    reset_startup_diagnostics_for_test()


def test_first_request_is_cold_and_later_requests_are_warm() -> None:
    """Only the first request handled by a process is classified as cold."""
    first = next_request_snapshot()
    second = next_request_snapshot()

    assert first.invocation == 1
    assert first.cold is True
    assert first.process_age_ms >= 0
    assert second.invocation == 2
    assert second.cold is False
    assert second.process_age_ms >= first.process_age_ms


def test_startup_completion_is_recorded_once() -> None:
    """Startup completion remains stable when initialization calls it repeatedly."""
    first_duration = mark_startup_complete()
    second_duration = mark_startup_complete()
    snapshot = next_request_snapshot()

    assert first_duration >= 0
    assert second_duration == first_duration
    assert snapshot.startup_complete is True
    assert snapshot.startup_duration_ms == first_duration


def test_request_before_startup_completion_reports_incomplete_startup() -> None:
    """Requests observed before startup completion expose that distinction."""
    snapshot = next_request_snapshot()

    assert snapshot.startup_complete is False
    assert snapshot.startup_duration_ms is None
    assert snapshot.process_started_at_ns > 0
