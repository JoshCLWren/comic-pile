#!/usr/bin/env python3
"""Benchmark SQLAlchemy pool configurations for Vercel Fluid Compute.

This script tests different pool configurations against a live database and measures:
- Pool checkout latency (with and without pre-ping)
- Physical connection creation rate
- Query latency under concurrent load
- Pool state transitions

Usage:
    DATABASE_URL=postgresql+asyncpg://... python scripts/pool_benchmark.py --configs all
    DATABASE_URL=postgresql+asyncpg://... python scripts/pool_benchmark.py --configs "1,2,true;2,0,false;3,0,true"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Default benchmark parameters
DEFAULT_CONCURRENCY: Final[list[int]] = [1, 2, 4, 8, 16, 32]
DEFAULT_WARMUP_SECONDS: Final[float] = 10.0
DEFAULT_DURATION_SECONDS: Final[float] = 30.0
DEFAULT_INTERVAL_MS: Final[float] = 100.0
DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0

# Pool configurations to test: (pool_size, max_overflow, pool_pre_ping, pool_recycle)
# Includes baseline, recommended (2,0,false), and variants
DEFAULT_CONFIGS: Final[list[tuple[int, int, bool, int]]] = [
    (1, 2, True, 3600),    # Legacy baseline (old defaults)
    (1, 2, False, 3600),   # Legacy baseline without pre-ping
    (2, 0, True, 3600),    # Recommended size, with pre-ping
    (2, 0, False, 3600),   # Recommended (new defaults): size 2, no overflow, no pre-ping
    (2, 1, True, 3600),    # Recommended size, small overflow, with pre-ping
    (2, 1, False, 3600),   # Recommended size, small overflow, no pre-ping
    (3, 0, True, 3600),    # Size 3, no overflow, with pre-ping
    (3, 0, False, 3600),   # Size 3, no overflow, without pre-ping
]


@dataclass(frozen=True)
class PoolConfig:
    """Pool configuration for benchmarking."""
    pool_size: int
    max_overflow: int
    pool_pre_ping: bool
    pool_recycle: int

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return asdict(self)

    def short_name(self) -> str:
        """Return a short name for the configuration."""
        return f"size{self.pool_size}_over{self.max_overflow}_ping{self.pool_pre_ping}_recycle{self.pool_recycle}"


@dataclass
class PoolEventSample:
    """A single pool event measurement."""
    timestamp: str
    event_type: str  # "checkout", "checkin", "connect", "first_connect", "invalidate"
    duration_ms: float | None
    pool_size: int
    checked_out: int
    checked_in: int
    overflow: int


@dataclass
class QuerySample:
    """A single query measurement."""
    timestamp: str
    route: str
    elapsed_ms: float
    status_code: int | None
    error: str | None


@dataclass
class BenchmarkResult:
    """Complete benchmark result for one pool configuration."""
    config: PoolConfig
    concurrency: int
    warmup_seconds: float
    duration_seconds: float
    interval_ms: float
    pool_events: list[PoolEventSample]
    query_samples: list[QuerySample]
    summary: dict[str, object]
    started_at: str
    ended_at: str


def percentile(values: list[float], percentile_value: float) -> float | None:
    """Return a nearest-rank percentile from non-empty values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(__import__("math").ceil(percentile_value / 100 * len(ordered))))
    return ordered[rank - 1]


def summarize_samples(samples: list[QuerySample], elapsed_s: float) -> dict[str, object]:
    """Build a summary for measured query samples."""
    durations = [sample.elapsed_ms for sample in samples]
    status_counts: dict[str, int] = {}
    successful = 0
    for sample in samples:
        key = str(sample.status_code) if sample.status_code is not None else "transport_error"
        status_counts[key] = status_counts.get(key, 0) + 1
        if sample.status_code is not None and 200 <= sample.status_code < 300:
            successful += 1

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
        "status_counts": dict(sorted(status_counts.items())),
    }


def parse_configs(config_str: str) -> list[PoolConfig]:
    """Parse pool configurations from a string like '1,2,true;2,0,false'."""
    configs = []
    for part in config_str.split(";"):
        if not part.strip():
            continue
        values = part.split(",")
        if len(values) != 4:
            raise ValueError(f"Invalid config format: {part}. Expected 'pool_size,max_overflow,pre_ping,recycle'")
        pool_size = int(values[0])
        max_overflow = int(values[1])
        pool_pre_ping = values[2].lower() == "true"
        pool_recycle = int(values[3])
        configs.append(PoolConfig(pool_size, max_overflow, pool_pre_ping, pool_recycle))
    return configs


class PoolBenchmark:
    """Run pool benchmarks against a live database."""

    def __init__(
        self,
        database_url: str,
        concurrency_levels: list[int],
        warmup_seconds: float,
        duration_seconds: float,
        interval_ms: float,
        timeout_seconds: float,
        output_dir: Path,
    ) -> None:
        """Initialize the benchmark runner.

        Args:
            database_url: Database connection URL.
            concurrency_levels: List of concurrency levels to test.
            warmup_seconds: Warmup duration in seconds.
            duration_seconds: Measurement duration in seconds.
            interval_ms: Interval between requests in milliseconds.
            timeout_seconds: Request timeout in seconds.
            output_dir: Directory to write results.
        """
        self.database_url = database_url
        self.concurrency_levels = concurrency_levels
        self.warmup_seconds = warmup_seconds
        self.duration_seconds = duration_seconds
        self.interval_ms = interval_ms
        self.timeout_seconds = timeout_seconds
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._pool_events: list[PoolEventSample] = []
        self._query_samples: list[QuerySample] = []

    def _create_engine(self, config: PoolConfig):
        """Create an async engine with the given pool configuration."""
        return create_async_engine(
            self.database_url,
            pool_recycle=config.pool_recycle,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow,
            pool_timeout=self.timeout_seconds,
            pool_pre_ping=config.pool_pre_ping,
            connect_args={
                "timeout": self.timeout_seconds,
                "command_timeout": self.timeout_seconds,
            },
        )

    def _attach_pool_listeners(self, engine, config: PoolConfig):
        """Attach pool event listeners to collect metrics."""
        pool = engine.sync_engine.pool

        @event.listens_for(pool, "checkout")
        def on_checkout(dbapi_connection, connection_record, connection_proxy):
            del dbapi_connection, connection_proxy
            checkout_started = getattr(connection_record, "_bench_checkout_started", None)
            duration_ms = None
            if isinstance(checkout_started, float):
                duration_ms = (time.perf_counter() - checkout_started) * 1000
            self._pool_events.append(PoolEventSample(
                timestamp=datetime.now(UTC).isoformat(),
                event_type="checkout",
                duration_ms=duration_ms,
                pool_size=pool.size(),
                checked_out=pool.checkedout(),
                checked_in=pool.checkedin(),
                overflow=pool.overflow(),
            ))

        @event.listens_for(pool, "checkin")
        def on_checkin(dbapi_connection, connection_record):
            del dbapi_connection, connection_record
            self._pool_events.append(PoolEventSample(
                timestamp=datetime.now(UTC).isoformat(),
                event_type="checkin",
                duration_ms=None,
                pool_size=pool.size(),
                checked_out=pool.checkedout(),
                checked_in=pool.checkedin(),
                overflow=pool.overflow(),
            ))

        @event.listens_for(pool, "connect")
        def on_connect(dbapi_connection, connection_record):
            del dbapi_connection, connection_record
            self._pool_events.append(PoolEventSample(
                timestamp=datetime.now(UTC).isoformat(),
                event_type="connect",
                duration_ms=None,
                pool_size=pool.size(),
                checked_out=pool.checkedout(),
                checked_in=pool.checkedin(),
                overflow=pool.overflow(),
            ))

        @event.listens_for(pool, "first_connect")
        def on_first_connect(dbapi_connection, connection_record):
            del dbapi_connection, connection_record
            self._pool_events.append(PoolEventSample(
                timestamp=datetime.now(UTC).isoformat(),
                event_type="first_connect",
                duration_ms=None,
                pool_size=pool.size(),
                checked_out=pool.checkedout(),
                checked_in=pool.checkedin(),
                overflow=pool.overflow(),
            ))

        @event.listens_for(pool, "invalidate")
        def on_invalidate(dbapi_connection, connection_record, exception):
            del dbapi_connection, connection_record
            self._pool_events.append(PoolEventSample(
                timestamp=datetime.now(UTC).isoformat(),
                event_type="invalidate",
                duration_ms=None,
                pool_size=pool.size(),
                checked_out=pool.checkedout(),
                checked_in=pool.checkedin(),
                overflow=pool.overflow(),
            ))

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def before_cursor(connection, cursor, statement, parameters, context, executemany):
            # Mark checkout start time on the connection record if available
            try:
                conn_record = getattr(connection, "_connection_record", None)
                if conn_record is not None:
                    conn_record._bench_checkout_started = time.perf_counter()
            except Exception:
                pass
            del cursor, statement, parameters, executemany
            vars(context)["_bench_query_started"] = time.perf_counter()

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def after_cursor(connection, cursor, statement, parameters, context, executemany):
            del connection, cursor, statement, parameters, executemany
            started = vars(context).get("_bench_query_started")
            if isinstance(started, float):
                # We don't record query samples here since we measure at HTTP level
                pass

    async def _run_query(self, session: AsyncSession, route: str) -> QuerySample:
        """Execute a single query and measure latency."""
        started = time.perf_counter()
        timestamp = datetime.now(UTC).isoformat()
        try:
            await session.execute(text("SELECT 1"))
            elapsed_ms = (time.perf_counter() - started) * 1000
            return QuerySample(
                timestamp=timestamp,
                route=route,
                elapsed_ms=elapsed_ms,
                status_code=200,
                error=None,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return QuerySample(
                timestamp=timestamp,
                route=route,
                elapsed_ms=elapsed_ms,
                status_code=None,
                error=type(e).__name__,
            )

    async def _worker(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        concurrency: int,
        deadline: float,
        interval_s: float,
        samples: list[QuerySample],
        client_id: int,
    ):
        """Run one persistent client until deadline."""
        route = "select1"
        sequence = 0
        while time.perf_counter() < deadline:
            sequence += 1
            async with session_factory() as session:
                sample = await self._run_query(session, route)
            samples.append(sample)
            if interval_s > 0:
                await asyncio.sleep(interval_s)

    async def run_config(self, config: PoolConfig) -> list[BenchmarkResult]:
        """Run benchmark for a single pool configuration across all concurrency levels."""
        print(f"\n{'='*60}")
        print(f"Testing config: {config.short_name()}")
        print(f"  pool_size={config.pool_size}, max_overflow={config.max_overflow}, "
              f"pre_ping={config.pool_pre_ping}, recycle={config.pool_recycle}")
        print(f"{'='*60}")

        results = []

        for concurrency in self.concurrency_levels:
            print(f"\n  Concurrency: {concurrency}")

            # Create fresh engine for this configuration
            engine = self._create_engine(config)
            self._attach_pool_listeners(engine, config)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)

            # Clear events for this run
            self._pool_events.clear()
            query_samples: list[QuerySample] = []

            interval_s = self.interval_ms / 1000.0

            # Warmup phase
            if self.warmup_seconds > 0:
                print(f"    Warmup: {self.warmup_seconds}s")
                warmup_deadline = time.perf_counter() + self.warmup_seconds
                tasks = [
                    asyncio.create_task(self._worker(session_factory, concurrency, warmup_deadline, interval_s, [], i))
                    for i in range(concurrency)
                ]
                await asyncio.gather(*tasks)
                # Clear warmup events
                self._pool_events.clear()

            # Measurement phase
            print(f"    Measurement: {self.duration_seconds}s")
            measurement_deadline = time.perf_counter() + self.duration_seconds
            measurement_started = datetime.now(UTC).isoformat()
            tasks = [
                asyncio.create_task(self._worker(session_factory, concurrency, measurement_deadline, interval_s, query_samples, i))
                for i in range(concurrency)
            ]
            measurement_start_time = time.perf_counter()
            await asyncio.gather(*tasks)
            measurement_elapsed = time.perf_counter() - measurement_start_time
            measurement_ended = datetime.now(UTC).isoformat()

            # Summarize
            summary = summarize_samples(query_samples, measurement_elapsed)

            # Pool event summary
            checkout_events = [e for e in self._pool_events if e.event_type == "checkout"]
            checkout_durations = [e.duration_ms for e in checkout_events if e.duration_ms is not None]
            connect_events = [e for e in self._pool_events if e.event_type == "connect"]
            invalidate_events = [e for e in self._pool_events if e.event_type == "invalidate"]

            pool_summary = {
                "total_checkouts": len(checkout_events),
                "checkout_latency_ms": {
                    "mean": statistics.fmean(checkout_durations) if checkout_durations else None,
                    "p50": percentile(checkout_durations, 50),
                    "p95": percentile(checkout_durations, 95),
                    "p99": percentile(checkout_durations, 99),
                } if checkout_durations else None,
                "physical_connections_created": len(connect_events),
                "invalidations": len(invalidate_events),
            }

            result = BenchmarkResult(
                config=config,
                concurrency=concurrency,
                warmup_seconds=self.warmup_seconds,
                duration_seconds=self.duration_seconds,
                interval_ms=self.interval_ms,
                pool_events=self._pool_events.copy(),
                query_samples=query_samples,
                summary={
                    "queries": summary,
                    "pool": pool_summary,
                },
                started_at=measurement_started,
                ended_at=measurement_ended,
            )
            results.append(result)

            # Print summary
            q_summary = summary
            print(f"    Requests: {q_summary['requests']}, "
                  f"RPS: {q_summary['requests_per_second']:.2f}, "
                  f"p50: {q_summary['latency_ms']['p50']}ms, "
                  f"p95: {q_summary['latency_ms']['p95']}ms, "
                  f"p99: {q_summary['latency_ms']['p99']}ms, "
                  f"errors: {q_summary['error_requests']}")
            if pool_summary["checkout_latency_ms"]:
                cl = pool_summary["checkout_latency_ms"]
                print(f"    Pool checkouts: {pool_summary['total_checkouts']}, "
                      f"checkout p50: {cl['p50']}ms, p95: {cl['p95']}ms, "
                      f"new connections: {pool_summary['physical_connections_created']}")

            await engine.dispose()

        return results

    async def run_all(self, configs: list[PoolConfig]) -> dict[str, object]:
        """Run benchmarks for all configurations."""
        all_results: dict[str, list[BenchmarkResult]] = {}
        metadata = {
            "experiment_name": "ComicPile Pool Configuration Benchmark",
            "harness_version": "pool-benchmark-v1",
            "result_schema_version": 1,
            "git_commit_sha": None,
            "python_version": __import__("platform").python_version(),
            "database_identity": f"sha256:{__import__('hashlib').sha256(self.database_url.encode()).hexdigest()}",
            "concurrency_levels": self.concurrency_levels,
            "warmup_seconds": self.warmup_seconds,
            "duration_seconds": self.duration_seconds,
            "interval_ms": self.interval_ms,
            "timeout_seconds": self.timeout_seconds,
            "captured_at": datetime.now(UTC).isoformat(),
        }

        for config in configs:
            results = await self.run_config(config)
            all_results[config.short_name()] = results

        # Write results
        output = {
            "metadata": metadata,
            "results": {
                config_name: [self._result_to_dict(r) for r in results]
                for config_name, results in all_results.items()
            },
        }

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = self.output_dir / f"pool-benchmark-{timestamp}.json"
        output_path.write_text(json.dumps(output, indent=2, default=str))
        print(f"\nResults written to {output_path}")

        # Also write a summary CSV for easy comparison
        self._write_summary_csv(all_results, self.output_dir / f"pool-benchmark-summary-{timestamp}.csv")

        return output

    def _result_to_dict(self, result: BenchmarkResult) -> dict[str, object]:
        return {
            "config": result.config.to_dict(),
            "concurrency": result.concurrency,
            "warmup_seconds": result.warmup_seconds,
            "duration_seconds": result.duration_seconds,
            "interval_ms": result.interval_ms,
            "summary": result.summary,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "pool_event_count": len(result.pool_events),
            "query_sample_count": len(result.query_samples),
        }

    def _write_summary_csv(self, all_results: dict[str, list[BenchmarkResult]], path: Path):
        """Write a summary CSV for easy comparison across configs."""
        import csv
        rows = []
        for config_name, results in all_results.items():
            for r in results:
                q = r.summary["queries"]
                p = r.summary["pool"]
                row = {
                    "config": config_name,
                    "pool_size": r.config.pool_size,
                    "max_overflow": r.config.max_overflow,
                    "pool_pre_ping": r.config.pool_pre_ping,
                    "pool_recycle": r.config.pool_recycle,
                    "concurrency": r.concurrency,
                    "requests": q["requests"],
                    "rps": q["requests_per_second"],
                    "p50_ms": q["latency_ms"]["p50"],
                    "p95_ms": q["latency_ms"]["p95"],
                    "p99_ms": q["latency_ms"]["p99"],
                    "errors": q["error_requests"],
                    "checkout_count": p["total_checkouts"],
                    "checkout_p50_ms": p["checkout_latency_ms"]["p50"] if p["checkout_latency_ms"] else None,
                    "checkout_p95_ms": p["checkout_latency_ms"]["p95"] if p["checkout_latency_ms"] else None,
                    "new_connections": p["physical_connections_created"],
                    "invalidations": p["invalidations"],
                }
                rows.append(row)

        if rows:
            fieldnames = list(rows[0].keys())
            with path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"Summary CSV written to {path}")


def main() -> None:
    """Run the CLI and write the JSON result document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Database URL (defaults to DATABASE_URL env var)",
    )
    parser.add_argument(
        "--configs",
        default="all",
        help="Pool configurations to test: 'all' for defaults, or semicolon-separated 'size,overflow,pre_ping,recycle'",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        action="append",
        help="Concurrency levels (repeat for multiple); defaults to 1,2,4,8,16,32",
    )
    parser.add_argument("--warmup-seconds", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--interval-ms", type=float, default=DEFAULT_INTERVAL_MS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/results"),
        help="Output directory for results",
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("DATABASE_URL must be set via --database-url or environment variable")

    if args.configs == "all":
        configs = [PoolConfig(*c) for c in DEFAULT_CONFIGS]
    else:
        configs = parse_configs(args.configs)

    concurrency = args.concurrency or DEFAULT_CONCURRENCY

    benchmark = PoolBenchmark(
        database_url=args.database_url,
        concurrency_levels=concurrency,
        warmup_seconds=args.warmup_seconds,
        duration_seconds=args.duration_seconds,
        interval_ms=args.interval_ms,
        timeout_seconds=args.timeout_seconds,
        output_dir=args.output_dir,
    )

    asyncio.run(benchmark.run_all(configs))


if __name__ == "__main__":
    main()