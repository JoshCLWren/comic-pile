#!/usr/bin/env python3
"""Compare repeated ComicPile Railway load-test result documents."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

COMPARISON_SCHEMA_VERSION: Final[int] = 1
COMPATIBILITY_FIELDS: Final[tuple[str, ...]] = (
    "result_schema_version",
    "routes",
    "concurrency_levels",
    "scheduling_mode",
    "interval_ms",
    "warmup_seconds",
    "measurement_seconds",
    "workers",
    "git_commit_sha",
    "python_implementation",
    "python_version",
    "database_identity",
    "railway_region",
)


def _as_dict(value: object) -> dict[str, object]:
    """Narrow decoded JSON objects to string-keyed dictionaries."""
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _as_list(value: object) -> list[object]:
    """Narrow decoded JSON arrays to lists."""
    return list(value) if isinstance(value, list) else []


def _optional_float(value: object) -> float | None:
    """Convert numeric JSON values while preserving missing measurements."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _stats(values: list[float]) -> dict[str, float | None]:
    """Calculate summary statistics over per-run values."""
    if not values:
        return {
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
            "standard_deviation": None,
            "coefficient_of_variation": None,
        }
    mean = statistics.fmean(values)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "mean": mean,
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "standard_deviation": deviation,
        "coefficient_of_variation": deviation / mean if mean else None,
    }


def _config(document: dict[str, object]) -> dict[str, object]:
    """Extract comparable configuration from one result document."""
    metadata = _as_dict(document.get("metadata", {}))
    run = _as_dict(document.get("run", {}))
    return {
        "result_schema_version": document.get("schema_version"),
        "routes": metadata.get("routes", run.get("routes")),
        "concurrency_levels": metadata.get("concurrency_levels", run.get("concurrency")),
        "scheduling_mode": metadata.get("scheduling_mode"),
        "interval_ms": metadata.get("interval_ms", run.get("interval_ms")),
        "warmup_seconds": metadata.get("warmup_seconds", run.get("warmup_seconds")),
        "measurement_seconds": metadata.get("measurement_seconds", run.get("duration_seconds")),
        "workers": metadata.get("workers"),
        "git_commit_sha": metadata.get("git_commit_sha"),
        "python_implementation": metadata.get("python_implementation"),
        "python_version": metadata.get("python_version"),
        "database_identity": metadata.get("database_identity"),
        "railway_region": metadata.get("railway_region"),
    }


def _compatibility_warnings(documents: list[dict[str, object]]) -> list[str]:
    """Find configuration differences across documents."""
    baseline = _config(documents[0])
    warnings: list[str] = []
    for index, document in enumerate(documents[1:], start=2):
        current = _config(document)
        for field in COMPATIBILITY_FIELDS:
            if current[field] != baseline[field]:
                warnings.append(
                    f"run {index} differs for {field}: "
                    f"baseline={baseline[field]!r}, current={current[field]!r}"
                )
    return warnings


def _rows(
    document: dict[str, object],
) -> list[tuple[str, int, dict[str, object], dict[str, object]]]:
    """Flatten combined and route summaries into comparison rows."""
    rows: list[tuple[str, int, dict[str, object], dict[str, object]]] = []
    for result_value in _as_list(document.get("results", [])):
        result = _as_dict(result_value)
        concurrency = result.get("concurrency")
        summary = result.get("summary")
        if not isinstance(concurrency, int):
            continue
        summary = _as_dict(summary)
        if not summary:
            continue
        rows.append(("combined", concurrency, summary, result))
        route_summaries = _as_dict(summary.get("route_summaries", {}))
        for route, route_summary_value in route_summaries.items():
            route_summary = _as_dict(route_summary_value)
            if route_summary:
                rows.append((route, concurrency, route_summary, result))
    return rows


def _failures(result: dict[str, object], scenario: str) -> list[dict[str, object]]:
    """Return diagnostic failures for one result and scenario."""
    diagnostics = _as_dict(result.get("failure_diagnostics", {}))
    failures = _as_list(diagnostics.get("measurement_failures", diagnostics.get("failures", [])))
    return [
        _as_dict(failure)
        for failure in failures
        if isinstance(failure, dict)
        and (scenario == "combined" or _as_dict(failure).get("route") == scenario)
    ]


def _route_error_diagnostics(summary: dict[str, object], scenario: str) -> Counter[str]:
    """Return route-level error counts when detailed failures are unavailable."""
    if scenario != "combined":
        error_count = summary.get("error_requests")
        if isinstance(error_count, int) and error_count:
            return Counter({scenario: error_count})
        return Counter()
    diagnostics: Counter[str] = Counter()
    for route, route_summary_value in _as_dict(summary.get("route_summaries", {})).items():
        route_summary = _as_dict(route_summary_value)
        error_count = route_summary.get("error_requests")
        if isinstance(error_count, int) and error_count:
            diagnostics[route] = error_count
    return diagnostics


def compare_documents(
    documents: list[dict[str, object]],
    *,
    allow_incompatible: bool = False,
    expected_run_set: str | None = None,
) -> dict[str, object]:
    """Compare compatible result documents and return a machine-readable report."""
    if len(documents) < 2:
        raise ValueError("comparison requires at least two result files")
    compatibility_warnings = _compatibility_warnings(documents)
    if compatibility_warnings and not allow_incompatible:
        raise ValueError("incompatible runs:\n" + "\n".join(compatibility_warnings))
    run_set_warnings = []
    if expected_run_set is not None:
        for index, document in enumerate(documents, start=1):
            metadata = _as_dict(document.get("metadata", {}))
            run = _as_dict(document.get("run", {}))
            metadata_run_set = metadata.get("run_set")
            run_run_set = run.get("run_set")
            if metadata_run_set != expected_run_set or run_run_set != expected_run_set:
                run_set_warnings.append(
                    f"run {index} does not match expected run_set {expected_run_set!r}: "
                    f"metadata={metadata_run_set!r}, run={run_run_set!r}"
                )
        if run_set_warnings:
            raise ValueError("run-set mismatch:\n" + "\n".join(run_set_warnings))

    configurations = [_config(document) for document in documents]
    expected_routes = set(configurations[0].get("routes") or [])
    expected_concurrency = set(configurations[0].get("concurrency_levels") or [])
    grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
    for run_index, document in enumerate(documents, start=1):
        for scenario, concurrency, summary, result in _rows(document):
            grouped.setdefault((scenario, concurrency), []).append(
                {"run": run_index, "summary": summary, "result": result}
            )

    groups: list[dict[str, object]] = []
    for (scenario, concurrency), observations in sorted(grouped.items()):
        summaries = [_as_dict(item["summary"]) for item in observations]
        latencies = [_as_dict(summary["latency_ms"]) for summary in summaries]
        rps = [float(summary["requests_per_second"]) for summary in summaries]
        p50 = [value for latency in latencies if (value := _optional_float(latency.get("p50"))) is not None]
        p95 = [value for latency in latencies if (value := _optional_float(latency.get("p95"))) is not None]
        p99 = [value for latency in latencies if (value := _optional_float(latency.get("p99"))) is not None]
        maximum_latency: list[float] = []
        for latency in latencies:
            maximum = _optional_float(latency.get("max"))
            if maximum is None:
                maximum = _optional_float(latency.get("p99"))
            if maximum is not None:
                maximum_latency.append(maximum)
        total_requests = sum(int(summary["requests"]) for summary in summaries)
        total_errors = sum(int(summary["error_requests"]) for summary in summaries)
        failures = [
            failure
            for item in observations
            for failure in _failures(_as_dict(item["result"]), scenario)
        ]
        errors_by_route = Counter(str(failure.get("route")) for failure in failures)
        if not failures:
            for summary in summaries:
                errors_by_route.update(_route_error_diagnostics(summary, scenario))
        errors_by_exception = Counter(
            str(failure.get("exception_type") or "non_2xx") for failure in failures
        )
        timeout_count = sum(
            1
            for failure in failures
            if failure.get("exception_type") in {"ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"}
        )
        non_2xx_statuses = Counter(
            str(failure["http_status"])
            for failure in failures
            if failure.get("http_status") is not None
        )
        p95_range = max(p95) - min(p95) if p95 else None
        p95_median = statistics.median(p95) if p95 else None
        warnings: list[str] = []
        rps_stats = _stats(rps)
        if total_errors:
            warnings.append("nonzero error rate")
        cv = rps_stats["coefficient_of_variation"]
        if cv is not None and cv > 0.10:
            warnings.append(f"RPS coefficient of variation is {cv:.1%}")
        if p95_median is not None and p95_range is not None and p95_range > p95_median * 0.15:
            warnings.append(f"p95 range is {p95_range:.2f} ms ({p95_range / p95_median:.1%})")
        if len(observations) != len(documents):
            warnings.append(f"missing from {len(documents) - len(observations)} run(s)")
        groups.append(
            {
                "scenario": scenario,
                "concurrency": concurrency,
                "run_count": len(observations),
                "total_requests": total_requests,
                "total_errors": total_errors,
                "error_rate": total_errors / total_requests if total_requests else None,
                "rps": rps_stats,
                "p50_ms": _stats(p50),
                "p95_ms": _stats(p95),
                "p99_ms": _stats(p99),
                "maximum_latency_ms": _stats(maximum_latency),
                "observations": [
                    {
                        "run": item["run"],
                        "rps": summary["requests_per_second"],
                        "p50_ms": latency["p50"],
                        "p95_ms": latency["p95"],
                        "p99_ms": latency["p99"],
                        "maximum_latency_ms": latency.get("max"),
                        "errors": summary["error_requests"],
                    }
                    for item, summary, latency in zip(observations, summaries, latencies, strict=True)
                ],
                "errors_by_route": dict(sorted(errors_by_route.items())),
                "errors_by_exception_type": dict(sorted(errors_by_exception.items())),
                "failure_timestamps": [failure.get("timestamp") for failure in failures],
                "failure_request_ids": [failure.get("request_id") for failure in failures],
                "timeout_count": timeout_count,
                "non_2xx_status_distribution": dict(sorted(non_2xx_statuses.items())),
                "failures": failures,
                "warnings": warnings,
            }
        )

    actual_routes = {scenario for scenario, _ in grouped if scenario != "combined"}
    actual_concurrency = {concurrency for _, concurrency in grouped}
    global_warnings = list(compatibility_warnings)
    missing_routes = sorted(expected_routes - actual_routes)
    missing_concurrency = sorted(expected_concurrency - actual_concurrency)
    if missing_routes:
        global_warnings.append(f"missing expected routes: {missing_routes}")
    if missing_concurrency:
        global_warnings.append(f"missing expected concurrency levels: {missing_concurrency}")
    for run_index, document in enumerate(documents, start=1):
        run_rows = _rows(document)
        run_routes = {scenario for scenario, _, _, _ in run_rows if scenario != "combined"}
        run_concurrency = {concurrency for _, concurrency, _, _ in run_rows}
        run_missing_routes = sorted(expected_routes - run_routes)
        run_missing_concurrency = sorted(expected_concurrency - run_concurrency)
        if run_missing_routes:
            global_warnings.append(
                f"run {run_index} missing expected routes: {run_missing_routes}"
            )
        if run_missing_concurrency:
            global_warnings.append(
                f"run {run_index} missing expected concurrency levels: {run_missing_concurrency}"
            )
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "run_count": len(documents),
        "compatibility_warnings": compatibility_warnings,
        "warnings": global_warnings,
        "run_set_warnings": run_set_warnings,
        "groups": groups,
    }


def _print_report(report: dict[str, object]) -> None:
    """Print a compact comparison report."""
    warnings = _as_list(report["warnings"])
    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("No compatibility or global warnings.")
    for group_value in _as_list(report["groups"]):
        group = _as_dict(group_value)
        rps = _as_dict(group["rps"])
        p95 = _as_dict(group["p95_ms"])
        rps_median = rps.get("median")
        rps_cv = rps.get("coefficient_of_variation")
        p95_median = p95.get("median")
        group_warnings = _as_list(group["warnings"])
        warning_text = f" warnings={group_warnings}" if group_warnings else ""
        print(
            f"scenario={group['scenario']} c={group['concurrency']} "
            f"runs={group['run_count']} "
            f"rps={'n/a' if rps_median is None else f'{rps_median:.2f}'} median "
            f"(cv={'n/a' if rps_cv is None else f'{rps_cv:.1%}'}) "
            f"p95={'n/a' if p95_median is None else f'{p95_median:.2f}'} ms median{warning_text}"
        )


def _write_csv(path: Path, report: dict[str, object]) -> None:
    """Write one CSV row per scenario/concurrency group."""
    groups = _as_list(report["groups"])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "scenario",
                "concurrency",
                "run_count",
                "total_requests",
                "total_errors",
                "rps_median",
                "rps_cv",
                "p50_median_ms",
                "p95_median_ms",
                "p99_median_ms",
                "warnings",
            ]
        )
        for group_value in groups:
            group = _as_dict(group_value)
            rps = _as_dict(group["rps"])
            p50 = _as_dict(group["p50_ms"])
            p95 = _as_dict(group["p95_ms"])
            p99 = _as_dict(group["p99_ms"])
            writer.writerow(
                [
                    group["scenario"],
                    group["concurrency"],
                    group["run_count"],
                    group["total_requests"],
                    group["total_errors"],
                    rps["median"],
                    rps["coefficient_of_variation"],
                    p50["median"],
                    p95["median"],
                    p99["median"],
                    "; ".join(str(warning) for warning in _as_list(group["warnings"])),
                ]
            )


def parse_args() -> argparse.Namespace:
    """Parse comparison CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--allow-incompatible", action="store_true")
    parser.add_argument("--run-set", help="Require every input file to use this run-set identifier.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv", type=Path)
    return parser.parse_args()


def main() -> int:
    """Load files, compare them, and write the report."""
    args = parse_args()
    if len(args.files) < 2:
        print("comparison requires at least two result files", file=sys.stderr)
        return 2
    try:
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in args.files]
        report = compare_documents(
            documents,
            allow_incompatible=args.allow_incompatible,
            expected_run_set=args.run_set,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    _print_report(report)
    output = args.output or Path("benchmarks/results") / (
        f"comparison-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"JSON comparison written to {output}")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(args.csv, report)
        print(f"CSV comparison written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
