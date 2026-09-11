#!/usr/bin/env python3
"""Read-only Step 14D audit for the remaining explicitly noted dependency families."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import sys
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AsyncSessionLocal = importlib.import_module("app.database").AsyncSessionLocal

USER_ID = 1
EVIDENCE = ROOT / "docs/recovery/step14d-noted-semantic-families-evidence.json"
STEP14A_PATTERN = r"^cbl-order:source:[^:]+:[0-9]+->[0-9]+$"
STEP14B_PATTERN = r"^cbl-order:group-16:[^:]+:[0-9]+->[0-9]+$"
STEP14B_TEMP_NOTE = "Temporary authoritative Ultimate Universe CBL order incident repair"
STEP14C_IDS = (
    18, 19, 20, 21, 1388, 1389, 1390, 1391, 1392, 1396, 1397, 1398,
    1399, 1400, 1404, 1414, 1789, 1791, 1792, 1793, 1794, 1795, 1796,
    1797, 1798, 1799, 1800, 1801, 1802, 1803, 1804, 1805, 1806, 1807,
    1808, 1810, 1811, 1812, 1813, 1814, 1815, 1816, 1817, 1818, 1819,
    1820, 1821, 1822, 1823, 1824, 1825, 1826, 1827, 1828, 1829, 1830,
    1832, 1833, 1846, 1847, 2678, 2679, 2680, 2681, 2682, 2683, 2684,
    2685, 2686, 2687, 2688, 2689, 2772, 2773, 2774, 2775, 2776,
)


def _sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def _stable(value: object) -> object:
    """Convert datetime values to stable JSON values."""
    return value.isoformat() if isinstance(value, datetime) else value


def _evidence() -> dict[str, object]:
    """Load the reviewed Step 14D exact-ID classification evidence."""
    return cast(dict[str, object], json.loads(EVIDENCE.read_text(encoding="utf-8")))


async def _select(
    db: AsyncSession,
    statement: str,
    params: dict[str, object],
) -> list[dict[str, object]]:
    """Execute one SELECT and return detached mapping rows."""
    if not statement.lstrip().upper().startswith("SELECT"):
        raise ValueError("Step 14D audit only permits SELECT statements")
    result = await db.execute(text(statement), params)
    return [dict(row) for row in result.mappings().all()]


def _scope_predicate() -> str:
    """Return the reviewed Step 14D scope predicate."""
    step14c = ",".join(str(value) for value in STEP14C_IDS)
    return f"""
      st.user_id = :user_id
      AND tt.user_id = :user_id
      AND d.note IS NOT NULL
      AND d.note !~ :step14a_pattern
      AND d.note !~ :step14b_pattern
      AND d.note <> :step14b_temp_note
      AND d.id NOT IN ({step14c})
    """


def _params() -> dict[str, object]:
    """Return fixed selector parameters."""
    return {
        "user_id": USER_ID,
        "step14a_pattern": STEP14A_PATTERN,
        "step14b_pattern": STEP14B_PATTERN,
        "step14b_temp_note": STEP14B_TEMP_NOTE,
    }


async def _snapshot(db: AsyncSession) -> dict[str, object]:
    """Capture the Step 14D production shape with SELECT statements only."""
    predicate = _scope_predicate()
    params = _params()
    dependencies = await _select(
        db,
        f"""
        SELECT d.id, d.created_at, d.source_issue_id, d.target_issue_id, d.note,
               si.status AS source_status,
               st.id AS source_thread_id, st.title AS source_title,
               si.issue_number AS source_issue_number,
               tt.id AS target_thread_id, tt.title AS target_title,
               ti.issue_number AS target_issue_number,
               tt.next_unread_issue_id AS target_next_unread_issue_id
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE {predicate}
        ORDER BY d.id
        """,
        params,
    )
    rules = await _select(
        db,
        f"""
        SELECT cr.id, cr.legacy_dependency_id, cr.source_type, cr.source_id,
               cr.target_type, cr.target_id, cr.satisfaction_type,
               cr.checkpoint_issue_id, cr.convergence_targets
        FROM continuity_rules cr
        WHERE cr.user_id = :user_id
          AND cr.legacy_dependency_id IN (
            SELECT d.id
            FROM dependencies d
            JOIN issues si ON si.id = d.source_issue_id
            JOIN threads st ON st.id = si.thread_id
            JOIN issues ti ON ti.id = d.target_issue_id
            JOIN threads tt ON tt.id = ti.thread_id
            WHERE {predicate}
          )
        ORDER BY cr.legacy_dependency_id, cr.id
        """,
        params,
    )
    groups = await _select(
        db,
        f"""
        SELECT dg.id AS group_id, d.id AS dependency_id,
               BOOL_OR(gm.sequence_order IS NOT NULL) AS ordered_membership_seen
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        JOIN dependency_group_memberships gm
          ON gm.issue_id IN (d.source_issue_id, d.target_issue_id)
          OR (gm.issue_id IS NULL AND gm.thread_id IN (si.thread_id, ti.thread_id))
        JOIN dependency_groups dg ON dg.id = gm.group_id AND dg.user_id = :user_id
        WHERE {predicate}
        GROUP BY dg.id, d.id
        ORDER BY dg.id, d.id
        """,
        params,
    )
    captured = await _select(db, "SELECT CURRENT_TIMESTAMP AS captured_at", {})
    return {
        "dependencies": dependencies,
        "rules": rules,
        "groups": groups,
        "captured_at": captured[0]["captured_at"],
    }


def _rows(snapshot: dict[str, object], key: str) -> list[dict[str, object]]:
    """Return one row collection from the snapshot."""
    value = snapshot[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} is not a row list")
    return cast(list[dict[str, object]], value)


def _manifest_index(
    evidence: dict[str, object],
) -> tuple[dict[int, tuple[str, str]], list[str]]:
    """Expand family manifests to one reviewed classification per dependency ID."""
    errors: list[str] = []
    index: dict[int, tuple[str, str]] = {}
    allowed = {"reading_plan_order", "standalone_prerequisite", "needs_review"}
    for family in cast(list[dict[str, object]], evidence["families"]):
        family_key = str(family["family_key"])
        classification = str(family["classification"])
        ids = cast(list[int], family["dependency_ids"])
        if classification not in allowed:
            errors.append(f"family {family_key} has invalid classification {classification!r}")
        if _sha256(ids) != family["sha256"]:
            errors.append(f"family {family_key} fingerprint drifted in evidence")
        for dependency_id in ids:
            if dependency_id in index:
                errors.append(f"duplicate family membership for dependency {dependency_id}")
            index[dependency_id] = (classification, family_key)
    return index, errors


def _linked_rule_errors(
    dependencies: list[dict[str, object]],
    rules: list[dict[str, object]],
) -> list[str]:
    """Require one exact legacy item_read mirror for every scoped dependency."""
    errors: list[str] = []
    linked: dict[int, list[dict[str, object]]] = defaultdict(list)
    for rule in rules:
        linked[int(rule["legacy_dependency_id"])].append(rule)
    for dependency in dependencies:
        dependency_id = int(dependency["id"])
        candidates = linked.get(dependency_id, [])
        if len(candidates) != 1:
            errors.append(f"dependency {dependency_id} has {len(candidates)} linked rules")
            continue
        rule = candidates[0]
        if (
            rule["source_type"] != "issue"
            or int(rule["source_id"]) != int(dependency["source_issue_id"])
            or rule["target_type"] != "issue"
            or int(rule["target_id"]) != int(dependency["target_issue_id"])
            or rule["satisfaction_type"] != "item_read"
            or rule["checkpoint_issue_id"] is not None
            or rule["convergence_targets"] not in (None, [])
        ):
            errors.append(f"dependency {dependency_id} no longer has an exact item_read mirror")
    return errors


def _build(snapshot: dict[str, object]) -> dict[str, object]:
    """Reconcile a fresh snapshot against the reviewed Step 14D evidence."""
    evidence = _evidence()
    scope = cast(dict[str, object], evidence["scope"])
    blocking = cast(dict[str, object], evidence["current_blocking_overlay"])
    manifest, errors = _manifest_index(evidence)
    dependencies = _rows(snapshot, "dependencies")
    rules = _rows(snapshot, "rules")
    groups = _rows(snapshot, "groups")

    live_ids = [int(row["id"]) for row in dependencies]
    expected_ids = cast(list[int], scope["dependency_ids"])
    if live_ids != expected_ids:
        errors.append("Step 14D exact dependency population drifted")
    if _sha256(live_ids) != scope["manifest_sha256"]:
        errors.append("Step 14D dependency manifest fingerprint drifted")
    if len(live_ids) != int(scope["count"]):
        errors.append("Step 14D dependency count drifted")
    if set(live_ids) != set(manifest):
        errors.append("classification families no longer cover the live scope exactly")

    errors.extend(_linked_rule_errors(dependencies, rules))
    if len(rules) != len(dependencies):
        errors.append("linked continuity-rule coverage is no longer 1:1")
    if any(bool(row["ordered_membership_seen"]) for row in groups):
        errors.append("a Step 14D dependency now touches non-null sequence_order")

    live_blocking = [
        int(row["id"])
        for row in dependencies
        if int(row["target_next_unread_issue_id"] or 0) == int(row["target_issue_id"])
        and row["source_status"] != "read"
    ]
    if live_blocking != cast(list[int], blocking["dependency_ids"]):
        errors.append("current-blocking overlay drifted from reviewed snapshot")

    counts = Counter(manifest[item][0] for item in live_ids if item in manifest)
    blocking_counts = Counter(manifest[item][0] for item in live_blocking if item in manifest)
    return {
        "step": "14D",
        "result": "PASS" if not errors else "DRIFT_DETECTED",
        "captured_at": _stable(snapshot["captured_at"]),
        "dependency_count": len(live_ids),
        "manifest_sha256": _sha256(live_ids),
        "distinct_note_count": len({row["note"] for row in dependencies}),
        "classification_counts": dict(sorted(counts.items())),
        "linked_rule_count": len(rules),
        "current_blocking_count": len(live_blocking),
        "current_blocking_dependency_ids": live_blocking,
        "current_blocking_by_classification": dict(sorted(blocking_counts.items())),
        "group_cluster_count": len({int(row["group_id"]) for row in groups}),
        "ordered_membership_dependency_count": len(
            {int(row["dependency_id"]) for row in groups if bool(row["ordered_membership_seen"])}
        ),
        "needs_review_dependency_ids": [
            item for item in live_ids if manifest.get(item, ("", ""))[0] == "needs_review"
        ],
        "errors": sorted(set(errors)),
        "production_mutated": False,
        "migration_authorized": False,
        "architecture_hold_2363_lifted": False,
        "step_14e_started": False,
    }


async def _run(output: Path | None) -> int:
    """Capture, reconcile, print, and optionally persist a fresh report."""
    async with AsyncSessionLocal() as db:
        try:
            snapshot = await _snapshot(db)
        finally:
            await db.rollback()
    report = _build(snapshot)
    rendered = json.dumps(report, indent=2, sort_keys=True, default=_stable)
    if output is not None:
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["result"] == "PASS" else 1


def main() -> int:
    """Run the Step 14D read-only production audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    return asyncio.run(_run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
