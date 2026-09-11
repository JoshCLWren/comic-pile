#!/usr/bin/env python3
"""Read-only Step 14C production audit for reader-order families and order overlaps."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AsyncSessionLocal = importlib.import_module("app.database").AsyncSessionLocal

USER_ID = 1
ORDER_NAMES = (
    "Doctor Strange Epic Collection Vol. 10: Infinity War",
    "Starman Compendiums 1-2",
    "JSA: Robinson / Goyer / Johns",
)
FAMILIES = {
    "Canonical Giffen/DeMatteis JLI reading spine": ("jli", 28),
    "Hickman Marvel Stage 1 order from cloned CBL reading list": (
        "hickman_marvel_stage_1",
        19,
    ),
    "Lee/Kirby Fantastic Four reading spine": ("lee_kirby_fantastic_four", 12),
    "Doctor Strange Epic Collection Vol. 10: Infinity War": (
        "doctor_strange_epic_vol_10",
        5,
    ),
    "Starlin Cosmic Saga CBL order": ("starlin_cosmic", 5),
}
STANDALONE_SIGNATURES = {
    18: (667, 2244),
    19: (668, 2246),
    20: (670, 2247),
    21: (671, 2248),
}
READER_ORDER_EXTRA_IDS = {1832, 1833, 1846, 1847}
EXPECTED_ORDER_COUNTS = {ORDER_NAMES[0]: 17, ORDER_NAMES[1]: 66, ORDER_NAMES[2]: 57}


def _sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def _stable(value: object) -> object:
    """Convert datetime values to stable JSON values."""
    return value.isoformat() if isinstance(value, datetime) else value


async def _select(
    db: AsyncSession,
    statement: str,
    params: dict[str, object],
) -> list[dict[str, object]]:
    """Execute one SELECT and return detached mapping rows."""
    if not statement.lstrip().upper().startswith("SELECT"):
        raise ValueError("Step 14C audit only permits SELECT statements")
    result = await db.execute(text(statement), params)
    return [dict(row) for row in result.mappings().all()]


def _params() -> dict[str, object]:
    """Return the fixed Step 14C selector parameters."""
    notes = list(FAMILIES)
    return {
        "user_id": USER_ID,
        "note1": notes[0],
        "note2": notes[1],
        "note3": notes[2],
        "note4": notes[3],
        "note5": notes[4],
        "order1": ORDER_NAMES[0],
        "order2": ORDER_NAMES[1],
        "order3": ORDER_NAMES[2],
    }


async def _snapshot(db: AsyncSession) -> dict[str, object]:
    """Capture all Step 14C evidence using SELECT statements only."""
    params = _params()
    dependencies = await _select(
        db,
        """
        SELECT d.id, d.created_at, d.source_issue_id, d.target_issue_id, d.note,
               st.id AS source_thread_id, st.title AS source_title,
               si.issue_number AS source_issue_number,
               tt.id AS target_thread_id, tt.title AS target_title,
               ti.issue_number AS target_issue_number
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE st.user_id = :user_id AND tt.user_id = :user_id
          AND (
            d.note IN (:note1, :note2, :note3, :note4, :note5)
            OR EXISTS (
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
          )
        ORDER BY d.id
        """,
        params,
    )
    orders = await _select(
        db,
        """
        SELECT ro.id AS reading_order_id, ro.name, roi.position,
               roi.thread_id, roi.issue_number, i.id AS issue_id
        FROM reading_orders ro
        JOIN reading_order_items roi ON roi.reading_order_id = ro.id
        JOIN issues i
          ON i.thread_id = roi.thread_id
         AND i.issue_number = roi.issue_number
        WHERE ro.user_id = :user_id
          AND ro.name IN (:order1, :order2, :order3)
        ORDER BY ro.id, roi.position
        """,
        params,
    )
    rules = await _select(
        db,
        """
        SELECT cr.legacy_dependency_id, cr.source_type, cr.source_id,
               cr.target_type, cr.target_id, cr.satisfaction_type
        FROM continuity_rules cr
        WHERE cr.user_id = :user_id
          AND cr.legacy_dependency_id IN (
            SELECT d.id
            FROM dependencies d
            JOIN issues si ON si.id = d.source_issue_id
            JOIN threads st ON st.id = si.thread_id
            JOIN issues ti ON ti.id = d.target_issue_id
            JOIN threads tt ON tt.id = ti.thread_id
            WHERE st.user_id = :user_id AND tt.user_id = :user_id
              AND (
                d.note IN (:note1, :note2, :note3, :note4, :note5)
                OR EXISTS (
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
              )
          )
        ORDER BY cr.legacy_dependency_id
        """,
        params,
    )
    provenance = await _select(
        db,
        """
        SELECT id, title, notes, created_at
        FROM threads
        WHERE user_id = :user_id
          AND id IN (88, 15524, 3145, 3166, 17063, 18545)
        ORDER BY id
        """,
        params,
    )
    groups = await _select(
        db,
        """
        SELECT dg.id, dg.name,
               COUNT(gm.id) AS member_count,
               COUNT(gm.id) FILTER (WHERE gm.sequence_order IS NOT NULL) AS ordered_count
        FROM dependency_groups dg
        LEFT JOIN dependency_group_memberships gm ON gm.group_id = dg.id
        WHERE dg.user_id = :user_id
          AND dg.id IN (2, 7, 117, 187)
        GROUP BY dg.id, dg.name
        ORDER BY dg.id
        """,
        params,
    )
    starlin_context = await _select(
        db,
        """
        SELECT d.id, d.note
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE st.user_id = :user_id
          AND tt.user_id = :user_id
          AND d.id BETWEEN 2771 AND 2782
        ORDER BY d.id
        """,
        params,
    )
    source = await _select(
        db,
        """
        SELECT id, name, content_hash, active
        FROM cbl_source_lists
        WHERE id = 22
        """,
        {},
    )
    captured = await _select(db, "SELECT CURRENT_TIMESTAMP AS captured_at", {})
    return {
        "dependencies": dependencies,
        "orders": orders,
        "rules": rules,
        "provenance": provenance,
        "groups": groups,
        "starlin_context": starlin_context,
        "source": source,
        "captured_at": captured[0]["captured_at"],
    }


def _list(snapshot: dict[str, object], key: str) -> list[dict[str, object]]:
    """Return one row collection from the snapshot."""
    rows = snapshot[key]
    if not isinstance(rows, list):
        raise TypeError(f"{key} is not a list")
    return rows


def _order_index(
    rows: list[dict[str, object]],
) -> tuple[dict[str, list[int]], dict[int, list[tuple[str, int]]], list[str]]:
    """Build exact ordered memberships and reverse issue membership."""
    by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
    reverse: dict[int, list[tuple[str, int]]] = defaultdict(list)
    errors: list[str] = []
    for row in rows:
        name = str(row["name"])
        position = int(row["position"])
        issue_id = int(row["issue_id"])
        by_name[name].append((position, issue_id))
        reverse[issue_id].append((name, position))
    exact: dict[str, list[int]] = {}
    for name in ORDER_NAMES:
        ordered = sorted(by_name.get(name, []))
        exact[name] = [issue_id for _, issue_id in ordered]
        if [position for position, _ in ordered] != list(
            range(1, EXPECTED_ORDER_COUNTS[name] + 1)
        ):
            errors.append(f"legacy Reading Order membership drifted: {name}")
    return exact, dict(reverse), errors


def _mirrored(
    row: dict[str, object],
    rules: dict[int, list[dict[str, object]]],
) -> bool:
    """Return whether exactly one item_read rule mirrors a dependency."""
    linked = rules.get(int(row["id"]), [])
    if len(linked) != 1:
        return False
    rule = linked[0]
    return (
        rule["source_type"] == "issue"
        and int(rule["source_id"]) == int(row["source_issue_id"])
        and rule["target_type"] == "issue"
        and int(rule["target_id"]) == int(row["target_issue_id"])
        and rule["satisfaction_type"] == "item_read"
    )


def _family_errors(
    key: str,
    rows: list[dict[str, object]],
    snapshot: dict[str, object],
    order_members: dict[str, list[int]],
) -> list[str]:
    """Validate the reviewed family-level semantic proof."""
    errors: list[str] = []
    expected = next(count for family_key, count in FAMILIES.values() if family_key == key)
    if len(rows) != expected:
        errors.append(f"expected {expected} rows, found {len(rows)}")

    provenance = {int(row["id"]): row for row in _list(snapshot, "provenance")}
    groups = {int(row["id"]): row for row in _list(snapshot, "groups")}
    if any(int(group["ordered_count"]) for group in groups.values()):
        errors.append("a provenance group unexpectedly has sequence_order")

    if key == "jli":
        if any(row["source_thread_id"] == row["target_thread_id"] for row in rows):
            errors.append("JLI family is no longer cross-thread stitching only")
        if "Giffen / J.M. DeMatteis" not in str(provenance.get(15524, {}).get("notes")):
            errors.append("JLI specials provenance drifted")
    elif key == "hickman_marvel_stage_1":
        if "cloned CBL reading order" not in str(provenance.get(17063, {}).get("notes")):
            errors.append("Hickman cloned-CBL provenance drifted")
        if len({str(_stable(row["created_at"])) for row in rows}) != 1:
            errors.append("Hickman generator batch is no longer uniform")
    elif key == "lee_kirby_fantastic_four":
        if "woven into this run" not in str(provenance.get(3166, {}).get("notes")):
            errors.append("Lee/Kirby monthly-spine provenance drifted")
        if "Sequenced into Fantastic Four" not in str(provenance.get(18545, {}).get("notes")):
            errors.append("Lee/Kirby annual provenance drifted")
        source = _list(snapshot, "source")
        if (
            len(source) != 1
            or source[0]["active"] is not True
            or source[0]["content_hash"]
            != "d3f597e1027d4924d0b0f698c54bc78fa155e0f0a4921f85d6ceadedb204a327"
        ):
            errors.append("Fantastic Four CBL corroboration drifted")
    elif key == "doctor_strange_epic_vol_10":
        positions = {
            issue_id: position
            for position, issue_id in enumerate(order_members[ORDER_NAMES[0]], start=1)
        }
        pairs = {
            (positions.get(int(row["source_issue_id"])), positions.get(int(row["target_issue_id"])))
            for row in rows
        }
        if pairs != {(8, 9), (9, 10), (10, 11), (11, 12), (16, 17)}:
            errors.append("Doctor Strange stitch positions drifted")
    elif key == "starlin_cosmic":
        pairs = [(int(row["source_issue_id"]), int(row["target_issue_id"])) for row in rows]
        if pairs != [
            (1549, 1550),
            (1550, 1551),
            (1551, 115319),
            (115319, 115320),
            (115320, 115321),
        ]:
            errors.append("Starlin scoped CBL chain drifted")
        continuation = [
            row["note"]
            for row in _list(snapshot, "starlin_context")
            if 2777 <= int(row["id"]) <= 2782
        ]
        if continuation != [
            f"Starlin Cosmic Saga CBL positions {position} -> {position + 1}"
            for position in range(26, 32)
        ]:
            errors.append("Starlin CBL continuation provenance drifted")
    return errors


def _build(snapshot: dict[str, object]) -> dict[str, object]:
    """Classify the fresh snapshot, failing closed on semantic drift."""
    dependencies = _list(snapshot, "dependencies")
    order_members, reverse, errors = _order_index(_list(snapshot, "orders"))

    rules: dict[int, list[dict[str, object]]] = defaultdict(list)
    for rule in _list(snapshot, "rules"):
        rules[int(rule["legacy_dependency_id"])].append(rule)

    family_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in dependencies:
        note = row["note"]
        if isinstance(note, str) and note in FAMILIES:
            family_rows[FAMILIES[note][0]].append(row)

    manifest: list[dict[str, object]] = []
    family_errors: dict[str, list[str]] = {}
    named_ids: set[int] = set()
    for key, _ in FAMILIES.values():
        rows = sorted(family_rows.get(key, []), key=lambda row: int(row["id"]))
        proof_errors = _family_errors(key, rows, snapshot, order_members)
        if any(not _mirrored(row, rules) for row in rows):
            proof_errors.append("one or more continuity rules no longer mirror the family")
        family_errors[key] = sorted(set(proof_errors))
        for row in rows:
            dependency_id = int(row["id"])
            named_ids.add(dependency_id)
            manifest.append(
                {
                    "dependency_id": dependency_id,
                    "classification": "needs_review" if proof_errors else "reading_plan_order",
                    "family_key": key,
                }
            )

    for row in dependencies:
        dependency_id = int(row["id"])
        if dependency_id in named_ids:
            continue
        row_errors: list[str] = []
        if not _mirrored(row, rules):
            row_errors.append("continuity rule mirror drifted")
        if dependency_id in STANDALONE_SIGNATURES:
            if (
                row["note"] is not None
                or (int(row["source_issue_id"]), int(row["target_issue_id"]))
                != STANDALONE_SIGNATURES[dependency_id]
                or not str(_stable(row["created_at"])).startswith("2026-03-08T")
            ):
                row_errors.append("reviewed Infinity War boundary signature drifted")
            classification = "needs_review" if row_errors else "standalone_prerequisite"
            family_key = "doctor_strange_infinity_war_boundary"
        elif dependency_id in READER_ORDER_EXTRA_IDS:
            source = reverse.get(int(row["source_issue_id"]), [])
            target = reverse.get(int(row["target_issue_id"]), [])
            expected_membership = {
                1832: ((ORDER_NAMES[1], 3), (ORDER_NAMES[1], 4)),
                1833: ((ORDER_NAMES[1], 24), (ORDER_NAMES[2], 1)),
                1846: ((ORDER_NAMES[1], 6), (ORDER_NAMES[1], 7)),
                1847: ((ORDER_NAMES[1], 8), (ORDER_NAMES[1], 9)),
            }[dependency_id]
            if expected_membership[0] not in source or expected_membership[1] not in target:
                row_errors.append("reviewed Starman/JSA boundary membership drifted")
            classification = "needs_review" if row_errors else "reading_plan_order"
            family_key = "starman_jsa_bridge" if dependency_id == 1833 else "starman_legacy_order"
        else:
            classification = "needs_review"
            family_key = "unrecognized_legacy_order_overlap"
            row_errors.append("unrecognized legacy Reading Order overlap")
        manifest.append(
            {
                "dependency_id": dependency_id,
                "classification": classification,
                "family_key": family_key,
            }
        )
        if row_errors:
            errors.extend(f"dependency {dependency_id}: {reason}" for reason in row_errors)

    manifest.sort(key=lambda row: int(row["dependency_id"]))
    ids = [int(row["dependency_id"]) for row in manifest]
    reading_plan_ids = [
        int(row["dependency_id"]) for row in manifest if row["classification"] == "reading_plan_order"
    ]
    standalone_ids = [
        int(row["dependency_id"])
        for row in manifest
        if row["classification"] == "standalone_prerequisite"
    ]
    review_ids = [
        int(row["dependency_id"]) for row in manifest if row["classification"] == "needs_review"
    ]

    overlap_ids: set[int] = set()
    order_report: dict[str, object] = {}
    for name, member_ids in order_members.items():
        touching = sorted(
            int(row["id"])
            for row in dependencies
            if int(row["source_issue_id"]) in member_ids or int(row["target_issue_id"]) in member_ids
        )
        overlap_ids.update(touching)
        order_report[name] = {"ordered_issue_ids": member_ids, "overlap_dependency_ids": touching}

    if len(ids) != len(set(ids)):
        errors.append("classification manifest contains duplicate dependency IDs")
    if len(named_ids) != 69:
        errors.append(f"named-family union expected 69, found {len(named_ids)}")
    if len(overlap_ids) != 13:
        errors.append(f"legacy-order overlap union expected 13, found {len(overlap_ids)}")
    if len(ids) != 77:
        errors.append(f"unique Step 14C population expected 77, found {len(ids)}")

    return {
        "step": "14C",
        "result": "PASS" if not errors and not review_ids else "REVIEW_REQUIRED",
        "captured_at": _stable(snapshot["captured_at"]),
        "unique_dependency_count": len(ids),
        "dependency_ids": ids,
        "id_manifest_sha256": _sha256(ids),
        "reading_plan_order_count": len(reading_plan_ids),
        "standalone_prerequisite_count": len(standalone_ids),
        "needs_review_count": len(review_ids),
        "standalone_prerequisite_dependency_ids": standalone_ids,
        "needs_review_dependency_ids": review_ids,
        "family_errors": family_errors,
        "legacy_reading_orders": order_report,
        "manifest": manifest,
        "errors": sorted(set(errors)),
        "production_mutated": False,
        "migration_authorized": False,
        "step_14d_started": False,
    }


async def _run(output: Path | None) -> int:
    """Capture, classify, print, and optionally persist the fresh report."""
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
    """Run the Step 14C audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    return asyncio.run(_run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
