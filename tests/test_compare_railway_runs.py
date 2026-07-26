"""Deterministic tests for repeated Railway result comparison."""

from __future__ import annotations

from argparse import Namespace
from typing import cast

import pytest

from scripts.compare_railway_runs import compare_documents
from scripts.railway_loadtest import ROUTES, build_metadata, default_output


def _mapping(value: object) -> dict[str, object]:
    """Narrow a JSON-like value for test setup and assertions."""
    return cast(dict[str, object], value)


def _groups(report: dict[str, object]) -> list[dict[str, object]]:
    """Narrow comparison groups for assertions."""
    return cast(list[dict[str, object]], report["groups"])


def _document(
    *,
    routes: list[str] | None = None,
    concurrency: list[int] | None = None,
    rps: float = 10.0,
    p50: float = 10.0,
    p95: float = 20.0,
    p99: float = 30.0,
    errors: int = 0,
) -> dict[str, object]:
    """Build a minimal valid result document for comparison tests."""
    selected_routes = routes or ["/health", "/api/auth/csrf"]
    selected_concurrency = concurrency or [1, 2]
    results: list[dict[str, object]] = []
    for level in selected_concurrency:
        route_summaries = {
            route: {
                "requests": 10,
                "successful_requests": 10 - errors,
                "error_requests": errors,
                "requests_per_second": rps,
                "latency_ms": {"p50": p50, "p95": p95, "p99": p99},
            }
            for route in selected_routes
        }
        results.append(
            {
                "concurrency": level,
                "summary": {
                    "requests": 20,
                    "successful_requests": 20 - errors,
                    "error_requests": errors,
                    "requests_per_second": rps,
                    "latency_ms": {"p50": p50, "p95": p95, "p99": p99},
                    "route_summaries": route_summaries,
                },
            }
        )
    return {
        "schema_version": 2,
        "metadata": {
            "routes": selected_routes,
            "concurrency_levels": selected_concurrency,
            "scheduling_mode": "paced_closed_loop",
            "interval_ms": 200.0,
            "warmup_seconds": 45.0,
            "measurement_seconds": 180.0,
            "workers": 2,
            "git_commit_sha": "abc123",
            "python_implementation": "CPython",
            "python_version": "3.14.2",
            "database_identity": "sha256:db",
            "railway_region": "us-east",
        },
        "results": results,
    }


def test_metadata_is_redacted_and_serializable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Metadata contains a database digest but never the database secret or URL."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://benchmark:super-secret@db.example.test/comicpile",
    )
    args = Namespace(
        run_set="control-results",
        interval_ms=200.0,
        warmup_seconds=45.0,
        duration_seconds=180.0,
        concurrency=[1, 2, 4],
    )

    metadata = build_metadata(args, (ROUTES["health"], ROUTES["csrf"]))
    serialized = str(metadata)

    assert str(metadata["database_identity"]).startswith("sha256:")
    assert "super-secret" not in serialized
    assert "postgresql+asyncpg" not in serialized
    assert metadata["run_set"] == "control-results"


def test_default_output_keeps_control_run_set_distinct() -> None:
    """Control-results files cannot collide with smoke or validation naming."""
    assert default_output("control-results").name.startswith("control-results-")


def test_compare_groups_routes_and_concurrency_and_calculates_variance() -> None:
    """Compatible runs produce combined and route-level statistics."""
    first = _document(rps=10.0, p50=10.0, p95=20.0, p99=30.0)
    second = _document(rps=12.0, p50=12.0, p95=22.0, p99=32.0)

    report = compare_documents([first, second])
    group = next(
        item for item in _groups(report) if item["scenario"] == "/health" and item["concurrency"] == 1
    )

    assert report["warnings"] == []
    assert group["run_count"] == 2
    rps = _mapping(group["rps"])
    assert rps["mean"] == 11.0
    assert rps["median"] == 11.0
    assert rps["minimum"] == 10.0
    assert rps["maximum"] == 12.0
    assert cast(float, rps["standard_deviation"]) > 0
    assert cast(float, rps["coefficient_of_variation"]) > 0


def test_compare_flags_errors_high_variance_and_p95_range() -> None:
    """Operational and statistical instability becomes visible in group warnings."""
    first = _document(rps=5.0, p95=10.0, errors=1)
    second = _document(rps=20.0, p95=30.0)

    report = compare_documents([first, second])
    group = next(item for item in _groups(report) if item["scenario"] == "combined")

    warnings = cast(list[str], group["warnings"])
    assert "nonzero error rate" in warnings
    assert any("coefficient of variation" in warning for warning in warnings)
    assert any("p95 range" in warning for warning in warnings)


def test_compare_flags_missing_route_and_concurrency() -> None:
    """Missing route and concurrency observations are global warnings."""
    first = _document()
    second = _document(routes=["/health"], concurrency=[1])

    report = compare_documents([first, second], allow_incompatible=True)

    warnings = cast(list[str], report["warnings"])
    assert any("missing expected routes" in warning for warning in warnings)
    assert any("missing expected concurrency" in warning for warning in warnings)


def test_compare_rejects_incompatible_configuration() -> None:
    """Runtime/configuration drift cannot silently become a control comparison."""
    first = _document()
    second = _document()
    _mapping(second["metadata"])["workers"] = 1

    with pytest.raises(ValueError, match="incompatible runs"):
        compare_documents([first, second])

    report = compare_documents([first, second], allow_incompatible=True)
    assert report["compatibility_warnings"]


def test_compare_reports_failures_by_route_and_exception() -> None:
    """Diagnostic comparisons preserve failure identity and timeout counts."""
    first = _document()
    second = _document()
    failure = {
        "timestamp": "2026-07-25T19:35:00.123Z",
        "route": "/health",
        "request_id": "request-1",
        "exception_type": "ConnectTimeout",
        "http_status": None,
        "elapsed_ms": 10096.0,
        "failure_category": "transport_error",
    }
    results = cast(list[dict[str, object]], second["results"])
    results[0]["failure_diagnostics"] = {
        "schema_version": 1,
        "warmup_failures": [{**failure, "request_id": "warmup-request"}],
        "measurement_failures": [failure],
        "failures": [{**failure, "request_id": "combined-request"}],
    }
    _mapping(results[0]["summary"])["error_requests"] = 1

    report = compare_documents([first, second])
    group = next(
        item
        for item in _groups(report)
        if item["scenario"] == "/health" and item["concurrency"] == 1
    )

    assert group["errors_by_route"] == {"/health": 1}
    assert group["errors_by_exception_type"] == {"ConnectTimeout": 1}
    assert group["timeout_count"] == 1
    assert group["failure_timestamps"] == ["2026-07-25T19:35:00.123Z"]
    assert group["failure_request_ids"] == ["request-1"]


def test_compare_handles_missing_latency_measurements() -> None:
    """Groups with no measured latency values report no data instead of crashing."""
    first = _document()
    second = _document()
    for document in (first, second):
        for result in cast(list[dict[str, object]], document["results"]):
            summary = _mapping(result["summary"])
            _mapping(summary["latency_ms"]).update({"p50": None, "p95": None, "p99": None, "max": None})

    report = compare_documents([first, second])
    group = next(item for item in _groups(report) if item["scenario"] == "combined")
    assert _mapping(group["p95_ms"])["median"] is None


def test_diagnostic_run_set_filter_rejects_control_files() -> None:
    """A diagnostic comparison cannot silently include ordinary control files."""
    first = _document()
    second = _document()
    first["metadata"]["run_set"] = "control-c32-diagnostic"
    second["metadata"]["run_set"] = "control-c32-diagnostic"
    first["run"] = {"run_set": "control-c32-diagnostic"}
    second["run"] = {"run_set": "control-c32-diagnostic"}

    report = compare_documents(
        [first, second],
        expected_run_set="control-c32-diagnostic",
    )

    assert report["run_count"] == 2

    with pytest.raises(ValueError, match="run-set mismatch"):
        compare_documents([_document(), second], expected_run_set="control-c32-diagnostic")
