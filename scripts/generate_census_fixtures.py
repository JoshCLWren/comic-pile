#!/usr/bin/env python3
"""Deterministic synthetic census fixtures for issue #3217.

The issue contract requires reproducible fixtures representing 2 and 100 users,
small and large libraries, mixed legacy/delta snapshots, and shared provider
identities, plus a published synthetic measured baseline.

Every value here is a deterministic function of the scenario parameters, so the
same command produces byte-identical output on every run. The script does not
connect to any database: it seeds nothing and reads nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.database_census_service import CENSUS_REPORT_VERSION


#: Fixed collection instant so repeated runs are byte-identical.
FIXTURE_TIMESTAMP = "2026-01-01T00:00:00+00:00"

#: Bytes-per-row model constants used to synthesize storage numbers. These are
#: declared modelling assumptions for the synthetic baseline, not measurements.
USER_ROW_BYTES = 512
THREAD_ROW_BYTES = 4096
ISSUE_ROW_BYTES = 1024
SNAPSHOT_ROW_BYTES = 2048
INDEX_OVERHEAD_RATIO = 0.5


def _synthetic_report(
    scenario: str,
    user_count: int,
    thread_count: int,
    issue_count: int,
    snapshot_count: int,
    legacy_snapshot_count: int,
    shared_provider_identity_count: int,
    legacy_version: str = "1",
    delta_version: str = "2",
) -> dict[str, Any]:
    """Build one deterministic synthetic census report.

    Args:
        scenario: Scenario label recorded in metadata.
        user_count: Number of synthetic users.
        thread_count: Number of synthetic threads.
        issue_count: Number of synthetic issues.
        snapshot_count: Number of synthetic snapshots.
        legacy_snapshot_count: Snapshots using the legacy full-state payload.
        shared_provider_identity_count: Provider identities shared across users.
        legacy_version: Payload version label for legacy snapshots.
        delta_version: Payload version label for delta snapshots.

    Returns:
        A deterministic report shaped like a measured census.
    """
    delta_snapshot_count = max(snapshot_count - legacy_snapshot_count, 0)
    threads_per_user = thread_count / user_count if user_count else 0.0

    table_bytes = {
        "users": user_count * USER_ROW_BYTES,
        "threads": thread_count * THREAD_ROW_BYTES,
        "issues": issue_count * ISSUE_ROW_BYTES,
        "snapshots": snapshot_count * SNAPSHOT_ROW_BYTES,
    }
    storage_tables = []
    for name, size in table_bytes.items():
        index_bytes = int(size * INDEX_OVERHEAD_RATIO)
        storage_tables.append(
            {
                "schema": "public",
                "name": name,
                "total_bytes": size + index_bytes,
                "table_bytes": size,
                "index_bytes": index_bytes,
                "total": f"{(size + index_bytes) / 1024:.1f} kB",
                "table": f"{size / 1024:.1f} kB",
                "index": f"{index_bytes / 1024:.1f} kB",
            }
        )

    legacy_payload_bytes = legacy_snapshot_count * SNAPSHOT_ROW_BYTES * 4
    delta_payload_bytes = delta_snapshot_count * SNAPSHOT_ROW_BYTES

    return {
        "report_version": CENSUS_REPORT_VERSION,
        "synthetic": True,
        "metadata": {
            "collected_at": FIXTURE_TIMESTAMP,
            "postgresql_version": "synthetic",
            "statement_timeout_seconds": 0,
            "sample_limit": 10,
            "read_only_transaction": True,
            "scenario": scenario,
            "user_count": user_count,
            "thread_count": thread_count,
            "issues_per_thread": round(issue_count / thread_count, 3) if thread_count else 0,
            "threads_per_user": round(threads_per_user, 3),
            "shared_provider_identity_count": shared_provider_identity_count,
        },
        "storage": {
            "tables": storage_tables,
            "toast": [
                {
                    "schema": "public",
                    "table": "snapshots",
                    "toast_bytes": legacy_payload_bytes,
                    "toast": f"{legacy_payload_bytes / 1024:.1f} kB",
                }
            ]
            if legacy_payload_bytes
            else [],
        },
        "tables": {
            name: {
                "measured_rows": rows,
                "estimated_rows": rows,
                "estimate_delta": 0,
            }
            for name, rows in (
                ("users", user_count),
                ("threads", thread_count),
                ("issues", issue_count),
                ("snapshots", snapshot_count),
            )
        },
        "indexes": {
            "count": 4,
            "by_table": {},
            "potential_redundant_indexes": [
                {
                    "table": "threads",
                    "index": "ix_threads_user_queue_position",
                    "covered_by": "ix_threads_user_status_queue_position",
                    "key_columns": ["user_id", "queue_position"],
                    "covering_key_columns": ["user_id", "status", "queue_position"],
                    "predicate": None,
                    "size_bytes": 0,
                    "classification": "potential_redundant",
                    "confirmed_safe_removal": False,
                    "reasons": ["has_recorded_scans"],
                }
            ],
        },
        "snapshots": {
            "by_version": [
                {
                    "version": legacy_version,
                    "measured_rows": legacy_snapshot_count,
                    "avg_payload_bytes": SNAPSHOT_ROW_BYTES * 4,
                    "max_payload_bytes": SNAPSHOT_ROW_BYTES * 8,
                    "min_payload_bytes": SNAPSHOT_ROW_BYTES * 2,
                    "total_payload_bytes": legacy_payload_bytes,
                },
                {
                    "version": delta_version,
                    "measured_rows": delta_snapshot_count,
                    "avg_payload_bytes": SNAPSHOT_ROW_BYTES,
                    "max_payload_bytes": SNAPSHOT_ROW_BYTES * 2,
                    "min_payload_bytes": SNAPSHOT_ROW_BYTES,
                    "total_payload_bytes": delta_payload_bytes,
                },
            ],
            "session_state": {
                "measured_rows": snapshot_count,
                "distinct_sessions": user_count,
                "rows_with_session_state": snapshot_count,
                "rows_without_session_state": 0,
                "avg_session_state_bytes": 512,
            },
            "workload_growth": {
                "sampled_readers": min(user_count, 10),
                "latest_undo": [
                    {
                        "sample_rank": rank,
                        "session_snapshot_rows": legacy_snapshot_count,
                        "thread_state_bytes": SNAPSHOT_ROW_BYTES * 4,
                        "session_state_bytes": 512,
                        "event_type": "roll",
                    }
                    for rank in range(1, min(user_count, 10) + 1)
                ],
                "reorder": {
                    "reorder_event_rows": max(user_count, 0),
                    "distinct_threads_moved": max(thread_count // max(user_count, 1), 1),
                    "queue_move_bytes": max(user_count, 0) * 16,
                },
                "note": (
                    "Rows and payload bytes only. No hardware-specific latency "
                    "pass/fail claim is made or implied."
                ),
            },
        },
        "queries": {},
        "constraints": {
            "primary_keys": [
                {
                    "table": "users",
                    "name": "users_pkey",
                    "key_columns": ["id"],
                    "is_deferrable": False,
                    "is_deferred": False,
                }
            ],
            "foreign_keys": [
                {
                    "table": "snapshots",
                    "name": "snapshots_session_id_fkey",
                    "column": "session_id",
                    "references_table": "sessions",
                    "references_column": "id",
                    "on_delete": "c",
                    "on_update": "a",
                    "is_deferrable": False,
                    "is_deferred": False,
                }
            ],
            "unique_constraints": [
                {
                    "table": "users",
                    "name": "users_username_key",
                    "key_columns": ["username"],
                    "is_deferrable": False,
                    "is_deferred": False,
                }
            ],
        },
    }


#: Issue #3217 requires deterministic fixtures for 2 and 100 users, small and
#: large libraries, mixed legacy/delta snapshots, and shared provider
#: identities. Each entry is fully determined by its parameters.
CENSUS_SCENARIOS: dict[str, dict[str, Any]] = {
    "small_library_2_users": {
        "user_count": 2,
        "thread_count": 10,
        "issue_count": 50,
        "snapshot_count": 20,
        "legacy_snapshot_count": 18,
        "shared_provider_identity_count": 6,
    },
    "large_library_100_users": {
        "user_count": 100,
        "thread_count": 2500,
        "issue_count": 15000,
        "snapshot_count": 7500,
        "legacy_snapshot_count": 750,
        "shared_provider_identity_count": 300,
    },
    "mixed_legacy_delta_snapshots": {
        "user_count": 25,
        "thread_count": 500,
        "issue_count": 3000,
        "snapshot_count": 4000,
        "legacy_snapshot_count": 2500,
        "shared_provider_identity_count": 75,
    },
}


def build_scenario(name: str) -> dict[str, Any]:
    """Build one named deterministic fixture.

    Args:
        name: Scenario key from :data:`CENSUS_SCENARIOS`.

    Returns:
        Deterministic report dictionary.

    Raises:
        KeyError: If the scenario name is unknown.
    """
    return _synthetic_report(scenario=name, **CENSUS_SCENARIOS[name])


def write_fixtures(output_dir: Path) -> list[Path]:
    """Write every deterministic fixture to disk.

    Args:
        output_dir: Destination directory.

    Returns:
        Sorted list of written fixture paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in sorted(CENSUS_SCENARIOS):
        path = output_dir / f"census_{name}.json"
        payload = json.dumps(build_scenario(name), indent=2, sort_keys=True)
        path.write_text(payload + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    """Generate the deterministic census fixtures.

    Args:
        argv: Optional argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit status; zero means every fixture was written.
    """
    parser = argparse.ArgumentParser(
        prog="generate_census_fixtures",
        description="Write deterministic synthetic census fixtures (issue #3217).",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/database-census/fixtures",
        help="Directory that receives the generated fixture JSON files.",
    )
    args = parser.parse_args(argv)

    for path in write_fixtures(Path(args.output_dir)):
        print(f"generated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())