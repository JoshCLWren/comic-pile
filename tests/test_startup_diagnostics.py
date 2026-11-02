"""Tests for process-level startup and cold-request diagnostics."""

from time import process_time
from types import SimpleNamespace

import pytest

import app.startup_diagnostics as diagnostics
from app.startup_diagnostics import (
    mark_heavy_init_complete,
    mark_heavy_init_started,
    mark_lifespan_started,
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
    mark_lifespan_started()
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


def test_worker_idle_age_does_not_inflate_readiness_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 300-second pause between app creation and lifespan is not startup work."""
    monkeypatch.setattr(diagnostics, "_PROCESS_STARTED_AT", 1.0)
    times = iter((1.10, 1.16, 301.16, 301.30, 301.31, 360.0))
    monkeypatch.setattr(
        diagnostics,
        "time",
        SimpleNamespace(perf_counter=lambda: next(times), process_time=process_time),
    )

    mark_application_import_complete()
    mark_application_created()
    mark_lifespan_started()
    observed_ms = mark_startup_complete()
    snapshot = startup_event_snapshot()

    # Import 100 ms + app creation 60 ms + lifespan 140 ms.
    assert observed_ms == pytest.approx(300.0)
    assert snapshot.startup_duration_ms == pytest.approx(300.0)
    assert snapshot.application_import_ms == pytest.approx(100.0)
    assert snapshot.application_creation_ms == pytest.approx(60.0)
    assert snapshot.lifespan_ms == pytest.approx(140.0)
    # These are process-age diagnostics, not readiness violations.
    assert snapshot.process_to_startup_ms == pytest.approx(300_300.0)
    assert snapshot.process_age_ms == pytest.approx(359_000.0)
    assert snapshot.startup_cpu_ms is not None


def test_heavy_init_reports_operation_duration_not_worker_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred DB work is timed from its own entry, even after a long idle."""
    monkeypatch.setattr(diagnostics, "_PROCESS_STARTED_AT", 1.0)
    times = iter((450.0, 450.4, 500.0))
    monkeypatch.setattr(
        diagnostics,
        "time",
        SimpleNamespace(perf_counter=lambda: next(times), process_time=process_time),
    )

    mark_heavy_init_started()
    duration_ms = mark_heavy_init_complete()
    snapshot = startup_event_snapshot()

    assert duration_ms == pytest.approx(400.0)
    assert snapshot.heavy_init_duration_ms == pytest.approx(400.0)
    assert snapshot.heavy_init_process_age_ms == pytest.approx(449_400.0)


def test_heavy_init_retry_resets_its_start_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed initialization attempt cannot charge idle time to a retry."""
    monkeypatch.setattr(diagnostics, "_PROCESS_STARTED_AT", 1.0)
    times = iter((100.0, 300.0, 300.2))
    monkeypatch.setattr(
        diagnostics,
        "time",
        SimpleNamespace(perf_counter=lambda: next(times), process_time=process_time),
    )

    mark_heavy_init_started()  # First attempt failed without completing.
    mark_heavy_init_started()  # Next attempt starts after idle.
    assert mark_heavy_init_complete() == pytest.approx(200.0)
