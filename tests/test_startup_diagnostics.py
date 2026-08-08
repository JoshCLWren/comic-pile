"""Tests for process-level startup and cold-request diagnostics."""

from app.startup_diagnostics import (
    mark_application_created,
    mark_application_import_complete,
    mark_startup_complete,
    next_request_snapshot,
    reset_startup_diagnostics_for_test,
    startup_event_snapshot,
)


def setup_function() -> None:
    """Reset process counters before each test.

    Args:
        None.

    Returns:
        None.
    """
    reset_startup_diagnostics_for_test()


def test_first_request_is_cold_and_later_requests_are_warm() -> None:
    """Only the first request handled by a process is classified as cold.

    Args:
        None.

    Returns:
        None.
    """
    first = next_request_snapshot()
    second = next_request_snapshot()

    assert first.invocation == 1
    assert first.cold is True
    assert first.process_age_ms >= 0
    assert second.invocation == 2
    assert second.cold is False
    assert second.process_age_ms >= first.process_age_ms


def test_startup_event_does_not_consume_first_request() -> None:
    """Startup logging must not turn the first HTTP request into a warm request.

    Args:
        None.

    Returns:
        None.
    """
    mark_application_import_complete()
    mark_application_created()
    mark_startup_complete()

    startup = startup_event_snapshot()
    first = next_request_snapshot()

    assert startup.invocation == 0
    assert startup.cold is False
    assert first.invocation == 1
    assert first.cold is True


def test_startup_snapshot_decomposes_measurable_phases() -> None:
    """Import, app creation, and lifespan phases are exposed when their markers exist.

    Args:
        None.

    Returns:
        None.
    """
    mark_application_import_complete()
    mark_application_created()
    total = mark_startup_complete()
    snapshot = startup_event_snapshot()

    assert total >= 0
    assert snapshot.startup_complete is True
    assert snapshot.startup_duration_ms == total
    assert snapshot.application_import_ms is not None
    assert snapshot.application_creation_ms is not None
    assert snapshot.lifespan_ms is not None
    assert snapshot.application_import_ms >= 0
    assert snapshot.application_creation_ms >= 0
    assert snapshot.lifespan_ms >= 0
    startup_duration_ms = snapshot.startup_duration_ms
    assert startup_duration_ms is not None
    assert startup_duration_ms <= snapshot.process_age_ms


def test_request_before_startup_completion_reports_unknown_phases() -> None:
    """Missing phase markers remain explicit instead of inventing proxy timings.

    Args:
        None.

    Returns:
        None.
    """
    snapshot = next_request_snapshot()

    assert snapshot.startup_complete is False
    assert snapshot.startup_duration_ms is None
    assert snapshot.application_import_ms is None
    assert snapshot.application_creation_ms is None
    assert snapshot.lifespan_ms is None
    assert snapshot.process_started_at_ns > 0
