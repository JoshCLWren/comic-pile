#!/usr/bin/env python3
"""Read-only Step 14E audit and final Step 14 production reconciliation."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AsyncSessionLocal = importlib.import_module("app.database").AsyncSessionLocal

USER_ID = 1
EVIDENCE = ROOT / "docs/recovery/step14e-unnoted-final-reconciliation-evidence.json"
FINAL_INDEX = ROOT / "docs/recovery/step14-final-classification-index.json"
ALLOWED = {"reading_plan_order", "standalone_prerequisite", "needs_review"}
STEP14A = re.compile(r"^cbl-order:source:([^:]+):[0-9]+->[0-9]+$")
STEP14B = re.compile(r"^cbl-order:group-16:[^:]+:[0-9]+->[0-9]+$")
STEP14B_TEMP = "Temporary authoritative Ultimate Universe CBL order incident repair"
LEGACY_ORDER_NAMES = (
    "Doctor Strange Epic Collection Vol. 10: Infinity War",
    "Starman Compendiums 1-2",
    "JSA: Robinson / Goyer / Johns",
)


def _sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def _md5(ids: list[int]) -> str:
    """Match the compact PostgreSQL manifest fingerprint used by Step 14."""
    return hashlib.md5(  # noqa: S324 - non-security manifest fingerprint
        ",".join(str(value) for value in ids).encode(),
        usedforsecurity=False,
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    """Load one persisted Step 14 artifact."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


async def _select(
    db: AsyncSession,
    statement: str,
    params: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Execute exactly one SELECT and detach its mapping rows."""
    if not statement.lstrip().upper().startswith("SELECT"):
        raise ValueError("Step 14E audit permits SELECT statements only")
    result = await db.execute(text(statement), params or {})
    return [dict(row) for row in result.mappings().all()]


def _explicit(index: dict[str, Any]) -> dict[int, dict[str, str]]:
    """Expand compact Step 14C-14E family buckets into an exact ID lookup."""
    lookup: dict[int, dict[str, str]] = {}
    slices = cast(dict[str, dict[str, Any]], index["lookup"]["explicit_slices"])
    for slice_name, slice_data in slices.items():
        evidence_artifact = str(slice_data["evidence_artifact"])
        for family in cast(list[dict[str, Any]], slice_data["families"]):
            metadata = {
                "slice": slice_name,
                "classification": str(family["classification"]),
                "family_key": str(family["family_key"]),
                "evidence_artifact": evidence_artifact,
            }
            for dependency_id in cast(list[int], family["ids"]):
                if dependency_id in lookup:
                    raise AssertionError(
                        f"duplicate final-index dependency ID {dependency_id}"
                    )
                lookup[dependency_id] = metadata
    return lookup


def _classify(
    row: dict[str, object],
    index: dict[str, Any],
    explicit: dict[int, dict[str, str]],
) -> dict[str, str]:
    """Classify one dependency from frozen Step 14 selectors."""
    dependency_id = int(row["id"])
    note = row["note"]
    lookup = cast(dict[str, Any], index["lookup"])
    if isinstance(note, str):
        match = STEP14A.fullmatch(note)
        if match is not None:
            source_hash = match.group(1)
            selector = cast(dict[str, Any], lookup["14A"])
            sources = cast(dict[str, list[object]], selector["source_hash_map"])
            source = sources.get(source_hash)
            if source is None:
                raise AssertionError(
                    f"Step 14A dependency {dependency_id} has unknown source hash "
                    f"{source_hash}"
                )
            return {
                "slice": "14A",
                "classification": "reading_plan_order",
                "family_key": f"cbl_source_list_{int(source[0])}",
            }
        if STEP14B.fullmatch(note) is not None:
            return {
                "slice": "14B",
                "classification": "reading_plan_order",
                "family_key": "unnamed_universe_generated_compatibility",
            }
        if note == STEP14B_TEMP:
            return {
                "slice": "14B",
                "classification": "reading_plan_order",
                "family_key": "ultimate_universe_temporary_repair",
            }

    classified = explicit.get(dependency_id)
    if classified is None:
        raise AssertionError(f"dependency {dependency_id} has no Step 14 classification")
    return classified


async def _snapshot(db: AsyncSession) -> dict[str, object]:
    """Capture the minimal read-only facts required for final reconciliation."""
    dependencies = await _select(
        db,
        """
        SELECT d.id, d.note, d.source_issue_id, d.target_issue_id,
               si.status AS source_status,
               tt.next_unread_issue_id AS target_next_unread_issue_id
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE st.user_id = :user_id AND tt.user_id = :user_id
        ORDER BY d.id
        """,
        {"user_id": USER_ID},
    )
    rules = await _select(
        db,
        """
        SELECT cr.id, cr.legacy_dependency_id, cr.source_type, cr.source_id,
               cr.target_type, cr.target_id, cr.satisfaction_type
        FROM continuity_rules cr
        WHERE cr.user_id = :user_id
          AND cr.legacy_dependency_id IS NOT NULL
        ORDER BY cr.legacy_dependency_id, cr.id
        """,
        {"user_id": USER_ID},
    )
    group_hits = await _select(
        db,
        """
        SELECT DISTINCT d.id AS dependency_id, dg.id AS group_id,
               dg.name AS group_name, gm.sequence_order
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        JOIN dependency_group_memberships gm
          ON gm.issue_id IN (d.source_issue_id, d.target_issue_id)
          OR (
            gm.issue_id IS NULL
            AND gm.thread_id IN (si.thread_id, ti.thread_id)
          )
        JOIN dependency_groups dg
          ON dg.id = gm.group_id
         AND dg.user_id = :user_id
        WHERE st.user_id = :user_id
          AND tt.user_id = :user_id
          AND d.note IS NULL
        ORDER BY d.id, dg.id
        """,
        {"user_id": USER_ID},
    )
    legacy_overlap = await _select(
        db,
        """
        SELECT DISTINCT d.id
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE st.user_id = :user_id
          AND tt.user_id = :user_id
          AND EXISTS (
            SELECT 1
            FROM reading_orders ro
            JOIN reading_order_items roi ON roi.reading_order_id = ro.id
            JOIN issues oi
              ON oi.thread_id = roi.thread_id
             AND oi.issue_number = roi.issue_number
            WHERE ro.user_id = :user_id
              AND ro.name IN (:order1, :order2, :order3)
              AND oi.id IN (d.source_issue_id, d.target_issue_id)
          )
        ORDER BY d.id
        """,
        {
            "user_id": USER_ID,
            "order1": LEGACY_ORDER_NAMES[0],
            "order2": LEGACY_ORDER_NAMES[1],
            "order3": LEGACY_ORDER_NAMES[2],
        },
    )
    bprd_overlap = await _select(
        db,
        """
        SELECT DISTINCT d.id
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE st.user_id = :user_id
          AND tt.user_id = :user_id
          AND (
            d.source_issue_id IN (
              SELECT DISTINCT (node->>'ref_id')::int
              FROM continuity_plans cp,
                   LATERAL json_array_elements(cp.nodes_json) AS node
              WHERE cp.user_id = :user_id
                AND cp.name = 'B.P.R.D.'
                AND node->>'node_type' = 'issue'
            )
            OR d.target_issue_id IN (
              SELECT DISTINCT (node->>'ref_id')::int
              FROM continuity_plans cp,
                   LATERAL json_array_elements(cp.nodes_json) AS node
              WHERE cp.user_id = :user_id
                AND cp.name = 'B.P.R.D.'
                AND node->>'node_type' = 'issue'
            )
          )
        ORDER BY d.id
        """,
        {"user_id": USER_ID},
    )
    return {
        "dependencies": dependencies,
        "rules": rules,
        "group_hits": group_hits,
        "legacy_overlap": legacy_overlap,
        "bprd_overlap": bprd_overlap,
    }


def _reconcile(snapshot: dict[str, object]) -> dict[str, object]:
    """Reconcile fresh production facts against the frozen Step 14 package."""
    evidence = _load(EVIDENCE)
    index = _load(FINAL_INDEX)
    explicit = _explicit(index)
    dependencies = cast(list[dict[str, object]], snapshot["dependencies"])

    by_slice: dict[str, list[int]] = defaultdict(list)
    by_classification: Counter[str] = Counter()
    active: Counter[str] = Counter()
    for row in dependencies:
        dependency_id = int(row["id"])
        result = _classify(row, index, explicit)
        classification = result["classification"]
        if classification not in ALLOWED:
            raise AssertionError(f"dependency {dependency_id}: invalid classification")
        by_slice[result["slice"]].append(dependency_id)
        by_classification[classification] += 1
        if (
            row["target_next_unread_issue_id"] == row["target_issue_id"]
            and row["source_status"] != "read"
        ):
            active[classification] += 1

    final = cast(dict[str, Any], evidence["final_reconciliation"])
    if len(dependencies) != final["production_total"]:
        raise AssertionError("production dependency total drifted")

    expected_slice_counts = cast(dict[str, int], final["slice_counts"])
    expected_slice_md5 = cast(dict[str, str], final["slice_id_md5"])
    for step, expected_count in expected_slice_counts.items():
        ids = sorted(by_slice.get(step, []))
        if len(ids) != expected_count:
            raise AssertionError(f"{step} count drifted")
        if _md5(ids) != expected_slice_md5[step]:
            raise AssertionError(f"{step} dependency-ID manifest drifted")

    expected_global = cast(dict[str, int], final["global_classification_totals"])
    if dict(by_classification) != expected_global:
        raise AssertionError("global Step 14 classification totals drifted")

    scope = cast(dict[str, Any], evidence["scope"])
    step14e_ids = sorted(by_slice["14E"])
    if step14e_ids != cast(list[int], scope["dependency_ids"]):
        raise AssertionError("Step 14E exact dependency population drifted")
    if _sha256(step14e_ids) != scope["manifest_sha256"]:
        raise AssertionError("Step 14E manifest fingerprint drifted")
    step14e_set = set(step14e_ids)

    rules_by_dependency: dict[int, list[dict[str, object]]] = defaultdict(list)
    for rule in cast(list[dict[str, object]], snapshot["rules"]):
        rules_by_dependency[int(rule["legacy_dependency_id"])].append(rule)
    mirrored = 0
    dependency_by_id = {int(row["id"]): row for row in dependencies}
    for dependency_id in step14e_ids:
        row = dependency_by_id[dependency_id]
        linked = rules_by_dependency.get(dependency_id, [])
        if len(linked) != 1:
            raise AssertionError(
                f"Step 14E dependency {dependency_id} no longer has one linked rule"
            )
        rule = linked[0]
        if (
            rule["source_type"] == "issue"
            and rule["source_id"] == row["source_issue_id"]
            and rule["target_type"] == "issue"
            and rule["target_id"] == row["target_issue_id"]
            and rule["satisfaction_type"] == "item_read"
        ):
            mirrored += 1
    if mirrored != len(step14e_ids):
        raise AssertionError("Step 14E linked-rule mirror coverage drifted")

    group_hits = [
        row
        for row in cast(list[dict[str, object]], snapshot["group_hits"])
        if int(row["dependency_id"]) in step14e_set
    ]
    if {int(row["dependency_id"]) for row in group_hits} != step14e_set:
        raise AssertionError("Step 14E dependency-group coverage drifted")
    if any(row["sequence_order"] is not None for row in group_hits):
        raise AssertionError("Step 14E unexpectedly gained sequence_order authority")

    legacy_ids = [
        int(row["id"])
        for row in cast(list[dict[str, object]], snapshot["legacy_overlap"])
    ]
    expected_legacy = cast(
        list[int],
        final["legacy_reading_orders"]["overlap_dependency_ids"],
    )
    if legacy_ids != expected_legacy:
        raise AssertionError("legacy Reading Order dependency overlap drifted")

    bprd_ids = [
        int(row["id"])
        for row in cast(list[dict[str, object]], snapshot["bprd_overlap"])
    ]
    if bprd_ids:
        raise AssertionError(f"B.P.R.D. regained legacy dependencies: {bprd_ids}")

    expected_active = cast(
        dict[str, int],
        final["global_current_blocking_overlay"],
    )
    actual_active = {key: active.get(key, 0) for key in ALLOWED}
    actual_active["total"] = sum(actual_active.values())
    for key in (*sorted(ALLOWED), "total"):
        if actual_active[key] != expected_active[key]:
            raise AssertionError(f"global blocking overlay drifted for {key}")

    return {
        "result": "PASS",
        "production_total": len(dependencies),
        "slice_counts": {step: len(ids) for step, ids in sorted(by_slice.items())},
        "classification_totals": dict(by_classification),
        "step14e_count": len(step14e_ids),
        "step14e_manifest_sha256": _sha256(step14e_ids),
        "global_active_blocking": actual_active,
        "legacy_reading_order_overlap_ids": legacy_ids,
        "bprd_dependency_overlap_ids": bprd_ids,
        "production_mutated": False,
    }


async def _run() -> dict[str, object]:
    """Open one read-only audit session and always roll it back."""
    async with AsyncSessionLocal() as db:
        try:
            snapshot = await _snapshot(db)
            return _reconcile(snapshot)
        finally:
            await db.rollback()


def main() -> int:
    """Run the final Step 14E audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run())
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
