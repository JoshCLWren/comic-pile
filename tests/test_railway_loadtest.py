"""Tests for the read-only Railway load-test harness."""

from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

from scripts.railway_loadtest import (
    ROUTES,
    RequestSample,
    request_once,
    resolve_routes,
    summarize,
    summarize_by_route,
    write_failure_log,
)


def test_resolve_safe_profile_requires_no_token() -> None:
    """The default profile contains only unauthenticated routes."""
    routes, token = resolve_routes("control-safe", "MISSING_BENCHMARK_TOKEN")

    assert [route.path for route in routes] == ["/health", "/api/auth/csrf"]
    assert token is None


def test_summarize_reports_percentiles_statuses_and_bytes() -> None:
    """Summary statistics include latency, throughput, statuses, and response bytes."""
    samples = [
        RequestSample("/health", 10.0, 200, 10, None),
        RequestSample("/health", 20.0, 200, 20, None),
        RequestSample("/api/auth/csrf", 30.0, 503, 30, None),
        RequestSample("/api/auth/csrf", 40.0, None, 0, "ReadTimeout"),
    ]

    result = summarize(samples, 2.0)
    latency = cast(dict[str, object], result["latency_ms"])

    assert result["requests"] == 4
    assert result["successful_requests"] == 2
    assert result["error_requests"] == 2
    assert result["requests_per_second"] == 2.0
    assert latency["p50"] == 20.0
    assert latency["p95"] == 40.0
    assert latency["p99"] == 40.0
    assert result["response_bytes"] == 60
    assert result["status_counts"] == {"200": 2, "503": 1, "transport_error": 1}


def test_summarize_counts_redirects_as_errors() -> None:
    """Summary success accounting matches request-level 2xx handling."""
    samples = [RequestSample("/health", 10.0, 302, 0, "HTTPStatus302")]

    result = summarize(samples, 1.0)

    assert result["successful_requests"] == 0
    assert result["error_requests"] == 1


def test_summarize_by_route_keeps_route_results_separate() -> None:
    """Combined scenarios expose independent statistics for every route."""
    samples = [
        RequestSample("/health", 10.0, 200, 10, None),
        RequestSample("/api/auth/csrf", 20.0, 200, 20, None),
    ]

    result = summarize_by_route(samples, 2.0)

    assert list(result) == ["/api/auth/csrf", "/health"]
    assert result["/api/auth/csrf"]["requests"] == 1
    assert result["/health"]["requests_per_second"] == 0.5


@pytest.mark.asyncio
async def test_request_id_propagates_and_non_2xx_failure_is_redacted() -> None:
    """Failed responses retain safe correlation data without credentials."""
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers["request_id"] = request.headers["X-Benchmark-Request-ID"]
        return httpx.Response(
            503,
            text='password="super-secret" bearer abc123',
            headers={"X-Request-ID": "railway-request", "Set-Cookie": "secret=hidden"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        sample = await request_once(
            client,
            ROUTES["health"],
            "https://example.test/health",
            {},
            32,
            4,
            9,
            "measurement",
            "paced_closed_loop",
            10.0,
        )

    assert sample.failure is not None
    assert seen_headers["request_id"] == sample.failure["request_id"]
    assert sample.error == "HTTPStatus503"
    assert str(sample.failure["timestamp"]).endswith("Z")
    assert sample.failure["route"] == "/health"
    assert sample.failure["http_status"] == 503
    assert "super-secret" not in str(sample.failure)
    assert "abc123" not in str(sample.failure)
    assert "set-cookie" not in str(sample.failure["response_headers"]).lower()


@pytest.mark.asyncio
async def test_transport_exception_records_correlation_fields() -> None:
    """Transport exceptions include type, timeout, and request identity."""
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection failed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await request_once(
            client,
            ROUTES["csrf"],
            "https://example.test/api/auth/csrf",
            {},
            32,
            2,
            3,
            "measurement",
            "paced_closed_loop",
            10.0,
        )

    assert sample.error == "ConnectTimeout"
    assert sample.failure is not None
    assert sample.failure["exception_type"] == "ConnectTimeout"
    assert sample.failure["failure_category"] == "transport_error"
    assert sample.failure["timeout_seconds"] == 10.0
    assert sample.failure["request_id"]


def test_failure_log_is_ndjson(tmp_path) -> None:
    """Failure logs contain one JSON object per line."""
    path = tmp_path / "failures.ndjson"
    failures = [{"request_id": "abc", "timestamp": "2026-01-01T00:00:00.000Z"}]

    write_failure_log(path, failures)

    assert [json.loads(line) for line in path.read_text().splitlines()] == failures
