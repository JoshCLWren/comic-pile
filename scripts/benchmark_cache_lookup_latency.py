"""Benchmark cache-lookup latency from a single vantage point.

Compares, from the same network position:
1. Postgres RTT floor (``SELECT 1``) via asyncpg.
2. Postgres indexed point lookup on an existing table (KV-shaped read).
3. Upstash REST GET round trip (when credentials are present and the
   database is not quota-hard-stopped).

Usage:
    set -a; source .env.production; set +a
    uv run python scripts/benchmark_cache_lookup_latency.py --samples 300

Never prints connection strings or tokens.
"""

import argparse
import asyncio
import os
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def _timed(coro_factory: Callable[[], Awaitable[None]], samples: int) -> list[float]:
    """Run ``coro_factory`` ``samples`` times and return per-run milliseconds."""
    timings: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        await coro_factory()
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def _summarize(label: str, timings: Sequence[float]) -> dict[str, int | float | str]:
    ordered = sorted(timings)
    return {
        "label": label,
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": ordered[int(len(ordered) * 0.95)],
        "max": ordered[-1],
    }


def _print_row(row: dict[str, float]) -> None:
    print(
        f"{row['label']:<34} min {row['min']:7.2f}  "
        f"p50 {row['median']:7.2f}  p95 {row['p95']:7.2f}  max {row['max']:7.2f}"
    )


def _resolve_upstash_base_url() -> str | None:
    """Return the Upstash REST base URL from either naming convention."""
    for key in ("UPSTASH_REDIS_REST_URL", "KV_REST_API_URL"):
        value = os.getenv(key)
        if value:
            return value.rstrip("/")
    return None


def _resolve_upstash_token() -> str | None:
    """Return the Upstash REST token from either naming convention."""
    for key in ("UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_TOKEN"):
        value = os.getenv(key)
        if value:
            return value
    return None


async def benchmark(database_url: str, samples: int) -> None:
    """Run all latency benchmarks and print a summary table."""
    engine = create_async_engine(database_url, pool_size=5, max_overflow=0)

    try:
        async with engine.begin() as conn:
            probe_id = await conn.scalar(text("SELECT MIN(id) FROM events"))

        if probe_id is None:
            probe_id = 1

        async def rtt_floor() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        async def point_lookup() -> None:
            async with engine.connect() as conn:
                await conn.execute(
                    text("SELECT id FROM events WHERE id = :id"),
                    {"id": probe_id},
                )

        _print_row(_summarize("postgres SELECT 1 (RTT)", await _timed(rtt_floor, samples)))
        _print_row(
            _summarize("postgres PK lookup (events)", await _timed(point_lookup, samples))
        )
    finally:
        await engine.dispose()

    base_url = _resolve_upstash_base_url()
    token = _resolve_upstash_token()
    if not base_url or not token:
        print("upstash REST GET                skipped (no credentials)")
        return

    headers = {"Authorization": f"Bearer {token}"}

    async def rest_get() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await client.get(
                f"{base_url}/get/benchmark-probe-key",
                headers=headers,
            )

    async def rest_timings() -> list[float]:
        out: list[float] = []
        statuses: set[int] = set()
        for _ in range(samples):
            started = time.perf_counter()
            response = await rest_get()
            out.append((time.perf_counter() - started) * 1000)
            statuses.add(response.status_code)
        print(f"(upstash response statuses: {sorted(statuses)})")
        return out

    _print_row(_summarize("upstash REST GET", await rest_timings()))


async def _benchmark_redis_protocol(url: str, samples: int) -> None:
    """Time warm GET/SET round trips against a RESP-compatible server."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=6,
        socket_timeout=6,
    )
    try:
        await client.set("benchmark-probe-key", "x" * 512)

        get_timings = await _timed(
            lambda: client.get("benchmark-probe-key"),
            samples,
        )
        _print_row(_summarize("redis RESP GET (warm)", get_timings))

        set_timings = await _timed(
            lambda: client.set("benchmark-probe-key", "x" * 512),
            max(samples // 4, 1),
        )
        _print_row(_summarize("redis RESP SET", set_timings))
    finally:
        await client.aclose()


def main() -> None:
    """Parse arguments and run the benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument(
        "--redis-only",
        action="store_true",
        help="Skip Postgres benchmarks; time only the RESP server from REDIS_BENCHMARK_URL.",
    )
    args = parser.parse_args()

    if args.redis_only:
        asyncio.run(run_redis_only(args.samples))
        return

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    # Vercel/Neon inject plain postgresql:// URLs; force the async driver.
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            database_url = "postgresql+asyncpg://" + database_url[len(prefix) :]
            break

    asyncio.run(benchmark(database_url, args.samples))


async def run_redis_only(samples: int) -> None:
    """Run only the RESP benchmark (used when DATABASE_URL is unavailable)."""
    url = os.getenv("REDIS_BENCHMARK_URL")
    if not url:
        raise SystemExit("REDIS_BENCHMARK_URL is required for --redis-only")
    await _benchmark_redis_protocol(url, samples)


if __name__ == "__main__":
    main()
