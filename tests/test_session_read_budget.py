"""Focused tests for the session-read budget helper used by issue #700."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.benchmark_session_reads import Sample, summarize
from scripts.session_read_budget import (
    DEFAULT_PAYLOAD_TOLERANCE_BYTES,
    BudgetThresholds,
    EndpointBudget,
    PayloadBaseline,
    _build_payload_baseline,
    _detect_payload_regression,
    _percentile,
    evaluate_endpoint,
    evaluate_report,
    render_budget_report,
)


def _build_summary(
    *,
    endpoint: str,
    first_ms: float,
    warm_ms_list: list[float],
    first_bytes: int,
    warm_bytes_list: list[int],
) -> dict[str, Any]:
    """Build a benchmark summary dict matching the canonical harness shape."""
    samples: list[Sample] = []
    samples.append(
        Sample(
            endpoint=endpoint,
            iteration=1,
            elapsed_ms=first_ms,
            status=200,
            response_bytes=first_bytes,
            request_id="r-first",
            app_cache="MISS",
            db_queries=8,
            server_timing="app;dur=first",
        )
    )
    for index, (elapsed, body_bytes) in enumerate(
        zip(warm_ms_list, warm_bytes_list, strict=True), start=2
    ):
        samples.append(
            Sample(
                endpoint=endpoint,
                iteration=index,
                elapsed_ms=elapsed,
                status=200,
                response_bytes=body_bytes,
                request_id=f"r-warm-{index}",
                app_cache="HIT",
                db_queries=0,
                server_timing=f"app;dur={elapsed}",
            )
        )
    return summarize(samples)


def test_percentile_returns_linear_interpolation() -> None:
    """Verify percentile interpolates between adjacent samples."""
    assert _percentile([10.0, 20.0, 30.0, 40.0], 50.0) == 25.0
    assert _percentile([10.0, 20.0, 30.0, 40.0], 100.0) == 40.0
    assert _percentile([10.0, 20.0, 30.0, 40.0], 0.0) == 10.0


def test_percentile_rejects_empty_input() -> None:
    """Verify percentile raises on an empty sample list."""
    with pytest.raises(ValueError, match="at least one value"):
        _percentile([], 50.0)


def test_build_payload_baseline_applies_tolerance() -> None:
    """Verify the payload baseline widens by the default tolerance in both directions."""
    baseline = _build_payload_baseline(1000, 1200)
    assert baseline == PayloadBaseline(
        min_bytes=1000 - DEFAULT_PAYLOAD_TOLERANCE_BYTES,
        max_bytes=1200 + DEFAULT_PAYLOAD_TOLERANCE_BYTES,
    )


def test_build_payload_baseline_clamps_minimum_at_zero() -> None:
    """Verify the baseline floor never drops below zero bytes."""
    baseline = _build_payload_baseline(0, 50)
    assert baseline.min_bytes == 0


def test_evaluate_endpoint_marks_first_observed_out_of_budget() -> None:
    """Verify cold latency exceeding the threshold marks the cold budget as failed."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=1800.0,
        warm_ms_list=[150.0, 170.0, 160.0],
        first_bytes=1500,
        warm_bytes_list=[1200, 1200, 1200],
    )

    budget = evaluate_endpoint(summary)

    assert isinstance(budget, EndpointBudget)
    assert budget.endpoint == "/api/v1/sessions/current/"
    assert budget.first_observed_ms == 1800.0
    assert budget.first_observed_within_budget is False
    assert budget.steady_state_median_within_budget is True
    assert budget.steady_state_p95_within_budget is True


def test_evaluate_endpoint_marks_warm_p95_out_of_budget() -> None:
    """Verify warm p95 exceeding the threshold marks the warm budget as failed."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=400.0,
        warm_ms_list=[150.0, 200.0, 600.0],
        first_bytes=1100,
        warm_bytes_list=[1100, 1100, 1100],
    )

    budget = evaluate_endpoint(
        summary,
        thresholds=BudgetThresholds(
            first_observed_ms=1500.0,
            steady_state_p95_ms=300.0,
            steady_state_median_ms=300.0,
        ),
    )

    assert budget.steady_state_p95_within_budget is False
    assert budget.steady_state_median_within_budget is True
    assert budget.first_observed_within_budget is True


def test_evaluate_endpoint_handles_single_sample_run() -> None:
    """Verify a single-sample run records undefined steady-state with a note."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=500.0,
        warm_ms_list=[],
        first_bytes=1000,
        warm_bytes_list=[],
    )

    budget = evaluate_endpoint(summary)

    assert budget.first_observed_ms == 500.0
    assert budget.steady_state_median_ms == 500.0
    assert budget.steady_state_p95_ms == 500.0
    assert any("steady-state budget is undefined" in note for note in budget.notes)


def test_evaluate_endpoint_flags_first_observed_below_warm_median() -> None:
    """Verify anomalous warm-up costs above first-observed latency are surfaced."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=80.0,
        warm_ms_list=[200.0, 250.0, 300.0],
        first_bytes=1000,
        warm_bytes_list=[1000, 1000, 1000],
    )

    budget = evaluate_endpoint(summary)

    assert any("deployment idleness actually produced a cold path" in note for note in budget.notes)


def test_evaluate_report_aggregates_three_endpoints() -> None:
    """Verify multi-endpoint reports produce per-endpoint budgets and aggregate counts."""
    current_summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=500.0,
        warm_ms_list=[150.0, 170.0, 160.0],
        first_bytes=1000,
        warm_bytes_list=[900, 900, 900],
    )
    history_first = _build_summary(
        endpoint="/api/v1/sessions/?page_size=50",
        first_ms=1800.0,
        warm_ms_list=[400.0, 420.0, 410.0],
        first_bytes=4000,
        warm_bytes_list=[3800, 3800, 3800],
    )

    report = evaluate_report(
        {
            "summaries": [current_summary, history_first],
        },
        deployment_source="local",
    )

    assert [budget.endpoint for budget in report.budgets] == [
        "/api/v1/sessions/current/",
        "/api/v1/sessions/?page_size=50",
    ]
    assert report.summary == {
        "endpoints_evaluated": 2,
        "cold_within_budget": 2,
        "warm_median_within_budget": 2,
        "warm_p95_within_budget": 2,
        "payload_within_baseline": 2,
    }
    assert report.deployment_source == "local"
    assert "/api/v1/sessions/current/" in report.thresholds
    assert "/api/v1/sessions/?page_size=50" in report.payload_baselines


def test_evaluate_report_reports_empty_summaries() -> None:
    """Verify a benchmark report with no summaries raises a clear error."""
    with pytest.raises(ValueError, match="no summaries to evaluate"):
        evaluate_report({"summaries": []}, deployment_source="local")


def test_render_budget_report_is_json_serializable() -> None:
    """Verify the render output is round-trippable through json."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=200.0,
        warm_ms_list=[100.0, 120.0, 110.0],
        first_bytes=900,
        warm_bytes_list=[800, 800, 800],
    )
    report = evaluate_report({"summaries": [summary]}, deployment_source="preview")

    rendered = render_budget_report(report)
    payload = json.dumps(rendered, indent=2, sort_keys=True)
    reparsed = json.loads(payload)

    assert reparsed["deployment_source"] == "preview"
    assert reparsed["budgets"][0]["endpoint"] == "/api/v1/sessions/current/"
    assert reparsed["summary"]["endpoints_evaluated"] == 1


def test_detect_payload_regression_emits_note_when_payload_grows() -> None:
    """Verify a regression exceeding the tolerance is surfaced as a note."""
    current_budget = EndpointBudget(
        endpoint="/api/v1/sessions/current/",
        first_observed_ms=200.0,
        steady_state_median_ms=100.0,
        steady_state_p95_ms=150.0,
        steady_state_max_ms=200.0,
        response_bytes_min=1000,
        response_bytes_max=1500,
        db_queries_reported=4,
        cache_states={"HIT": 3, "MISS": 1},
        first_observed_within_budget=True,
        steady_state_median_within_budget=True,
        steady_state_p95_within_budget=True,
        payload_within_baseline=True,
        notes=(),
    )
    previous = [
        {
            "endpoint": "/api/v1/sessions/current/",
            "response_bytes_max": 1100,
        }
    ]

    notes = _detect_payload_regression(previous, [current_budget], tolerance_bytes=100)

    assert len(notes) == 1
    assert "payload max grew from 1100 to 1500" in notes[0]
    assert "+400" in notes[0]


def test_detect_payload_regression_is_silent_within_tolerance() -> None:
    """Verify regressions within tolerance produce no note."""
    current_budget = EndpointBudget(
        endpoint="/api/v1/sessions/current/",
        first_observed_ms=200.0,
        steady_state_median_ms=100.0,
        steady_state_p95_ms=150.0,
        steady_state_max_ms=200.0,
        response_bytes_min=1000,
        response_bytes_max=1100,
        db_queries_reported=4,
        cache_states={"HIT": 3, "MISS": 1},
        first_observed_within_budget=True,
        steady_state_median_within_budget=True,
        steady_state_p95_within_budget=True,
        payload_within_baseline=True,
        notes=(),
    )
    previous = [{"endpoint": "/api/v1/sessions/current/", "response_bytes_max": 1000}]

    notes = _detect_payload_regression(previous, [current_budget], tolerance_bytes=200)

    assert notes == []


def test_detect_payload_regression_ignores_unknown_endpoints() -> None:
    """Verify endpoints without a previous baseline are skipped silently."""
    current_budget = EndpointBudget(
        endpoint="/api/v1/sessions/current/",
        first_observed_ms=200.0,
        steady_state_median_ms=100.0,
        steady_state_p95_ms=150.0,
        steady_state_max_ms=200.0,
        response_bytes_min=1000,
        response_bytes_max=1000,
        db_queries_reported=1,
        cache_states={"MISS": 1},
        first_observed_within_budget=True,
        steady_state_median_within_budget=True,
        steady_state_p95_within_budget=True,
        payload_within_baseline=True,
        notes=(),
    )

    assert _detect_payload_regression([], [current_budget]) == []


def test_cli_evaluate_benchmark_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the command-line entrypoint writes a budget artifact for a synthetic report."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=300.0,
        warm_ms_list=[120.0, 130.0, 125.0],
        first_bytes=900,
        warm_bytes_list=[800, 800, 800],
    )
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "summaries": [summary],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "budget.json"

    from scripts.session_read_budget import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "session_read_budget.py",
            "--benchmark-report",
            str(benchmark_path),
            "--deployment-source",
            "production",
            "--output",
            str(output_path),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    rendered = json.loads(output_path.read_text(encoding="utf-8"))
    assert rendered["deployment_source"] == "production"
    assert rendered["budgets"][0]["endpoint"] == "/api/v1/sessions/current/"
    assert rendered["summary"]["endpoints_evaluated"] == 1


def test_cli_evaluate_benchmark_report_detects_payload_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the CLI surfaces payload regressions when a previous budget is provided."""
    summary = _build_summary(
        endpoint="/api/v1/sessions/current/",
        first_ms=300.0,
        warm_ms_list=[120.0, 130.0, 125.0],
        first_bytes=1500,
        warm_bytes_list=[1500, 1500, 1500],
    )
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps({"summaries": [summary]}),
        encoding="utf-8",
    )
    previous_path = tmp_path / "previous.json"
    previous_path.write_text(
        json.dumps(
            {
                "budgets": [
                    {
                        "endpoint": "/api/v1/sessions/current/",
                        "response_bytes_max": 1100,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "budget.json"

    from scripts.session_read_budget import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "session_read_budget.py",
            "--benchmark-report",
            str(benchmark_path),
            "--deployment-source",
            "production",
            "--previous-budget",
            str(previous_path),
            "--output",
            str(output_path),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    rendered = json.loads(output_path.read_text(encoding="utf-8"))
    assert any("grew from 1100 to 1500" in note for note in rendered["notes"])
