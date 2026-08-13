"""Establish cold/first and warm/steady-state budgets from session-read benchmark evidence.

The benchmark harness in ``scripts/benchmark_session_reads.py`` records first-observed
and steady-state HTTP measurements for the current-session and History endpoints.
This module consumes the harness's JSON output, derives explicit per-endpoint budgets,
and detects payload-size regressions against a baseline.

The output is the canonical budget artifact for issue #700. It distinguishes cold
(first-observed after deployment idle) from warm (steady-state) budgets, separates
the current-session endpoint from the History first/later pages, and surfaces any
payload-size regression honestly.

Production evidence remains gated on the dedicated production account provisioned by
issue #832. Until authenticated production samples exist, this module accepts
authenticated dev, preview, or local evidence and labels every artifact with the
deployment source so the budgets can be re-derived when the production credentials
arrive without changing the harness or contract.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class BudgetThresholds:
    """Acceptable per-endpoint latency ceilings in milliseconds."""

    first_observed_ms: float
    steady_state_p95_ms: float
    steady_state_median_ms: float


@dataclass(frozen=True)
class PayloadBaseline:
    """Reference payload sizes in bytes used for regression detection."""

    min_bytes: int
    max_bytes: int


@dataclass(frozen=True)
class EndpointBudget:
    """Computed budget verdict for a single endpoint."""

    endpoint: str
    first_observed_ms: float
    steady_state_median_ms: float
    steady_state_p95_ms: float
    steady_state_max_ms: float
    response_bytes_min: int
    response_bytes_max: int
    db_queries_reported: int
    cache_states: dict[str, int]
    first_observed_within_budget: bool
    steady_state_median_within_budget: bool
    steady_state_p95_within_budget: bool
    payload_within_baseline: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class BudgetReport:
    """Top-level budget artifact for the current-session and History endpoints."""

    deployment_source: str
    generated_at: str
    source_report_path: str | None
    thresholds: dict[str, dict[str, float]]
    payload_baselines: dict[str, dict[str, int]]
    budgets: list[EndpointBudget]
    summary: dict[str, int]
    notes: tuple[str, ...]


DEFAULT_FIRST_OBSERVED_THRESHOLD_MS = 1500.0
DEFAULT_STEADY_STATE_P95_THRESHOLD_MS = 500.0
DEFAULT_STEADY_STATE_MEDIAN_THRESHOLD_MS = 250.0

DEFAULT_PAYLOAD_TOLERANCE_BYTES = 256


_DEFAULT_THRESHOLDS: dict[str, BudgetThresholds] = {
    "/api/v1/sessions/current/": BudgetThresholds(
        first_observed_ms=1200.0,
        steady_state_p95_ms=400.0,
        steady_state_median_ms=200.0,
    ),
    "/api/v1/sessions/?page_size=50": BudgetThresholds(
        first_observed_ms=2500.0,
        steady_state_p95_ms=1200.0,
        steady_state_median_ms=600.0,
    ),
}


def _default_thresholds_for(endpoint: str) -> BudgetThresholds:
    """Return the default thresholds for a known endpoint, or generic ceilings."""
    if endpoint in _DEFAULT_THRESHOLDS:
        return _DEFAULT_THRESHOLDS[endpoint]
    return BudgetThresholds(
        first_observed_ms=DEFAULT_FIRST_OBSERVED_THRESHOLD_MS,
        steady_state_p95_ms=DEFAULT_STEADY_STATE_P95_THRESHOLD_MS,
        steady_state_median_ms=DEFAULT_STEADY_STATE_MEDIAN_THRESHOLD_MS,
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Return the linear-interpolated percentile of ``values``.

    Args:
        values: Non-empty list of numeric samples.
        percentile: Target percentile in the inclusive range ``[0.0, 100.0]``.

    Returns:
        Interpolated percentile value. Uses the same definition as
        ``statistics.quantiles(n=100)`` so 95 corresponds to the 95th percentile.
    """
    if not values:
        raise ValueError("percentile requires at least one value")
    if percentile <= 0:
        return min(values)
    if percentile >= 100:
        return max(values)
    ordered = sorted(values)
    rank = (percentile / 100) * (len(ordered) - 1)
    lower = int(rank)
    fraction = rank - lower
    if lower + 1 >= len(ordered):
        return ordered[lower]
    return ordered[lower] + (ordered[lower + 1] - ordered[lower]) * fraction


def _build_payload_baseline(
    response_bytes_min: int,
    response_bytes_max: int,
) -> PayloadBaseline:
    """Build a baseline range centered on the observed maximum with a small tolerance.

    Args:
        response_bytes_min: Smallest observed response body size.
        response_bytes_max: Largest observed response body size.

    Returns:
        Baseline range used to detect regressions in future samples.
    """
    return PayloadBaseline(
        min_bytes=max(response_bytes_min - DEFAULT_PAYLOAD_TOLERANCE_BYTES, 0),
        max_bytes=response_bytes_max + DEFAULT_PAYLOAD_TOLERANCE_BYTES,
    )


def evaluate_endpoint(
    summary: dict[str, Any],
    *,
    thresholds: BudgetThresholds | None = None,
    payload_baseline: PayloadBaseline | None = None,
) -> EndpointBudget:
    """Evaluate one benchmark summary against thresholds and the payload baseline.

    Args:
        summary: Per-endpoint summary produced by
            ``scripts.benchmark_session_reads.summarize``.
        thresholds: Optional latency ceilings; defaults to known per-endpoint budgets.
        payload_baseline: Optional payload-size baseline; derived from this run when
            ``None`` so the first evaluation establishes the budget reference.

    Returns:
        Computed per-endpoint budget verdict including pass/fail flags and any
        notes that explain cold/warm classification or sample scarcity.
    """
    endpoint = str(summary["endpoint"])
    first = summary["first_observed"]
    steady = summary["steady_state"]
    all_recorded = summary["all_recorded"]

    first_ms = float(first["elapsed_ms"])
    response_min = int(all_recorded["response_bytes"]["min"])
    response_max = int(all_recorded["response_bytes"]["max"])

    notes: list[str] = []

    if steady is None:
        notes.append(
            "Only one sample was recorded; steady-state budget is undefined. "
            "Re-run with --iterations >= 3 to establish warm budgets."
        )
        steady_median = first_ms
        steady_p95 = first_ms
        steady_max = first_ms
    else:
        elapsed = steady["elapsed_ms"]
        steady_median = float(elapsed["median"])
        steady_max = float(elapsed["max"])
        steady_elapsed = [
            steady_median,
            float(elapsed["min"]),
            float(elapsed["max"]),
            float(elapsed["mean"]),
        ]
        steady_p95 = _percentile(steady_elapsed, 95.0)
        if first_ms < steady_median:
            notes.append(
                "First-observed latency is below the steady-state median; verify "
                "that deployment idleness actually produced a cold path."
            )

    active_thresholds = thresholds or _default_thresholds_for(endpoint)
    active_baseline = payload_baseline or _build_payload_baseline(response_min, response_max)

    return EndpointBudget(
        endpoint=endpoint,
        first_observed_ms=round(first_ms, 3),
        steady_state_median_ms=round(steady_median, 3),
        steady_state_p95_ms=round(steady_p95, 3),
        steady_state_max_ms=round(steady_max, 3),
        response_bytes_min=response_min,
        response_bytes_max=response_max,
        db_queries_reported=int(all_recorded["db_queries"]["reported_samples"]),
        cache_states=dict(all_recorded["cache_states"]),
        first_observed_within_budget=first_ms <= active_thresholds.first_observed_ms,
        steady_state_median_within_budget=steady_median <= active_thresholds.steady_state_median_ms,
        steady_state_p95_within_budget=steady_p95 <= active_thresholds.steady_state_p95_ms,
        payload_within_baseline=(
            active_baseline.min_bytes <= response_min and response_max <= active_baseline.max_bytes
        ),
        notes=tuple(notes),
    )


def evaluate_report(
    report: dict[str, Any],
    *,
    deployment_source: str,
    thresholds: dict[str, BudgetThresholds] | None = None,
    payload_baselines: dict[str, PayloadBaseline] | None = None,
) -> BudgetReport:
    """Evaluate every summary inside one benchmark report.

    Args:
        report: Parsed JSON output from ``scripts/benchmark_session_reads.py``.
        deployment_source: Free-form label such as ``"production"``, ``"preview"``,
            or ``"local"`` so the artifact honestly states where the evidence
            came from.
        thresholds: Optional per-endpoint latency ceilings overriding defaults.
        payload_baselines: Optional payload baselines overriding derived defaults.

    Returns:
        Aggregated budget artifact suitable for review, archival, or automated
        regression comparison.
    """
    summaries = report.get("summaries", [])
    if not summaries:
        raise ValueError("benchmark report contains no summaries to evaluate")

    active_thresholds = thresholds or {}
    active_baselines = payload_baselines or {}

    budgets: list[EndpointBudget] = []
    cold_pass = 0
    warm_median_pass = 0
    warm_p95_pass = 0
    payload_pass = 0

    for summary in summaries:
        endpoint = str(summary["endpoint"])
        budget = evaluate_endpoint(
            summary,
            thresholds=active_thresholds.get(endpoint),
            payload_baseline=active_baselines.get(endpoint),
        )
        budgets.append(budget)
        if budget.first_observed_within_budget:
            cold_pass += 1
        if budget.steady_state_median_within_budget:
            warm_median_pass += 1
        if budget.steady_state_p95_within_budget:
            warm_p95_pass += 1
        if budget.payload_within_baseline:
            payload_pass += 1

    rendered_thresholds = {
        endpoint: asdict(active_thresholds.get(endpoint) or _default_thresholds_for(endpoint))
        for endpoint in (budget.endpoint for budget in budgets)
    }
    rendered_baselines = {
        budget.endpoint: asdict(
            active_baselines.get(budget.endpoint)
            or _build_payload_baseline(budget.response_bytes_min, budget.response_bytes_max)
        )
        for budget in budgets
    }

    notes: tuple[str, ...] = (
        "Cold budget is set from the first-observed sample in each endpoint's "
        "isolated run; warm budget is set from the steady-state median and p95 "
        "of the remaining samples.",
    )

    return BudgetReport(
        deployment_source=deployment_source,
        generated_at=datetime.now(UTC).isoformat(),
        source_report_path=None,
        thresholds=rendered_thresholds,
        payload_baselines=rendered_baselines,
        budgets=budgets,
        summary={
            "endpoints_evaluated": len(budgets),
            "cold_within_budget": cold_pass,
            "warm_median_within_budget": warm_median_pass,
            "warm_p95_within_budget": warm_p95_pass,
            "payload_within_baseline": payload_pass,
        },
        notes=notes,
    )


def render_budget_report(budget_report: BudgetReport) -> dict[str, Any]:
    """Return a JSON-serializable dict representation of the budget report."""
    return {
        "deployment_source": budget_report.deployment_source,
        "generated_at": budget_report.generated_at,
        "source_report_path": budget_report.source_report_path,
        "thresholds": budget_report.thresholds,
        "payload_baselines": budget_report.payload_baselines,
        "budgets": [asdict(budget) for budget in budget_report.budgets],
        "summary": budget_report.summary,
        "notes": list(budget_report.notes),
    }


def _detect_payload_regression(
    previous_budgets: list[dict[str, Any]],
    current_budgets: list[EndpointBudget],
    tolerance_bytes: int = DEFAULT_PAYLOAD_TOLERANCE_BYTES,
) -> list[str]:
    """Compare current payload sizes against a previously archived budget artifact.

    Args:
        previous_budgets: Endpoint budget dicts from a prior run.
        current_budgets: Newly evaluated endpoint budgets for the same endpoints.
        tolerance_bytes: Allowed drift in bytes before the regression is reported.

    Returns:
        Human-readable notes describing any payload-size regression detected.
    """
    notes: list[str] = []
    previous_by_endpoint = {entry["endpoint"]: entry for entry in previous_budgets}
    for current in current_budgets:
        previous = previous_by_endpoint.get(current.endpoint)
        if previous is None:
            continue
        prev_max = int(previous["response_bytes_max"])
        if current.response_bytes_max > prev_max + tolerance_bytes:
            notes.append(
                f"{current.endpoint}: payload max grew from {prev_max} to "
                f"{current.response_bytes_max} bytes (+{current.response_bytes_max - prev_max})"
            )
    return notes


def main() -> int:
    """Parse arguments, evaluate the benchmark report, and print the budget JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-report", required=True, help="Path to benchmark JSON output")
    parser.add_argument(
        "--deployment-source",
        required=True,
        help="Free-form label describing where the benchmark evidence came from",
    )
    parser.add_argument("--output", help="Optional path to write the budget JSON")
    parser.add_argument(
        "--previous-budget",
        help="Optional prior budget JSON used for payload regression detection",
    )
    args = parser.parse_args()

    with open(args.benchmark_report, encoding="utf-8") as handle:
        report = json.load(handle)

    budget_report = evaluate_report(
        report,
        deployment_source=args.deployment_source,
    )

    if args.previous_budget:
        with open(args.previous_budget, encoding="utf-8") as handle:
            previous = json.load(handle)
        regression_notes = _detect_payload_regression(
            previous.get("budgets", []),
            budget_report.budgets,
        )
        if regression_notes:
            budget_report = BudgetReport(
                deployment_source=budget_report.deployment_source,
                generated_at=budget_report.generated_at,
                source_report_path=budget_report.source_report_path,
                thresholds=budget_report.thresholds,
                payload_baselines=budget_report.payload_baselines,
                budgets=budget_report.budgets,
                summary=budget_report.summary,
                notes=budget_report.notes + tuple(regression_notes),
            )

    rendered = json.dumps(render_budget_report(budget_report), indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
