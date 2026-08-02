"""Focused tests for the session-read benchmark harness."""
from scripts.benchmark_session_reads import (
    Sample,
    _build_endpoints,
    _parse_db_queries,
    summarize,
)


def test_parse_db_queries_handles_missing_and_invalid_headers() -> None:
    """Verify the header parser correctly handles missing, empty, invalid, and valid values."""
    assert _parse_db_queries(None) is None
    assert _parse_db_queries("") is None
    assert _parse_db_queries("unknown") is None
    assert _parse_db_queries("7") == 7


def test_build_endpoints_includes_optional_later_history_page() -> None:
    """Verify endpoint construction includes the optional later-History-page entry."""
    assert _build_endpoints(25, None) == [
        "/api/sessions/current/",
        "/api/sessions/?page_size=25",
    ]
    assert _build_endpoints(25, "2026-08-01T12:00:00+00:00,42") == [
        "/api/sessions/current/",
        "/api/sessions/?page_size=25",
        "/api/sessions/?page_size=25&page_token=2026-08-01T12%3A00%3A00%2B00%3A00%2C42",
    ]


def test_summarize_separates_first_observed_from_steady_state() -> None:
    """Verify summarize splits first-observed evidence from steady-state aggregate."""
    samples = [
        Sample(
            endpoint="/api/sessions/current/",
            iteration=1,
            elapsed_ms=40.0,
            status=200,
            response_bytes=1000,
            request_id="req-1",
            app_cache="MISS",
            db_queries=8,
            server_timing=None,
        ),
        Sample(
            endpoint="/api/sessions/current/",
            iteration=2,
            elapsed_ms=20.0,
            status=200,
            response_bytes=900,
            request_id="req-2",
            app_cache="HIT",
            db_queries=0,
            server_timing="app;dur=19.5",
        ),
        Sample(
            endpoint="/api/sessions/current/",
            iteration=3,
            elapsed_ms=30.0,
            status=200,
            response_bytes=950,
            request_id="req-3",
            app_cache="HIT",
            db_queries=0,
            server_timing="app;dur=29.5",
        ),
    ]

    assert summarize(samples) == {
        "endpoint": "/api/sessions/current/",
        "first_observed": {
            "elapsed_ms": 40.0,
            "status": 200,
            "response_bytes": 1000,
            "request_id": "req-1",
            "app_cache": "MISS",
            "db_queries": 8,
            "server_timing": None,
        },
        "steady_state": {
            "samples": 2,
            "elapsed_ms": {"min": 20.0, "median": 25.0, "max": 30.0, "mean": 25.0},
            "response_bytes": {"min": 900, "max": 950},
            "db_queries": {"reported_samples": 2, "min": 0, "max": 0},
            "cache_states": {"HIT": 2},
            "missing_server_timing": 0,
        },
        "all_recorded": {
            "samples": 3,
            "elapsed_ms": {"min": 20.0, "median": 30.0, "max": 40.0, "mean": 30.0},
            "response_bytes": {"min": 900, "max": 1000},
            "db_queries": {"reported_samples": 3, "min": 0, "max": 8},
            "cache_states": {"MISS": 1, "HIT": 2},
            "missing_server_timing": 1,
        },
    }


def test_summarize_handles_a_single_recorded_sample() -> None:
    """Verify summarize correctly reports a single-sample run with no steady state."""
    sample = Sample(
        endpoint="/api/sessions/?page_size=50",
        iteration=1,
        elapsed_ms=15.0,
        status=200,
        response_bytes=500,
        request_id=None,
        app_cache=None,
        db_queries=None,
        server_timing=None,
    )

    summary = summarize([sample])

    assert summary["first_observed"]["elapsed_ms"] == 15.0
    assert summary["steady_state"] is None
    assert summary["all_recorded"]["samples"] == 1
