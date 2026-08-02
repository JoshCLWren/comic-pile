from scripts.benchmark_session_reads import (
    Sample,
    _build_endpoints,
    _parse_db_queries,
    summarize,
)


def test_parse_db_queries_handles_missing_and_invalid_headers() -> None:
    assert _parse_db_queries(None) is None
    assert _parse_db_queries("") is None
    assert _parse_db_queries("unknown") is None
    assert _parse_db_queries("7") == 7


def test_build_endpoints_includes_optional_later_history_page() -> None:
    assert _build_endpoints(25, None) == [
        "/api/sessions/current/",
        "/api/sessions/?page_size=25",
    ]
    assert _build_endpoints(25, "2026-08-01T12:00:00+00:00,42") == [
        "/api/sessions/current/",
        "/api/sessions/?page_size=25",
        "/api/sessions/?page_size=25&page_token=2026-08-01T12%3A00%3A00%2B00%3A00%2C42",
    ]


def test_summarize_reports_latency_payload_query_and_header_evidence() -> None:
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
    ]

    assert summarize(samples) == {
        "endpoint": "/api/sessions/current/",
        "samples": 2,
        "elapsed_ms": {"min": 20.0, "median": 30.0, "max": 40.0, "mean": 30.0},
        "response_bytes": {"min": 900, "max": 1000},
        "db_queries": {"reported_samples": 2, "min": 0, "max": 8},
        "cache_states": {"MISS": 1, "HIT": 1},
        "missing_server_timing": 1,
    }
