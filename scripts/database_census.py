#!/usr/bin/env python3
"""Read-only storage, index, and query census command (issue #3217).

Defaults to synthetic data. Connecting to a real database requires an explicit
``--database-url`` and is always read-only with a statement timeout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.database_census_service import (
    CENSUS_REPORT_VERSION,
    DEFAULT_SAMPLE_LIMIT,
    DatabaseCensusService,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the census argument parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="database_census",
        description=(
            "Read-only storage, index, and query census. Defaults to synthetic "
            "data; a real database requires an explicit --database-url."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Explicitly supplied database URL. When omitted the command emits "
            "synthetic data and never touches a database."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write the JSON report to this path instead of stdout.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-statement timeout in seconds for a supplied database (default: 30).",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=DEFAULT_SAMPLE_LIMIT,
        help=(
            "Maximum rows pulled for any bounded workload sample "
            f"(default: {DEFAULT_SAMPLE_LIMIT})."
        ),
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Force synthetic output even when --database-url is supplied.",
    )
    parser.add_argument(
        "--report-version",
        action="version",
        version=CENSUS_REPORT_VERSION,
    )
    return parser


def synthetic_report(sample_limit: int = DEFAULT_SAMPLE_LIMIT) -> dict[str, Any]:
    """Return a deterministic synthetic report used when no database is supplied.

    Args:
        sample_limit: Sample ceiling echoed into the synthetic metadata.

    Returns:
        A report with the same shape as a measured census.
    """
    return {
        "report_version": CENSUS_REPORT_VERSION,
        "synthetic": True,
        "metadata": {
            "collected_at": "2026-01-01T00:00:00+00:00",
            "postgresql_version": "synthetic",
            "statement_timeout_seconds": 0,
            "sample_limit": sample_limit,
            "read_only_transaction": True,
        },
        "storage": {
            "tables": [
                {
                    "schema": "public",
                    "name": "users",
                    "total_bytes": 16384,
                    "table_bytes": 8192,
                    "index_bytes": 8192,
                    "total": "16 kB",
                    "table": "8192 bytes",
                    "index": "8192 bytes",
                }
            ],
            "toast": [],
        },
        "tables": {"users": {"measured_rows": 0, "estimated_rows": 0, "estimate_delta": 0}},
        "indexes": {
            "count": 0,
            "by_table": {},
            "potential_redundant_indexes": [],
        },
        "snapshots": {
            "by_version": [],
            "session_state": {
                "measured_rows": 0,
                "distinct_sessions": 0,
                "rows_with_session_state": 0,
                "rows_without_session_state": 0,
                "avg_session_state_bytes": 0,
            },
            "workload_growth": {
                "sampled_readers": 0,
                "latest_undo": [],
                "reorder": {
                    "reorder_event_rows": 0,
                    "distinct_threads_moved": 0,
                    "queue_move_bytes": 0,
                },
                "note": (
                    "Rows and payload bytes only. No hardware-specific latency "
                    "pass/fail claim is made or implied."
                ),
            },
        },
        "queries": {},
        "constraints": {
            "primary_keys": [],
            "foreign_keys": [],
            "unique_constraints": [],
        },
    }


def write_report(report: dict[str, Any], output_path: str | None) -> None:
    """Serialize the report to a file or stdout.

    Args:
        report: Census report.
        output_path: Destination path, or ``None`` to write to stdout.
    """
    serialized = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if output_path is None:
        print(serialized)
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized + "\n", encoding="utf-8")


async def run_census(
    database_url: str,
    output_file: str | None = None,
    timeout_seconds: int = 30,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Run the read-only census against an explicitly supplied database.

    Args:
        database_url: Explicitly supplied database URL.
        output_file: Optional destination path for the JSON report.
        timeout_seconds: Per-statement timeout in seconds.
        sample_limit: Maximum rows pulled for any bounded workload sample.

    Returns:
        The redacted census report.
    """
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            service = DatabaseCensusService(
                session,
                timeout_seconds=timeout_seconds,
                sample_limit=sample_limit,
            )
            report = await service.collect_census()
    finally:
        await engine.dispose()
    write_report(report, output_file)
    return report


async def main(argv: list[str] | None = None) -> int:
    """Run the census command.

    Args:
        argv: Optional argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit status; zero means the report was produced.
    """
    args = build_parser().parse_args(argv)

    if args.synthetic or not args.database_url:
        report = synthetic_report(sample_limit=args.sample_limit)
        write_report(report, args.output)
        return 0

    try:
        await run_census(
            database_url=args.database_url,
            output_file=args.output,
            timeout_seconds=args.timeout,
            sample_limit=args.sample_limit,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"census failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))