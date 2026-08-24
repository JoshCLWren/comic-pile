#!/usr/bin/env python3
"""Asynchronous latency benchmark for cache provider alternatives.

Measures three paths that appear in the provider-choice debate for issue #1782:

1. **Upstash REST GET** – round-trip time for a single cache read through the
   Upstash Redis REST API.  This is the path the application uses today via
   ``upstash_redis.asyncio.Redis.get``.  Required env vars: ``UPSTASH_REDIS_REST_URL``
   and ``UPSTASH_REDIS_REST_TOKEN``.  Returns ``quota_blocked`` when Upstash
   returns HTTP 429 (quota exhausted – currently expected until ~Aug 28).

2. **Neon point SELECT** – round-trip time for an indexed point SELECT against
   a deliberately narrow KV-style table in Neon, measured with ``asyncpg`` using
   the same connection the application uses.  Required env var: ``DATABASE_URL``.
   The table ``bench_cache_kv`` is created with idempotent DDL if it does not
   exist, then populated with a small representative payload before timing.

3. **Uncached queue read** – authenticated ``GET /api/v1/sessions/current/``
   round-trip from Vercel's network vantage point (caller must supply the
   deployment URL and a bearer token).  This gives context for how much the
   database round-trip contributes to an uncached response versus raw cache
   hop latency.

Output is a JSON document printed to stdout (and optionally written to a file
via ``--output``) with per-run samples and a summary that includes ``p50``
(median), ``p95``, ``min``, ``max``, and ``mean`` for each path.

Usage from Vercel region (replaces local stdlib urllib path with serverless
edge-context measurement):

    DATABASE_URL=postgresql://... \
    UPSTASH_REDIS_REST_URL=https://... \
    UPSTASH_REDIS_REST_TOKEN=... \
    VERCEL_BASE_URL=https://comic-pile.vercel.app \
    VERCEL_BEARER_TOKEN=... \
        python scripts/benchmark_cache_latency.py \
            --iterations 30 \
            --warmups 3 \
            --output docs/CACHE_LOOKUP_LATENCY_2026-08.json

The script is intentionally dependency-minimal: it imports only the Python
standard library and ``asyncpg`` (an existing production dependency) so that
it can be deployed as a throwaway serverless function without installing extra
packages.  Network requests use ``urllib.request`` to avoid introducing ``httpx``
into the throwaway harness.

Quota note: Upstash free-tier is quota-stopped until approximately 2026-08-28.
The script correctly records quota-429 responses in the output rather than
failing outright, so the Neon and uncached-reread paths can still be measured
independently.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request


@dataclasses.dataclass(frozen=True)
class Run:
    """Single recorded observation."""

    path: str
    iteration: int
    elapsed_ms: float
    status: str
    http_status: int | None
    upstash_error: str | None
    error_detail: str | None


def _upstash_rest_key() -> str:
    """Derive the canonical Upstash REST endpoint for a cache GET."""
    return "comic_pile_cache_latency_bench_key_v1"


def _upstash_rest_url(base_url: str, token: str, key: str) -> str:
    """Build the GET URL for a raw Upstash REST GET call."""
    encoded_key = urllib.parse.quote(key, safe="")
    return f"{base_url}/get/{encoded_key}"


def _upstash_request(url: str, token: str, timeout: float) -> tuple[float, int, bytes, str | None]:
    """Execute a raw HTTP GET against the Upstash REST API and wall-clock it.

    Returns (elapsed_ms, http_status, response_body_bytes, error_summary_or_None).
    Mirrors the network path taken by ``upstash_redis.asyncio.Redis.get`` without
    requiring that package.
    """
    started = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "comic-pile-cache-benchmark/1")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, resp.status, body, None
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        body = exc.read() if exc.fp else b""
        error = f"HTTP {exc.code}"
        return elapsed_ms, exc.code, body, error
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        error = str(exc.reason)
        return elapsed_ms, 0, b"", error
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, 0, b"", str(exc)


async def _neon_point_select(
    database_url: str,
    table: str,
    key: str,
    timeout: float,
) -> tuple[float, str | None, str | None]:
    """Open an asyncpg connection and execute a point SELECT against the KV table.

    Returns (elapsed_ms, row_value_or_None, error_summary_or_None).
    Uses ``asyncpg`` directly (same ``postgresql+asyncpg://`` driver the
    application uses) so the hop count matches production exactly.
    """
    import asyncpg

    started = time.perf_counter()
    try:
        conn = await asyncpg.connect(database_url, timeout=timeout)
    except (OSError, asyncpg.exceptions.InvalidConnectionError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, None, f"connect_failed: {exc}"

    try:
        row = await conn.fetchrow(
            f"SELECT key, value, created_at FROM {table} WHERE key = $1 LIMIT 1",
            key,
            timeout=timeout,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        value = row["value"] if row else None
        return elapsed_ms, value, None
    except (OSError, asyncpg.exceptions.PostgresError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        error = f"query_failed: {exc}"
        return elapsed_ms, None, error
    finally:
        await conn.close()


async def _ensure_kv_table(conn: object, table: str) -> None:
    """Idempotently create a small KV-style table and insert one representative row."""
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            key        TEXT PRIMARY KEY,
            value      JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        f"INSERT INTO {table} (key, value) VALUES ($1, $2) "
        f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, created_at = NOW()",
        "bench:user:42:thread_list_v1",
        json.dumps({"threads": 42, "queue_size": 7, "last_roll_id": 1001}),
    )


async def _uncached_queue_read(base_url: str, bearer_token: str, timeout: float) -> tuple[float, int, bytes, str | None]:
    """Unauthenticated-skip GET to the representative queue-bearing endpoint.

    Reads from ``/api/v1/sessions/current/`` which in production includes
    the active thread queue alongside session state.  This path bypasses the
    application cache (production cache is disabled by default: ``CACHE_ENABLED=false``).

    Returns (elapsed_ms, http_status, response_body_bytes, error_summary_or_None).
    """
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "api/v1/sessions/current/")
    started = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", f"Bearer {bearer_token}")
    req.add_header("User-Agent", "comic-pile-cache-benchmark/1")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, resp.status, body, None
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        body = exc.read() if exc.fp else b""
        error = f"HTTP {exc.code}"
        return elapsed_ms, exc.code, body, error
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        error = str(exc.reason)
        return elapsed_ms, 0, b"", error
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, 0, b"", str(exc)


def _summarize(runs: list[Run]) -> dict[str, int | float | dict[str, float]] | None:
    """Compute p50, p95, and other aggregates for a list of successful runs."""
    if not runs:
        return None
    elapsed = [r.elapsed_ms for r in runs]
    try:
        p95 = statistics.quantiles(elapsed, n=20)[18]
    except (statistics.StatisticsError, IndexError):
        p95 = max(elapsed)
    return {
        "samples": len(runs),
        "elapsed_ms": {
            "min": min(elapsed),
            "p50": round(statistics.median(elapsed), 3),
            "p95": round(p95, 3),
            "max": max(elapsed),
            "mean": round(statistics.fmean(elapsed), 3),
        },
    }


async def run_benchmark(args: argparse.Namespace) -> dict[str, str | int | float | list[dict[str, object]] | dict[str, object] | None]:
    """Execute the full benchmark suite and return the JSON-ready report."""
    upstash_url: str = args.upstash_url
    upstash_token: str = args.upstash_token
    database_url: str | None = args.database_url
    kv_table: str = args.kv_table
    queue_base_url: str | None = args.queue_base_url
    queue_bearer_token: str | None = args.queue_bearer_token
    iterations: int = args.iterations
    warmups: int = args.warmups
    upstash_timeout: float = args.upstash_timeout
    db_timeout: float = args.db_timeout
    queue_timeout: float = args.queue_timeout
    upstash_key = _upstash_rest_key()

    all_runs: list[dict[str, object]] = []
    upstash_runs: list[Run] = []
    neon_runs: list[Run] = []
    queue_runs: list[Run] = []

    # ── Phase 1: Upstash REST GET ─────────────────────────────────────────────
    rest_endpoint = _upstash_rest_url(upstash_url, upstash_token, upstash_key)
    upstash_quota_blocked = False
    for i in range(-warmups, iterations):
        elapsed_ms, http_status, body, error = _upstash_request(
            rest_endpoint, upstash_token, upstash_timeout
        )
        run = Run(
            path="upstash_rest_get",
            iteration=i,
            elapsed_ms=round(elapsed_ms, 3),
            status="ok" if error is None else ("quota_blocked" if http_status == 429 else "error"),
            http_status=http_status,
            upstash_error=error if error else None,
            error_detail=None,
        )
        if i >= 0:
            upstash_runs.append(run)
        all_runs.append(dataclasses.asdict(run))
        if http_status == 429:
            upstash_quota_blocked = True

    upstash_summary = _summarize(upstash_runs)

    # ── Phase 2: Neon point SELECT ─────────────────────────────────────────────
    if database_url:
        try:
            import asyncpg  # noqa: F811 – re-import to confirm availability
        except ImportError:
            neon_error = "asyncpg_not_installed"
            for i in range(iterations):
                run = Run(
                    path="neon_point_select",
                    iteration=i,
                    elapsed_ms=0.0,
                    status="skipped",
                    http_status=None,
                    upstash_error=None,
                    error_detail=neon_error,
                )
                neon_runs.append(run)
                all_runs.append(dataclasses.asdict(run))
        else:
            pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2, timeout=db_timeout)
            async with pool.acquire() as conn:
                await _ensure_kv_table(conn, kv_table)
            populate_run = Run(
                path="neon_point_select",
                iteration=-1,
                elapsed_ms=0.0,
                status="setup:table_ready",
                http_status=None,
                upstash_error=None,
                error_detail=None,
            )
            all_runs.append(dataclasses.asdict(populate_run))

            for i in range(-warmups, iterations):
                elapsed_ms, value, error = await _neon_point_select(
                    database_url, kv_table, upstash_key, db_timeout
                )
                run = Run(
                    path="neon_point_select",
                    iteration=i,
                    elapsed_ms=round(elapsed_ms, 3),
                    status="ok" if error is None else "error",
                    http_status=None,
                    upstash_error=None,
                    error_detail=error,
                )
                if i >= 0:
                    neon_runs.append(run)
                all_runs.append(dataclasses.asdict(run))
            await pool.close()

    neon_summary = _summarize(neon_runs) if neon_runs else None

    # ── Phase 3: Uncached queue read ──────────────────────────────────────────
    if queue_base_url and queue_bearer_token:
        for i in range(-warmups, iterations):
            elapsed_ms, http_status, body, error = await _uncached_queue_read(
                queue_base_url, queue_bearer_token, queue_timeout
            )
            run = Run(
                path="uncached_queue_read",
                iteration=i,
                elapsed_ms=round(elapsed_ms, 3),
                status="ok" if error is None else "error",
                http_status=http_status,
                upstash_error=None,
                error_detail=error,
            )
            if i >= 0:
                queue_runs.append(run)
            all_runs.append(dataclasses.asdict(run))
    else:
        for i in range(iterations):
            run = Run(
                path="uncached_queue_read",
                iteration=i,
                elapsed_ms=0.0,
                status="skipped",
                http_status=None,
                upstash_error=None,
                error_detail="--queue-base-url and --queue-bearer-token required",
            )
            queue_runs.append(run)
            all_runs.append(dataclasses.asdict(run))

    queue_summary = _summarize(queue_runs) if queue_runs else None

    # ── Provider decision note ─────────────────────────────────────────────────
    decision_parts: list[str] = []
    if upstash_summary and not upstash_quota_blocked:
        upstash_p50 = upstash_summary["elapsed_ms"]["p50"]
        decision_parts.append(
            f"Upstash REST path p50={upstash_p50} ms"
        )
        if neon_summary:
            neon_p50 = neon_summary["elapsed_ms"]["p50"]
            ratio = upstash_p50 / neon_p50 if neon_p50 else None
            if ratio is not None:
                decision_parts.append(
                    f"{ratio:.1f}× {'faster' if ratio < 1 else 'slower'} than Neon point SELECT p50={neon_p50} ms"
                )
    elif upstash_quota_blocked:
        decision_parts.append(
            "Upstash quota-blocked (HTTP 429) – measurements cannot be compared until reset"
        )
    else:
        decision_parts.append("Upstash measurements pending (no valid token or URL)")

    if neon_summary:
        neon_p50 = neon_summary["elapsed_ms"]["p50"]
        decision_parts.append(f"Neon point SELECT p50={neon_p50} ms")

    if queue_summary:
        queue_p50 = queue_summary["elapsed_ms"]["p50"]
        decision_parts.append(f"Uncached queue read p50={queue_p50} ms")

    provider_decision = "; ".join(decision_parts) if decision_parts else "Awaiting measurements"

    report: dict[str, str | int | bool | list | dict | None] = {
        "schema_version": "1.0",
        "measured_from": args.location or "unknown",
        "iterations": iterations,
        "warmups_per_path": warmups,
        "kv_table": kv_table,
        "upstash_rest_get": {
            "endpoint": rest_endpoint,
            "quota_blocked": upstash_quota_blocked,
            "runs": [dataclasses.asdict(r) for r in upstash_runs],
            "summary": upstash_summary,
        },
        "neon_point_select": {
            "runs": [dataclasses.asdict(r) for r in neon_runs],
            "summary": neon_summary,
        },
        "uncached_queue_read": {
            "runs": [dataclasses.asdict(r) for r in queue_runs],
            "summary": queue_summary,
        },
        "provider_decision": provider_decision,
        "_note_upstash_quota": (
            "Upstash free-tier quota is blocked until approximately 2026-08-28. "
            "The upstash_rest_get section records quota_blocked=true and individual "
            "HTTP 429 responses. Re-run after quota reset for a complete comparison."
        ),
    }
    return report


def run_sync(args: argparse.Namespace) -> int:
    """Entry point used by synchronous invocation."""
    report = asyncio.run(run_benchmark(args))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        import os

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--upstash-url",
        required=True,
        help="Upstash Redis REST base URL (e.g. https://us1-xxxx.upstash.io)",
    )
    parser.add_argument(
        "--upstash-token",
        required=True,
        help="Upstash Redis REST token",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Neon DATABASE_URL (asyncpg). Required for the Neon point SELECT measurement.",
    )
    parser.add_argument(
        "--kv-table",
        default="neon_default_table",
        help=f"Name of the KV-style table for the Neon benchmark (default: {"neon_default_table"})",
    )
    parser.add_argument(
        "--queue-base-url",
        default=None,
        help="Base URL of the production deployment (https://comic-pile.vercel.app)",
    )
    parser.add_argument(
        "--queue-bearer-token",
        default=None,
        help="Bearer token for the authenticated queue-read measurement",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Recorded samples per measurement (default: {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=DEFAULT_WARMUPS,
        help=f"Unrecorded warm-up samples (default: {DEFAULT_WARMUPS})",
    )
    parser.add_argument(
        "--upstash-timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds for Upstash calls",
    )
    parser.add_argument(
        "--db-timeout",
        type=float,
        default=10.0,
        help="Query timeout in seconds for Neon point SELECT",
    )
    parser.add_argument(
        "--queue-timeout",
        type=float,
        default=15.0,
        help="HTTP request timeout in seconds for the queue read",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional file path for the JSON report (always printed to stdout)",
    )
    parser.add_argument(
        "--location",
        default="unknown",
        help="Deployment vantage (e.g. 'vercel:iad1', 'local:docker') for the report header",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")
    if args.warmups < 0:
        raise SystemExit("--warmups must be >= 0")
    return run_sync(args)


if __name__ == "__main__":
    raise SystemExit(main())