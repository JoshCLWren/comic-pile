#!/usr/bin/env python3
"""DB scale 09 — read-only reader-ownership consistency preflight (issue #3225).

Reports cross-reader ownership violations across graph and library write
boundaries WITHOUT private payloads: output contains per-category counts and
row IDs only — never titles, notes, ratings, event payloads, or credentials.

Categories: thread frontier mismatches, cross-user dependency endpoints,
plan-issue / plan-dependency cross-user rows, session pending cross-user or
mismatched pairs, private-tag assignments on another reader's target.

Read-only: SET TRANSACTION READ ONLY + 5s statement timeout. Never mutates
application tables, never backfills, never auto-repairs. Shared catalog links
(catalog_issue_id / catalog_series_id) are never consulted: shared identity
is not authorization evidence.

Usage:
    python scripts/check_ownership_consistency.py --database-url "$TEST_DATABASE_URL"
    python scripts/check_ownership_consistency.py --database-url "$DATABASE_URL" \
        --output /tmp/ownership.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.config import get_app_settings
except Exception:  # pragma: no cover
    get_app_settings = None


QUERIES: dict[str, str] = {
    "frontier_thread_ids": (
        "SELECT t.id FROM threads t "
        "LEFT JOIN issues i ON i.id = t.next_unread_issue_id AND i.thread_id = t.id "
        "WHERE t.next_unread_issue_id IS NOT NULL AND i.id IS NULL ORDER BY t.id"
    ),
    "cross_user_dependency_ids": (
        "SELECT d.id FROM dependencies d "
        "JOIN issues si ON si.id = d.source_issue_id "
        "JOIN threads st ON st.id = si.thread_id "
        "JOIN issues ti ON ti.id = d.target_issue_id "
        "JOIN threads tt ON tt.id = ti.thread_id "
        "WHERE st.user_id <> tt.user_id ORDER BY d.id"
    ),
    "plan_issue_pairs": (
        "SELECT rpi.plan_id, rpi.issue_id FROM reading_plan_issues rpi "
        "JOIN continuity_plans p ON p.id = rpi.plan_id "
        "JOIN issues i ON i.id = rpi.issue_id "
        "JOIN threads t ON t.id = i.thread_id "
        "WHERE t.user_id <> p.user_id ORDER BY rpi.plan_id, rpi.issue_id"
    ),
    "plan_dependency_source_pairs": (
        "SELECT rpd.plan_id, rpd.dependency_id FROM reading_plan_dependencies rpd "
        "JOIN continuity_plans p ON p.id = rpd.plan_id "
        "JOIN dependencies d ON d.id = rpd.dependency_id "
        "JOIN issues i ON i.id = d.source_issue_id "
        "JOIN threads t ON t.id = i.thread_id "
        "WHERE t.user_id <> p.user_id ORDER BY rpd.plan_id, rpd.dependency_id"
    ),
    "plan_dependency_target_pairs": (
        "SELECT rpd.plan_id, rpd.dependency_id FROM reading_plan_dependencies rpd "
        "JOIN continuity_plans p ON p.id = rpd.plan_id "
        "JOIN dependencies d ON d.id = rpd.dependency_id "
        "JOIN issues i ON i.id = d.target_issue_id "
        "JOIN threads t ON t.id = i.thread_id "
        "WHERE t.user_id <> p.user_id ORDER BY rpd.plan_id, rpd.dependency_id"
    ),
    "session_pending_thread_ids": (
        "SELECT s.id FROM sessions s "
        "JOIN threads t ON t.id = s.pending_thread_id "
        "WHERE s.pending_thread_id IS NOT NULL AND t.user_id <> s.user_id ORDER BY s.id"
    ),
    "session_pending_issue_ids": (
        "SELECT s.id FROM sessions s "
        "JOIN issues i ON i.id = s.pending_issue_id "
        "JOIN threads t ON t.id = i.thread_id "
        "WHERE s.pending_issue_id IS NOT NULL AND t.user_id <> s.user_id ORDER BY s.id"
    ),
    "session_pending_mismatch_ids": (
        "SELECT s.id FROM sessions s "
        "JOIN issues i ON i.id = s.pending_issue_id "
        "WHERE s.pending_issue_id IS NOT NULL AND s.pending_thread_id IS NOT NULL "
        "AND i.thread_id <> s.pending_thread_id ORDER BY s.id"
    ),
    "private_tag_thread_assignment_ids": (
        "SELECT ta.id FROM tag_assignments ta "
        "JOIN tags g ON g.id = ta.tag_id "
        "JOIN threads t ON t.id = ta.target_id "
        "WHERE g.scope = 'private' AND ta.target_type = 'Thread' "
        "AND t.user_id <> g.owner_user_id ORDER BY ta.id"
    ),
    "private_tag_issue_assignment_ids": (
        "SELECT ta.id FROM tag_assignments ta "
        "JOIN tags g ON g.id = ta.tag_id "
        "JOIN issues i ON i.id = ta.target_id "
        "JOIN threads t ON t.id = i.thread_id "
        "WHERE g.scope = 'private' AND ta.target_type = 'Issue' "
        "AND t.user_id <> g.owner_user_id ORDER BY ta.id"
    ),
    "private_tag_plan_assignment_ids": (
        "SELECT ta.id FROM tag_assignments ta "
        "JOIN tags g ON g.id = ta.tag_id "
        "JOIN continuity_plans p ON p.id = ta.target_id "
        "WHERE g.scope = 'private' AND ta.target_type = 'ContinuityPlan' "
        "AND p.user_id <> g.owner_user_id ORDER BY ta.id"
    ),
}


def _resolve_database_url(explicit: str | None) -> str | None:
    """Resolve the database URL from flags, settings, or environment."""
    if explicit:
        return explicit
    if get_app_settings is not None:
        try:
            return str(get_app_settings().database_url)
        except Exception:
            pass
    return os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")


async def _collect(conn: asyncpg.Connection) -> dict[str, object]:
    """Run every violation query and return the redacted report."""
    await conn.execute("SET TRANSACTION READ ONLY")
    await conn.execute("SET statement_timeout = '5000'")
    id_lists: dict[str, list[int]] = {}
    pair_lists: dict[str, list[list[int]]] = {}
    for name, sql in QUERIES.items():
        rows = await conn.fetch(sql)
        if name.endswith("_pairs"):
            pair_lists[name] = sorted([[int(row[0]), int(row[1])] for row in rows])
        else:
            id_lists[name] = sorted([int(row[0]) for row in rows])
    # Merge source/target plan-dependency pairs into one category.
    merged_deps = sorted(
        {
            (pair[0], pair[1])
            for pair in pair_lists["plan_dependency_source_pairs"]
            + pair_lists["plan_dependency_target_pairs"]
        }
    )
    # Merge per-target private-tag assignments into one category.
    merged_tags = sorted(
        set(id_lists["private_tag_thread_assignment_ids"])
        | set(id_lists["private_tag_issue_assignment_ids"])
        | set(id_lists["private_tag_plan_assignment_ids"])
    )
    categories: dict[str, dict[str, object]] = {}
    for name, ids in id_lists.items():
        if name.startswith("private_tag_"):
            continue
        categories[name] = {"count": len(ids), "ids": ids}
    for name, pairs in pair_lists.items():
        if name.startswith("plan_dependency_"):
            continue
        categories[name] = {"count": len(pairs), "ids": pairs}
    categories["plan_dependency_pairs"] = {
        "count": len(merged_deps),
        "ids": [[first, second] for first, second in merged_deps],
    }
    categories["private_tag_assignment_ids"] = {
        "count": len(merged_tags),
        "ids": merged_tags,
    }
    has_violations = any(
        category["count"] != 0 for category in categories.values()
    )
    return {"categories": categories, "has_violations": has_violations}


async def main() -> int:
    """Entry point for the ownership consistency preflight."""
    parser = argparse.ArgumentParser(description="Ownership preflight for #3225")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    url = _resolve_database_url(args.database_url or args.db_url)
    if not url:
        print("ERROR: no database URL (pass --database-url)", file=sys.stderr)
        return 2
    if "postgresql" not in url:
        print("ERROR: refusing non-PostgreSQL URL", file=sys.stderr)
        return 2

    try:
        import asyncpg as asyncpg_module
    except ImportError:
        print("ERROR: asyncpg is not installed", file=sys.stderr)
        return 2

    conn = await asyncpg_module.connect(url, command_timeout=10)
    try:
        report = await _collect(conn)
    finally:
        await conn.close()

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)
    return 1 if report["has_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
