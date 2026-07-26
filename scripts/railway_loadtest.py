#!/usr/bin/env python3
"""Run repeatable, read-only HTTP load tests against a ComicPile deployment.

The default profile only exercises unauthenticated routes and is safe for a
production deployment. Authenticated profiles require a bearer token supplied
through an environment variable; the token is never written to result files.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx

DEFAULT_BASE_URL: Final[str] = "https://app-production-72b9.up.railway.app"
DEFAULT_TOKEN_ENV: Final[str] = "RAILWAY_BENCHMARK_TOKEN"
RESULT_SCHEMA_VERSION: Final[int] = 2
HARNESS_VERSION: Final[str] = "railway-loadtest-v2"
FAILURE_DIAGNOSTICS_SCHEMA_VERSION: Final[int] = 1
FAILURE_BODY_SNIPPET_LIMIT: Final[int] = 512
SAFE_RESPONSE_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "content-type",
        "date",
        "server",
        "traceparent",
        "tracestate",
        "via",
        "x-request-id",
        "x-railway-request-id",
    }
)


@dataclass(frozen=True)
class Route:
    """A benchmark route definition."""

    name: str
    path: str
    requires_auth: bool


ROUTES: Final[dict[str, Route]] = {
    "health": Route("health", "/health", False),
    "csrf": Route("csrf", "/api/auth/csrf", False),
    "threads": Route("threads", "/api/threads/", True),
}

PROFILES: Final[dict[str, tuple[str, ...]]] = {
    "control-safe": ("health", "csrf"),
    "health": ("health",),
    "csrf": ("csrf",),
    "authenticated-read": ("threads",),
}

PRESETS: Final[dict[str, dict[str, object]]] = {
    "smoke": {
        "concurrency": [1, 2, 4, 8],
        "warmup_seconds": 10.0,
        "duration_seconds": 30.0,
        "interval_ms": 200.0,
    },
    "results": {
        "concurrency": [1, 2, 4, 8, 16, 32],
        "warmup_seconds": 45.0,
        "duration_seconds": 180.0,
        "interval_ms": 200.0,
    },
    "c32-diagnostic": {
        "concurrency": [32],
        "warmup_seconds": 45.0,
        "duration_seconds": 180.0,
        "interval_ms": 200.0,
    },
}


@dataclass(frozen=True)
class RequestSample:
    """The measured result of one request."""

    route_path: str
    elapsed_ms: float
    status_code: int | None
    response_bytes: int
    error: str | None
    failure: dict[str, object] | None = None


def _as_dict(value: object) -> dict[str, object]:
    """Narrow decoded JSON objects to string-keyed dictionaries."""
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def utc_timestamp() -> str:
    """Return a millisecond-precision UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def redact_text(value: str, limit: int = FAILURE_BODY_SNIPPET_LIMIT) -> str:
    """Redact common credential forms and truncate diagnostic text."""
    redacted = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", value)
    redacted = re.sub(
        r"(?i)(access[_-]?token|refresh[_-]?token|password|secret|api[_-]?key)"
        r"([\"'=:\s]+)[^\s,;\"']+",
        r"\1\2[REDACTED]",
        redacted,
    )
    return redacted[:limit]


def safe_response_headers(response: httpx.Response) -> dict[str, str]:
    """Return only non-sensitive response headers useful for correlation."""
    return {
        name: redact_text(value, 256)
        for name, value in response.headers.items()
        if name.lower() in SAFE_RESPONSE_HEADERS
    }


def percentile(values: list[float], percentile_value: float) -> float | None:
    """Return a nearest-rank percentile from non-empty values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(samples: list[RequestSample], elapsed_s: float) -> dict[str, object]:
    """Build a stable summary for measured request samples."""
    durations = [sample.elapsed_ms for sample in samples]
    status_counts = Counter(
        str(sample.status_code) if sample.status_code is not None else "transport_error"
        for sample in samples
    )
    successful = sum(200 <= (sample.status_code or 0) < 400 for sample in samples)
    return {
        "requests": len(samples),
        "successful_requests": successful,
        "error_requests": len(samples) - successful,
        "requests_per_second": len(samples) / elapsed_s if elapsed_s > 0 else 0.0,
        "latency_ms": {
            "min": min(durations) if durations else None,
            "mean": statistics.fmean(durations) if durations else None,
            "p50": percentile(durations, 50),
            "p95": percentile(durations, 95),
            "p99": percentile(durations, 99),
            "max": max(durations) if durations else None,
        },
        "response_bytes": sum(sample.response_bytes for sample in samples),
        "status_counts": dict(sorted(status_counts.items())),
    }


def summarize_by_route(
    samples: list[RequestSample],
    elapsed_s: float,
) -> dict[str, dict[str, object]]:
    """Build summaries for each route using the same measured-window duration."""
    route_samples: dict[str, list[RequestSample]] = {}
    for sample in samples:
        route_samples.setdefault(sample.route_path, []).append(sample)
    return {
        route_name: summarize(samples_for_route, elapsed_s)
        for route_name, samples_for_route in sorted(route_samples.items())
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PROD_BASE_URL", DEFAULT_BASE_URL),
        help="Deployment URL; defaults to PROD_BASE_URL or the production Railway URL.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="control-safe",
        help="Named route set to exercise.",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="smoke",
        help="Timing/concurrency preset; explicit flags override its values.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        action="append",
        help="Concurrent clients; repeat to run a matrix (preset default applies otherwise).",
    )
    parser.add_argument("--warmup-seconds", type=float)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--interval-ms",
        type=float,
        help="Delay per client between requests; use 0 for open-loop generation.",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable containing a bearer token for authenticated profiles.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output path; defaults to benchmarks/results/<timestamp>.json.",
    )
    parser.add_argument(
        "--run-set",
        default="control-smoke",
        help="Stable experiment/run-set identifier stored in metadata and filenames.",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=Path("benchmarks/control-environment.json"),
        help="Path for the redacted control-environment metadata document.",
    )
    parser.add_argument(
        "--failure-log",
        type=Path,
        help="Optional newline-delimited JSON output for failed-request diagnostics.",
    )
    parser.add_argument(
        "--user-agent",
        default="comicpile-railway-control/1.0",
        help="User-Agent sent by the load generator.",
    )
    args = parser.parse_args()
    preset = PRESETS[args.preset]
    if args.concurrency is None:
        args.concurrency = list(preset["concurrency"])
    if args.warmup_seconds is None:
        args.warmup_seconds = float(preset["warmup_seconds"])
    if args.duration_seconds is None:
        args.duration_seconds = float(preset["duration_seconds"])
    if args.interval_ms is None:
        args.interval_ms = float(preset["interval_ms"])
    args.concurrency = [int(value) for value in args.concurrency]
    if any(value < 1 for value in args.concurrency):
        parser.error("--concurrency values must be positive")
    if args.warmup_seconds < 0 or args.duration_seconds <= 0:
        parser.error("warmup must be non-negative and duration must be positive")
    if args.timeout_seconds <= 0 or args.interval_ms < 0:
        parser.error("timeout must be positive and interval must be non-negative")
    return args


def resolve_routes(profile: str, token_env: str) -> tuple[tuple[Route, ...], str | None]:
    """Resolve a profile and optional bearer token."""
    routes = tuple(ROUTES[name] for name in PROFILES[profile])
    token = os.environ.get(token_env)
    if any(route.requires_auth for route in routes) and not token:
        raise SystemExit(
            f"Profile {profile!r} requires a token in environment variable {token_env!r}."
        )
    return routes, token


async def request_once(
    client: httpx.AsyncClient,
    route: Route,
    url: str,
    headers: dict[str, str],
    concurrency: int,
    client_id: int,
    sequence: int,
    phase: str,
    scheduling_mode: str,
    timeout_seconds: float,
) -> RequestSample:
    """Execute one request and convert transport errors into samples."""
    request_id = str(uuid.uuid4())
    request_headers = {**headers, "X-Benchmark-Request-ID": request_id}
    timestamp = utc_timestamp()
    started = time.perf_counter()
    try:
        response = await client.get(url, headers=request_headers)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if 200 <= response.status_code < 300:
            return RequestSample(
                route_path=route.path,
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                response_bytes=len(response.content),
                error=None,
            )
        failure = {
            "timestamp": timestamp,
            "route": route.path,
            "concurrency": concurrency,
            "client_id": client_id,
            "request_sequence": sequence,
            "scheduling_mode": scheduling_mode,
            "request_id": request_id,
            "exception_type": None,
            "exception_message": f"HTTP status {response.status_code}",
            "http_status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "timeout_seconds": timeout_seconds,
            "failure_category": "non_2xx",
            "response_body_snippet": redact_text(response.text),
            "response_headers": safe_response_headers(response),
        }
        return RequestSample(
            route_path=route.path,
            elapsed_ms=elapsed_ms,
            status_code=response.status_code,
            response_bytes=len(response.content),
            error=f"HTTPStatus{response.status_code}",
            failure=failure,
        )
    except httpx.HTTPError as error:
        elapsed_ms = (time.perf_counter() - started) * 1000
        failure = {
            "timestamp": timestamp,
            "route": route.path,
            "concurrency": concurrency,
            "client_id": client_id,
            "request_sequence": sequence,
            "scheduling_mode": scheduling_mode,
            "request_id": request_id,
            "exception_type": type(error).__name__,
            "exception_message": redact_text(str(error)),
            "http_status": None,
            "elapsed_ms": elapsed_ms,
            "timeout_seconds": timeout_seconds,
            "failure_category": "transport_error",
            "response_body_snippet": None,
            "response_headers": {},
        }
        return RequestSample(
            route_path=route.path,
            elapsed_ms=elapsed_ms,
            status_code=None,
            response_bytes=0,
            error=type(error).__name__,
            failure=failure,
        )


async def worker(
    client: httpx.AsyncClient,
    base_url: str,
    routes: tuple[Route, ...],
    headers: dict[str, str],
    concurrency: int,
    deadline: float,
    interval_s: float,
    samples: list[RequestSample] | None,
    failures: list[dict[str, object]],
    phase: str,
    scheduling_mode: str,
    timeout_seconds: float,
    client_id: int,
) -> None:
    """Run one persistent keep-alive client until a deadline."""
    route_index = 0
    sequence = 0
    while time.perf_counter() < deadline:
        route = routes[route_index % len(routes)]
        route_index += 1
        sequence += 1
        sample = await request_once(
            client,
            route,
            f"{base_url}{route.path}",
            headers,
            concurrency,
            client_id,
            sequence,
            phase,
            scheduling_mode,
            timeout_seconds,
        )
        if samples is not None:
            samples.append(sample)
        if sample.failure is not None:
            failures.append(sample.failure)
        if interval_s > 0:
            await asyncio.sleep(interval_s)


async def run_window(
    client: httpx.AsyncClient,
    base_url: str,
    routes: tuple[Route, ...],
    headers: dict[str, str],
    concurrency: int,
    duration_s: float,
    interval_s: float,
    collect_samples: bool,
    timeout_seconds: float,
    phase: str,
) -> tuple[dict[str, object], list[RequestSample], list[dict[str, object]], dict[str, str]]:
    """Run one warm-up or measured phase on an existing client."""
    samples: list[RequestSample] = []
    failures: list[dict[str, object]] = []
    window_started_at = utc_timestamp()
    deadline = time.perf_counter() + duration_s
    tasks = [
        asyncio.create_task(
            worker(
                client,
                base_url,
                routes,
                headers,
                concurrency,
                deadline,
                interval_s,
                samples if collect_samples else None,
                failures,
                phase,
                "paced_closed_loop" if interval_s > 0 else "open_loop_per_client",
                timeout_seconds,
                client_id,
            )
        )
        for client_id in range(concurrency)
    ]
    started = time.perf_counter()
    await asyncio.gather(*tasks)
    elapsed_s = time.perf_counter() - started
    window_ended_at = utc_timestamp()
    summary = summarize(samples, elapsed_s)
    summary["route_summaries"] = summarize_by_route(samples, elapsed_s)
    return summary, samples, failures, {
        "start_at": window_started_at,
        "end_at": window_ended_at,
    }


def default_output(run_set: str) -> Path:
    """Return a timestamped result path."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("benchmarks/results") / f"{run_set}-{timestamp}.json"


def write_failure_log(path: Path, failures: list[dict[str, object]]) -> None:
    """Write failure diagnostics as newline-delimited JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for failure in failures:
            stream.write(json.dumps(failure, sort_keys=True) + "\n")


def _git_value(*arguments: str) -> str | None:
    """Read a repository value without exposing command failures to the run."""
    try:
        result = subprocess.run(
            ["git", *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _file_match(path: Path, pattern: str) -> str | None:
    """Return the first regex capture from a repository file."""
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(pattern, contents, re.MULTILINE)
    return match.group(1) if match else None


def build_metadata(args: argparse.Namespace, routes: tuple[Route, ...]) -> dict[str, object]:
    """Build redacted, reproducibility metadata from the repo and environment."""
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    database_identity = (
        f"sha256:{hashlib.sha256(database_url.encode()).hexdigest()}"
        if database_url
        else None
    )
    workers_value = os.environ.get("WEB_CONCURRENCY", "2")
    try:
        workers: int | None = int(workers_value)
    except ValueError:
        workers = None
    return {
        "experiment_name": "ComicPile Railway control baseline",
        "run_set": args.run_set,
        "harness_version": HARNESS_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "git_commit_sha": _git_value("rev-parse", "HEAD"),
        "branch": _git_value("branch", "--show-current"),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "docker_base_image": _file_match(
            Path("Dockerfile"), r"^FROM (python:[^ ]+) AS python-builder$"
        ),
        "uv_version": _file_match(Path("Dockerfile"), r"uv:([^ /]+) /uv"),
        "uvicorn_version": _file_match(
            Path("uv.lock"), r'^name = "uvicorn"\nversion = "([^"]+)"'
        ),
        "workers": workers,
        "scheduling_mode": "paced_closed_loop" if args.interval_ms > 0 else "open_loop_per_client",
        "interval_ms": args.interval_ms,
        "warmup_seconds": args.warmup_seconds,
        "measurement_seconds": args.duration_seconds,
        "concurrency_levels": args.concurrency,
        "routes": [route.path for route in routes],
        "railway_service_name": os.environ.get("RAILWAY_SERVICE_NAME"),
        "railway_deployment_id": os.environ.get("RAILWAY_DEPLOYMENT_ID"),
        "railway_region": os.environ.get("RAILWAY_REGION"),
        "railway_cpu_allocation": os.environ.get("RAILWAY_CPU_ALLOCATION"),
        "railway_memory_allocation": os.environ.get("RAILWAY_MEMORY_ALLOCATION"),
        "replica_count": os.environ.get("RAILWAY_REPLICA_COUNT"),
        "autoscaling_status": os.environ.get("RAILWAY_AUTOSCALING_STATUS"),
        "database_region": os.environ.get("DATABASE_REGION"),
        "database_plan": os.environ.get("DATABASE_PLAN"),
        "database_identity": database_identity,
        "database_pool": {
            "pool_size": 1,
            "max_overflow": 2,
            "pool_timeout": 30,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
        },
        "captured_at": datetime.now(UTC).isoformat(),
        "notes": "Railway-only fields remain null unless supplied through environment variables.",
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    """Run all requested concurrency levels and return the result document."""
    routes, token = resolve_routes(args.profile, args.token_env)
    base_url = args.base_url.rstrip("/")
    started_at = datetime.now(UTC).isoformat()
    metadata = build_metadata(args, routes)
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    headers = {"User-Agent": args.user_agent, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results: list[dict[str, object]] = []
    all_failures: list[dict[str, object]] = []
    for concurrency in args.concurrency:
        limits = httpx.Limits(
            max_connections=concurrency,
            max_keepalive_connections=concurrency,
        )
        timeout = httpx.Timeout(args.timeout_seconds)
        async with httpx.AsyncClient(limits=limits, timeout=timeout, http2=False) as client:
            if args.warmup_seconds:
                _, _, warmup_failures, warmup_window = await run_window(
                    client,
                    base_url,
                    routes,
                    headers,
                    concurrency,
                    args.warmup_seconds,
                    args.interval_ms / 1000,
                    False,
                    args.timeout_seconds,
                    "warmup",
                )
            else:
                warmup_failures = []
                warmup_window = {"start_at": None, "end_at": None}
            summary, samples, measurement_failures, measurement_window = await run_window(
                client,
                base_url,
                routes,
                headers,
                concurrency,
                args.duration_seconds,
                args.interval_ms / 1000,
                True,
                args.timeout_seconds,
                "measurement",
            )
        failures = warmup_failures + measurement_failures
        all_failures.extend(failures)
        errors = Counter(sample.error for sample in samples if sample.error)
        results.append(
            {
                "concurrency": concurrency,
                "summary": summary,
                "transport_errors": dict(sorted(errors.items())),
                "measurement_window": measurement_window,
                "warmup_window": warmup_window,
                "failure_diagnostics": {
                    "schema_version": FAILURE_DIAGNOSTICS_SCHEMA_VERSION,
                    "failures": failures,
                    "warmup_failures": warmup_failures,
                    "measurement_failures": measurement_failures,
                },
            }
        )
        latency = _as_dict(summary["latency_ms"])
        print(
            f"c={concurrency}: requests={summary['requests']} "
            f"rps={summary['requests_per_second']:.2f} "
            f"p50={latency['p50']}ms "
            f"p95={latency['p95']}ms "
            f"p99={latency['p99']}ms "
            f"errors={summary['error_requests']}"
        )
        for route_name, route_summary_value in _as_dict(summary["route_summaries"]).items():
            route_summary = _as_dict(route_summary_value)
            route_latency = _as_dict(route_summary["latency_ms"])
            print(
                f"  route={route_name}: requests={route_summary['requests']} "
                f"rps={route_summary['requests_per_second']:.2f} "
                f"p50={route_latency['p50']}ms "
                f"p95={route_latency['p95']}ms "
                f"p99={route_latency['p99']}ms "
                f"errors={route_summary['error_requests']}"
            )

    ended_at = datetime.now(UTC).isoformat()
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "metadata": metadata,
        "run": {
            "started_at": started_at,
            "base_url": base_url,
            "profile": args.profile,
            "preset": args.preset,
            "run_set": args.run_set,
            "ended_at": ended_at,
            "routes": [route.path for route in routes],
            "concurrency": args.concurrency,
            "warmup_seconds": args.warmup_seconds,
            "duration_seconds": args.duration_seconds,
            "timeout_seconds": args.timeout_seconds,
            "interval_ms": args.interval_ms,
            "schedule": (
                "paced: each client issues one request, then sleeps interval_ms"
                if args.interval_ms > 0
                else "open_loop: each client issues the next request immediately"
            ),
            "http2": False,
            "token_supplied": token is not None,
            "token_env": args.token_env if token is not None else None,
            "user_agent": args.user_agent,
            "generator": {
                "python": sys.version,
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
        },
        "results": results,
    }
    if args.failure_log:
        write_failure_log(args.failure_log, all_failures)
    return _as_dict(result)


def main() -> None:
    """Run the CLI and write the JSON result document."""
    args = parse_args()
    result = asyncio.run(run(args))
    output = args.output or default_output(args.run_set)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Results written to {output}")


if __name__ == "__main__":
    main()
