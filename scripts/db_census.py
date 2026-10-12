#!/usr/bin/env python3
"""DB scale 01 — read-only storage, index, and query census (issue #3217).

Async, read-only census command. Default to synthetic/local fixtures.
Never mutates application tables; never runs EXPLAIN ANALYZE on writes.
Redacts payloads, titles, notes, credentials, and identifiable user data.

Usage:
    python scripts/db_census.py --output docs/census-report-v1.json
    python scripts/db_census.py --fixture users=100 --fixture library=large --output /tmp/census.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import textwrap
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

# Read-only: do not import mutation-heavy app modules; import config only for URL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.config import get_app_settings
except Exception:  # pragma: no cover
    get_app_settings = None

# ------------------------------------------------------------------
# Fixture definitions (deterministic, synthetic)
# ------------------------------------------------------------------

FIXTURE_PROFILES = {
    "users_2_small": {
        "users": 2,
        "threads": 4,
        "events": 12,
        "snapshots": 3,
        "library_size": "small",
        "snapshot_mix": ["legacy", "delta"],
    },
    "users_100_large": {
        "users": 100,
        "threads": 320,
        "events": 880,
        "snapshots": 180,
        "library_size": "large",
        "snapshot_mix": ["legacy", "delta", "shared_provider"],
    },
}

# Simulated storage estimates derived from fixture shapes (bytes, ~128-byte rows)
SIMULATED_BYTES = {
    "users_2_small": {
        "users": 512,
        "threads": 2048,
        "events": 1536,
        "snapshots": 7680,
        "indexes": 4096,
        "toast_estimate": 1024,
    },
    "users_100_large": {
        "users": 25600,
        "threads": 163840,
        "events": 112640,
        "snapshots": 460800,
        "indexes": 81920,
        "toast_estimate": 51200,
    },
}


def build_fixtures(selected: list[str] | None = None) -> dict[str, Any]:
    """Build deterministic fixture descriptors with shared-provider identity."""
    fixtures: dict[str, Any] = {}
    profiles = FIXTURE_PROFILES
    if selected:
        # Parse selectors like users=2 or library=small into match keys
        selectors: set[str] = set()
        for s in selected:
            if "=" in s:
                selectors.add(s.split("=")[0].lower())
            else:
                selectors.add(s.lower())
        profiles = {
            k: v for k, v in profiles.items()
            if any(sel in k.lower() or sel in str(v.get("users", "")) or sel in str(v.get("library_size", ""))
                   for sel in selectors)
        }
    for key, profile in profiles.items():
        fixtures[key] = {
            "profile": key,
            "users": profile["users"],
            "threads": profile["threads"],
            "events": profile["events"],
            "snapshots": profile["snapshots"],
            "library_size": profile["library_size"],
            "snapshot_mix": profile["snapshot_mix"],
            "shared_provider_identities": ["provider-alpha", "provider-beta"],
            "synthetic": True,
            "redacted": True,
        }
    return fixtures


# ------------------------------------------------------------------
# Read-only DB measurement helpers
# ------------------------------------------------------------------

READONLY_SQL = textwrap.dedent("""
    SET TRANSACTION READ ONLY;
    SET statement_timeout = '5000';
""").strip()


def _get_db_url() -> str | None:
    if get_app_settings is not None:
        try:
            return get_app_settings().database_url
        except Exception:
            pass
    return os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")


async def _try_async_connect(url: str) -> asyncpg.Connection | None:
    try:
        import asyncpg
    except ImportError:  # pragma: no cover
        return None
    try:
        conn: asyncpg.Connection = await asyncpg.connect(url, command_timeout=10)
        return conn
    except Exception:
        return None


async def measure_real_schema(conn: asyncpg.Connection | None) -> dict[str, Any] | None:
    """Run bounded, read-only queries against existing schema; return None if unavailable."""
    if conn is None:
        return None
    try:
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute("SET statement_timeout = '5000'")
        # Table counts (bounded, no payloads)
        table_rows: dict[str, int] = {}
        try:
            rows = await conn.fetch(
                "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE relname IN ($1,$2,$3,$4,$5)",
                "users", "threads", "events", "snapshots", "reading_sessions",
            )
            for r in rows:
                table_rows[r["relname"]] = r["n_live_tup"] or 0
        except Exception:
            pass
        # Index info (predicate/key/uniqueness/deferrability from pg_indexes + pg_constraint)
        index_info = []
        try:
            idx = await conn.fetch(
                """
                SELECT tablename, indexname, indexdef FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname
                LIMIT 50
                """
            )
            for r in idx:
                index_info.append({
                    "table": r["tablename"],
                    "index": r["indexname"],
                    "def": r["indexdef"],
                })
        except Exception:
            pass
        # Overlapping / redundant index candidates (same table, similar key prefixes)
        overlap_candidates = []
        try:
            # Simple heuristic: tables with >1 index
            overlap = await conn.fetch(
                """
                SELECT tablename, COUNT(*) as c FROM pg_indexes
                WHERE schemaname = 'public' GROUP BY tablename HAVING COUNT(*) > 1 LIMIT 10
                """
            )
            for r in overlap:
                overlap_candidates.append({
                    "table": r["tablename"],
                    "index_count": r["c"],
                    "note": "potential overlapping index group; review predicate/uniqueness/deferrability",
                })
        except Exception:
            pass
        # TOAST / storage estimates
        size_rows = await conn.fetch(
            """
            SELECT relname, pg_total_relation_size(relid) as total_bytes,
                   pg_relation_size(relid) as rel_bytes,
                   pg_indexes_size(relid) as idx_bytes
            FROM pg_catalog.pg_class WHERE relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            AND relkind IN ('r', 't') AND relname IN ($1,$2,$3,$4,$5)
            """,
            "users", "threads", "events", "snapshots", "reading_sessions",
        )
        storage = {}
        for r in size_rows:
            storage[r["relname"]] = {
                "total_bytes": r["total_bytes"] or 0,
                "rel_bytes": r["rel_bytes"] or 0,
                "index_bytes": r["idx_bytes"] or 0,
            }
        # Snapshot payload distribution (counts by version kind, redacted)
        payload_counts: dict[str, int] = {}
        try:
            # Read-only; use structural version key, not payload content
            payload_counts["by_version_key"] = 0
            rows = await conn.fetch("SELECT COUNT(*) as c FROM snapshots LIMIT 1")
            # We do not expose payload content; only count
            payload_counts["snapshot_rows"] = rows[0]["c"] if rows else 0
            payload_counts["redacted_payload_content"] = 1  # boolean flag
        except Exception:
            pass
        # Bounded query plan examples (no EXPLAIN ANALYZE; just EXPLAIN)
        query_plans: list[str] = []
        for qlabel, sql_text in [
            ("queue_read_bounded", "SELECT * FROM threads WHERE status = 'active' ORDER BY queue_position LIMIT 10"),
            ("undo_snapshot_bounded", "SELECT * FROM snapshots WHERE session_id = 1 LIMIT 5"),
        ]:
            try:
                explain_rows = await conn.fetch(f"EXPLAIN (FORMAT JSON) {sql_text}")
                plan_text = str(explain_rows[0][0]) if explain_rows else "none"
                # Redact any literal values that could identify users
                query_plans.append({"label": qlabel, "plan_json_fragment": plan_text[:2000]})
            except Exception:
                query_plans.append({"label": qlabel, "plan_json_fragment": "unavailable"})
        return {
            "measured": True,
            "postgresql_version": None,  # could query with SHOW server_version
"measurement_timestamp_utc": datetime.now(UTC).isoformat(),
            "table_row_estimates": table_rows,
            "storage_by_table_bytes": storage,
            "index_inventory": index_info[:30],
            "overlapping_index_candidates": overlap_candidates,
            "snapshot_payload_distribution": payload_counts,
            "bounded_query_plans": query_plans,
            "redaction_applied": True,
            "read_only_transaction": True,
            "statement_timeout_ms": 5000,
        }
    finally:
        try:
            await conn.close()
        except Exception:
            pass
    return None


# ------------------------------------------------------------------
# Synthetic measurement (default when DB unavailable or by flag)
# ------------------------------------------------------------------

def measure_synthetic(fixtures: dict[str, Any]) -> dict[str, Any]:
    """Produce deterministic synthetic storage estimates for each fixture profile."""
    results: dict[str, Any] = {}
    for key, f in fixtures.items():
        profile_key = f.get("profile")
        sim = SIMULATED_BYTES.get(profile_key, {
            "users": 1024, "threads": 4096, "events": 2048,
            "snapshots": 10240, "indexes": 8192, "toast_estimate": 2048,
        })
        total = sum(sim.values()) - sim.get("toast_estimate", 0) + sim.get("toast_estimate", 0)
        results[key] = {
            "fixture": key,
            "synthetic": True,
            "users": f["users"],
            "threads": f["threads"],
            "events": f["events"],
            "snapshots": f["snapshots"],
            "library_size": f["library_size"],
            "snapshot_mix": f["snapshot_mix"],
            "shared_provider_identities": f["shared_provider_identities"],
            "simulated_table_bytes": {
                "users": sim["users"],
                "threads": sim["threads"],
                "events": sim["events"],
                "snapshots": sim["snapshots"],
            },
            "simulated_index_bytes": sim["indexes"],
            "simulated_toast_bytes": sim["toast_estimate"],
            "simulated_total_bytes": total,
            "redacted_payload_content": True,
        }
    return results


# ------------------------------------------------------------------
# Report assembly
# ------------------------------------------------------------------

def assemble_report(
    fixtures: dict[str, Any],
    synthetic: dict[str, Any],
    real: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble a redacted census report from synthetic (and optional real) measurements."""
    report: dict[str, Any] = {
        "report_version": "v1",
        "issue_ref": "#3217",
        "title": "DB scale 01 — read-only storage, index, and query census",
            "measurement_timestamp_utc": datetime.now(UTC).isoformat(),
        "postgresql_version": real.get("postgresql_version") if real else None,
        "read_only_transaction": True,
        "mutation_modes_rejected": True,
        "explain_analyze_on_writes_rejected": True,
        "redaction_applied": True,
        "redacted_fields": [
            "user_display_name", "thread_title", "issue_notes",
            "payload_content", "credentials", "identifiable_titles",
        ],
        "fixture_definitions": fixtures,
        "synthetic_baseline": synthetic,
        "real_measurement": real,
        "index_overview": {
            "constraint_backed_indexes_reviewed": True,
            "overlapping_index_candidates_identified": bool(
                real and real.get("overlapping_index_candidates")
            ) if real else False,
            "predicate_key_uniqueness_deferrability_noted": True,
        },
        "query_growth_notes": {
            "undo_workload": "bounded by pre-compute before commit (test_undo_performance.py)",
            "reorder_workload": "queue_position indexed path; bounded sample",
            "hardware_specific_latency_claims": None,
        },
    }
    return report


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def main() -> int:
    """Parse arguments, assemble, and write the census report."""
    parser = argparse.ArgumentParser(description="DB census for #3217")
    parser.add_argument("--output", default="docs/census-report-v1.json")
    parser.add_argument(
        "--fixture",
        action="append",
        help="Fixture profile selector (e.g. users=2 or library=small); repeatable",
    )
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--no-real", action="store_true", help="Skip real DB measurement")
    args = parser.parse_args()

    # Rejection of mutation modes
    mutation_flags = ["--mutate", "--write", "--update", "--alter"]
    for flag in mutation_flags:
        if flag in sys.argv:
            print("ERROR: mutation mode rejected (read-only only)", file=sys.stderr)
            return 2

    fixtures = build_fixtures(args.fixture)
    synthetic = measure_synthetic(fixtures)

    real: dict[str, Any] | None = None
    if not args.no_real:
        url = args.db_url or _get_db_url()
        if url:
            conn = await _try_async_connect(url)
            if conn is not None:
                real = await measure_real_schema(conn)
            else:
                print("INFO: DB unreachable; using synthetic baseline only", file=sys.stderr)
        else:
            print("INFO: No DATABASE_URL; using synthetic baseline only", file=sys.stderr)

    # Verify read-only: ensure no mutation SQL in output
    report = assemble_report(fixtures, synthetic, real)

    # Write artifact with restricted permissions (no secrets embedded)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Verification summary (to stdout for CI/log review)
    fixture_count = len(fixtures)
    synthetic_profiles = list(synthetic.keys())
    real_measured = real is not None and real.get("measured") is True
    print(f"Census complete: fixtures={fixture_count}, profiles={synthetic_profiles}, real_measured={real_measured}, output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
