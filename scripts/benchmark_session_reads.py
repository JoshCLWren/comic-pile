#!/usr/bin/env python3
"""Benchmark authenticated current-session and History API reads.

This harness is intentionally dependency-free so it can run against local,
preview, or production deployments without installing the application.
It records the response evidence needed by issue #700: elapsed time, payload
size, application cache state, request ID, and database query-count headers.

The first recorded request is reported separately from later steady-state
samples. It is only a first-observed measurement, not proof that the deployment
was cold; callers must control deployment idleness when collecting cold-path
evidence. Use ``--endpoint`` to isolate one endpoint in a fresh invocation when
collecting endpoint-specific first-request evidence.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Sample:
    """One recorded benchmark observation for a single endpoint request."""

    endpoint: str
    iteration: int
    elapsed_ms: float
    status: int
    response_bytes: int
    request_id: str | None
    app_cache: str | None
    db_queries: int | None
    server_timing: str | None


def _parse_db_queries(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _request(
    *,
    base_url: str,
    endpoint: str,
    iteration: int,
    bearer_token: str | None,
    cookie: str | None,
    timeout: float,
) -> Sample:
    url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))
    headers = {"Accept": "application/json", "User-Agent": "comic-pile-session-benchmark/1"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if cookie:
        headers["Cookie"] = cookie

    request = Request(url, headers=headers, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit operator URL
            body = response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return Sample(
                endpoint=endpoint,
                iteration=iteration,
                elapsed_ms=round(elapsed_ms, 3),
                status=response.status,
                response_bytes=len(body),
                request_id=response.headers.get("X-Request-ID"),
                app_cache=response.headers.get("X-App-Cache"),
                db_queries=_parse_db_queries(response.headers.get("X-App-DB-Queries")),
                server_timing=response.headers.get("Server-Timing"),
            )
    except HTTPError as exc:
        body = exc.read()
        elapsed_ms = (time.perf_counter() - started) * 1000
        raise RuntimeError(
            f"{endpoint} returned HTTP {exc.code} after {elapsed_ms:.1f} ms: "
            f"{body[:500].decode('utf-8', errors='replace')}"
        ) from exc
    except URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        raise RuntimeError(
            f"{endpoint} failed after {elapsed_ms:.1f} ms: {exc.reason}"
        ) from exc


def _sample_evidence(sample: Sample) -> dict[str, Any]:
    return {
        "elapsed_ms": sample.elapsed_ms,
        "status": sample.status,
        "response_bytes": sample.response_bytes,
        "request_id": sample.request_id,
        "app_cache": sample.app_cache,
        "db_queries": sample.db_queries,
        "server_timing": sample.server_timing,
    }


def _aggregate(samples: list[Sample]) -> dict[str, Any] | None:
    if not samples:
        return None

    elapsed = [sample.elapsed_ms for sample in samples]
    db_queries = [sample.db_queries for sample in samples if sample.db_queries is not None]
    cache_states: dict[str, int] = {}
    for sample in samples:
        key = sample.app_cache or "missing"
        cache_states[key] = cache_states.get(key, 0) + 1

    return {
        "samples": len(samples),
        "elapsed_ms": {
            "min": min(elapsed),
            "median": round(statistics.median(elapsed), 3),
            "max": max(elapsed),
            "mean": round(statistics.fmean(elapsed), 3),
        },
        "response_bytes": {
            "min": min(sample.response_bytes for sample in samples),
            "max": max(sample.response_bytes for sample in samples),
        },
        "db_queries": {
            "reported_samples": len(db_queries),
            "min": min(db_queries) if db_queries else None,
            "max": max(db_queries) if db_queries else None,
        },
        "cache_states": cache_states,
        "missing_server_timing": sum(sample.server_timing is None for sample in samples),
    }


def summarize(samples: list[Sample]) -> dict[str, Any]:
    """Return first-observed and steady-state evidence for one endpoint."""
    if not samples:
        raise ValueError("at least one sample is required")

    return {
        "endpoint": samples[0].endpoint,
        "first_observed": _sample_evidence(samples[0]),
        "steady_state": _aggregate(samples[1:]),
        "all_recorded": _aggregate(samples),
    }


def _build_endpoints(page_size: int, later_page_token: str | None) -> list[str]:
    endpoints = [
        "/api/sessions/current/",
        f"/api/sessions/?{urlencode({'page_size': page_size})}",
    ]
    if later_page_token:
        endpoints.append(
            f"/api/sessions/?{urlencode({'page_size': page_size, 'page_token': later_page_token})}"
        )
    return endpoints


def _select_endpoints(
    endpoint_selection: str,
    page_size: int,
    later_page_token: str | None,
) -> list[str]:
    """Select endpoints without preconditioning a later target in the same run."""
    endpoints = _build_endpoints(page_size, later_page_token)
    if endpoint_selection == "all":
        return endpoints
    if endpoint_selection == "current":
        return [endpoints[0]]
    if endpoint_selection == "history-first":
        return [endpoints[1]]
    if endpoint_selection == "history-later":
        if len(endpoints) < 3:
            raise ValueError("history-later requires --later-page-token")
        return [endpoints[2]]
    raise ValueError(f"unknown endpoint selection: {endpoint_selection}")


def main() -> int:
    """Run the session-read benchmark and print a JSON report to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Deployment URL, for example http://localhost:8000")
    parser.add_argument("--bearer-token", help="Access token for Authorization: Bearer")
    parser.add_argument("--cookie", help="Raw Cookie header, useful for refresh-cookie authentication")
    parser.add_argument(
        "--endpoint",
        choices=("all", "current", "history-first", "history-later"),
        default="all",
        help=(
            "Endpoint group to benchmark. Select one endpoint in a fresh invocation for "
            "endpoint-specific first-request evidence."
        ),
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=0,
        help="Unrecorded preconditioning requests per endpoint; default 0 retains first-observed evidence",
    )
    parser.add_argument("--iterations", type=int, default=5, help="Recorded requests per endpoint")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--later-page-token", help="Optional History cursor to benchmark a later page")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", help="Optional path for the JSON report")
    args = parser.parse_args()

    if args.warmups < 0 or args.iterations < 1:
        parser.error("--warmups must be >= 0 and --iterations must be >= 1")
    if not 1 <= args.page_size <= 200:
        parser.error("--page-size must be between 1 and 200")

    try:
        endpoints = _select_endpoints(args.endpoint, args.page_size, args.later_page_token)
    except ValueError as exc:
        parser.error(str(exc))

    if len(endpoints) == 1:
        first_observed_note = (
            "The first recorded request is not guaranteed cold. Control deployment idleness "
            "outside this harness when collecting cold-path evidence."
        )
    else:
        first_observed_note = (
            "Only the first endpoint in this multi-endpoint run can be the deployment's first "
            "request. Use --endpoint in separate fresh invocations for endpoint-specific "
            "first-request evidence; deployment coldness must still be controlled externally."
        )

    report: dict[str, Any] = {
        "base_url": args.base_url,
        "endpoint_selection": args.endpoint,
        "warmups": args.warmups,
        "iterations": args.iterations,
        "page_size": args.page_size,
        "first_observed_note": first_observed_note,
        "runs": [],
        "summaries": [],
    }

    for endpoint in endpoints:
        for warmup in range(args.warmups):
            _request(
                base_url=args.base_url,
                endpoint=endpoint,
                iteration=-(warmup + 1),
                bearer_token=args.bearer_token,
                cookie=args.cookie,
                timeout=args.timeout,
            )

        endpoint_samples = [
            _request(
                base_url=args.base_url,
                endpoint=endpoint,
                iteration=iteration,
                bearer_token=args.bearer_token,
                cookie=args.cookie,
                timeout=args.timeout,
            )
            for iteration in range(1, args.iterations + 1)
        ]
        report["runs"].extend(asdict(sample) for sample in endpoint_samples)
        report["summaries"].append(summarize(endpoint_samples))

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
