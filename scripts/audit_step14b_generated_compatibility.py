#!/usr/bin/env python3
"""Read-only Step 14B audit for two generated compatibility families.

The audit classifies only The Unnamed Universe ``cbl-order:group-16:*`` rows
and the temporary Ultimate Universe incident-repair rows. Every database
statement in this file is a SELECT, and the session is always rolled back.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AsyncSessionLocal = importlib.import_module("app.database").AsyncSessionLocal

USER_ID = 1

UNNAMED_GROUP_ID = 16
UNNAMED_GROUP_NAME = "The Unnamed Universe"
UNNAMED_LIST_ID = 3
UNNAMED_HASH = "bb54dfc094a2a7c469b6baa77f6751a8d30ea034ede24d686ba1ab4a968ae0ca"
UNNAMED_EXPECTED_COUNT = 1228
UNNAMED_NOTE_PREFIX = "cbl-order:group-16:"
UNNAMED_NOTE_RE = re.compile(r"^cbl-order:group-16:([^:]+):(\d+)->(\d+)$")

ULTIMATE_GROUP_ID = 15
ULTIMATE_GROUP_NAME = "Ultimate Universe Reading Order"
ULTIMATE_LIST_ID = 12
ULTIMATE_HASH = "d8944942bb6115ea9607ac6be0ac53e59368b90a929d44412900b3b9cae8b66a"
ULTIMATE_EXPECTED_COUNT = 73
ULTIMATE_EXPECTED_ADJACENCY_COUNT = 55
ULTIMATE_EXPECTED_BRIDGE_COUNT = 18
ULTIMATE_REPAIR_NOTE = "Temporary authoritative Ultimate Universe CBL order incident repair"


def _manifest_sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def _json_value(value: object) -> object:
    """Convert database values to stable JSON values."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def _select_rows(
    db: AsyncSession,
    statement: str,
    params: dict[str, object],
) -> list[dict[str, Any]]:
    """Execute one SELECT and return detached mapping rows."""
    result = await db.execute(text(statement), params)
    return [dict(row) for row in result.mappings().all()]


async def _load_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Load the complete Step 14B evidence using SELECT statements only."""
    dependency_rows = await _select_rows(
        db,
        """
        SELECT d.id, d.created_at, d.source_issue_id, d.target_issue_id, d.note,
               st.user_id AS source_user_id, tt.user_id AS target_user_id,
               st.id AS source_thread_id, st.title AS source_title,
               si.issue_number AS source_issue_number,
               tt.id AS target_thread_id, tt.title AS target_title,
               ti.issue_number AS target_issue_number
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE d.note LIKE :unnamed_prefix
           OR d.note = :ultimate_note
        ORDER BY d.id
        """,
        {
            "unnamed_prefix": f"{UNNAMED_NOTE_PREFIX}%",
            "ultimate_note": ULTIMATE_REPAIR_NOTE,
        },
    )
    group_rows = await _select_rows(
        db,
        """
        SELECT id, user_id, name, created_at
        FROM dependency_groups
        WHERE id IN (:unnamed_group_id, :ultimate_group_id)
        ORDER BY id
        """,
        {
            "unnamed_group_id": UNNAMED_GROUP_ID,
            "ultimate_group_id": ULTIMATE_GROUP_ID,
        },
    )
    membership_rows = await _select_rows(
        db,
        """
        SELECT id, group_id, thread_id, issue_id, sequence_order
        FROM dependency_group_memberships
        WHERE group_id IN (:unnamed_group_id, :ultimate_group_id)
        ORDER BY group_id, id
        """,
        {
            "unnamed_group_id": UNNAMED_GROUP_ID,
            "ultimate_group_id": ULTIMATE_GROUP_ID,
        },
    )
    list_rows = await _select_rows(
        db,
        """
        SELECT l.id, l.source_id, l.source_path, l.name, l.declared_issue_count,
               l.content_hash, l.revision_sha, l.active, l.created_at, l.updated_at,
               s.repository, s.revision_sha AS source_revision_sha
        FROM cbl_source_lists l
        JOIN cbl_sources s ON s.id = l.source_id
        WHERE l.id IN (:unnamed_list_id, :ultimate_list_id)
        ORDER BY l.id
        """,
        {
            "unnamed_list_id": UNNAMED_LIST_ID,
            "ultimate_list_id": ULTIMATE_LIST_ID,
        },
    )
    entry_rows = await _select_rows(
        db,
        """
        SELECT id, list_id, position, series_name, issue_number, volume_year,
               publication_year, external_issue_identity_id
        FROM cbl_source_entries
        WHERE list_id IN (:unnamed_list_id, :ultimate_list_id)
        ORDER BY list_id, position
        """,
        {
            "unnamed_list_id": UNNAMED_LIST_ID,
            "ultimate_list_id": ULTIMATE_LIST_ID,
        },
    )
    mapping_rows = await _select_rows(
        db,
        """
        SELECT e.list_id, e.position, m.issue_id, gm.group_id, m.id AS mapping_id,
               m.external_identity_id, m.status, m.evidence_source, m.confidence
        FROM cbl_source_entries e
        JOIN issue_external_identity_mappings m
          ON m.external_identity_id = e.external_issue_identity_id
         AND m.status = 'confirmed'
        JOIN dependency_group_memberships gm ON gm.issue_id = m.issue_id
        WHERE (e.list_id = :unnamed_list_id AND gm.group_id = :unnamed_group_id)
           OR (e.list_id = :ultimate_list_id AND gm.group_id = :ultimate_group_id)
        ORDER BY e.list_id, e.position, m.issue_id
        """,
        {
            "unnamed_list_id": UNNAMED_LIST_ID,
            "unnamed_group_id": UNNAMED_GROUP_ID,
            "ultimate_list_id": ULTIMATE_LIST_ID,
            "ultimate_group_id": ULTIMATE_GROUP_ID,
        },
    )
    rule_rows = await _select_rows(
        db,
        """
        SELECT r.id, r.user_id, r.legacy_dependency_id, r.source_type, r.source_id,
               r.target_type, r.target_id, r.satisfaction_type,
               r.checkpoint_issue_id, r.convergence_targets, r.note,
               r.created_at, r.updated_at
        FROM continuity_rules r
        JOIN dependencies d ON d.id = r.legacy_dependency_id
        WHERE d.note LIKE :unnamed_prefix
           OR d.note = :ultimate_note
        ORDER BY r.legacy_dependency_id, r.id
        """,
        {
            "unnamed_prefix": f"{UNNAMED_NOTE_PREFIX}%",
            "ultimate_note": ULTIMATE_REPAIR_NOTE,
        },
    )
    capture_rows = await _select_rows(
        db,
        "SELECT CURRENT_TIMESTAMP AS captured_at",
        {},
    )
    return {
        "dependencies": dependency_rows,
        "groups": group_rows,
        "memberships": membership_rows,
        "lists": list_rows,
        "entries": entry_rows,
        "mappings": mapping_rows,
        "rules": rule_rows,
        "captured_at": capture_rows[0]["captured_at"],
    }


def _group_evidence(
    snapshot: dict[str, Any],
    *,
    group_id: int,
    expected_name: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    """Return one dependency group's evidence and fail-closed errors."""
    groups = [row for row in snapshot["groups"] if int(row["id"]) == group_id]
    memberships = [
        row for row in snapshot["memberships"] if int(row["group_id"]) == group_id
    ]
    errors: list[str] = []
    if len(groups) != 1:
        errors.append(f"expected exactly one dependency group {group_id}, found {len(groups)}")
        group = None
    else:
        group = groups[0]
        if int(group["user_id"]) != USER_ID or group["name"] != expected_name:
            errors.append(
                f"dependency group {group_id} identity drifted: "
                f"user={group['user_id']!r}, name={group['name']!r}"
            )
    ordered_ids = [int(row["id"]) for row in memberships if row["sequence_order"] is not None]
    if ordered_ids:
        errors.append(f"dependency group {group_id} has non-null sequence_order rows")
    thread_member_ids = [int(row["id"]) for row in memberships if row["thread_id"] is not None]
    if thread_member_ids:
        errors.append(f"dependency group {group_id} has unexpected thread memberships")
    return group, memberships, errors


def _list_evidence(
    snapshot: dict[str, Any],
    *,
    list_id: int,
    expected_hash: str,
) -> tuple[dict[str, Any] | None, dict[int, dict[str, Any]], dict[int, list[int]], list[str]]:
    """Return one active source list, its positions, mappings, and errors."""
    lists = [row for row in snapshot["lists"] if int(row["id"]) == list_id]
    errors: list[str] = []
    if len(lists) != 1:
        errors.append(f"expected exactly one CBL source list {list_id}, found {len(lists)}")
        source_list = None
    else:
        source_list = lists[0]
        if source_list["content_hash"] != expected_hash or source_list["active"] is not True:
            errors.append(
                f"CBL source list {list_id} hash/active state drifted: "
                f"hash={source_list['content_hash']!r}, active={source_list['active']!r}"
            )
    entries = {
        int(row["position"]): row
        for row in snapshot["entries"]
        if int(row["list_id"]) == list_id
    }
    mapped_issue_ids: dict[int, list[int]] = defaultdict(list)
    for row in snapshot["mappings"]:
        if int(row["list_id"]) == list_id:
            mapped_issue_ids[int(row["position"])].append(int(row["issue_id"]))
    for values in mapped_issue_ids.values():
        values.sort()
    return source_list, entries, dict(mapped_issue_ids), errors


def _rule_errors(
    row: dict[str, Any],
    rules: list[dict[str, Any]],
    *,
    expected_note: str | None,
) -> list[str]:
    """Validate one dependency's linked compatibility rule."""
    errors: list[str] = []
    if len(rules) != 1:
        return [f"expected exactly one linked continuity rule, found {len(rules)}"]
    rule = rules[0]
    if not (
        int(rule["user_id"]) == USER_ID
        and rule["source_type"] == "issue"
        and int(rule["source_id"]) == int(row["source_issue_id"])
        and rule["target_type"] == "issue"
        and int(rule["target_id"]) == int(row["target_issue_id"])
        and rule["satisfaction_type"] == "item_read"
        and rule["checkpoint_issue_id"] is None
        and not rule["convergence_targets"]
    ):
        errors.append("linked continuity rule does not mirror the dependency edge")
    if expected_note is not None and rule["note"] != expected_note:
        errors.append("linked continuity rule does not retain incident-repair provenance")
    return errors


def _family_result(
    ids: list[int],
    row_errors: dict[int, list[str]],
    global_errors: list[str],
) -> dict[str, Any]:
    """Classify a family, assigning failures to needs_review."""
    if global_errors:
        for dependency_id in ids:
            row_errors[dependency_id].extend(global_errors)
    needs_review_ids = sorted(dependency_id for dependency_id in ids if row_errors[dependency_id])
    reading_plan_order_ids = sorted(set(ids) - set(needs_review_ids))
    return {
        "reading_plan_order_count": len(reading_plan_order_ids),
        "needs_review_count": len(needs_review_ids),
        "standalone_prerequisite_count": 0,
        "needs_review_dependency_ids": needs_review_ids,
        "exceptions": [
            {
                "dependency_id": dependency_id,
                "reasons": sorted(set(row_errors[dependency_id])),
            }
            for dependency_id in needs_review_ids
        ],
    }


def _build_unnamed_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify The Unnamed Universe generated group-order family."""
    rows = [
        row for row in snapshot["dependencies"] if row["note"].startswith(UNNAMED_NOTE_PREFIX)
    ]
    rows.sort(key=lambda row: int(row["id"]))
    ids = [int(row["id"]) for row in rows]
    row_errors: dict[int, list[str]] = defaultdict(list)
    global_errors: list[str] = []

    group, memberships, group_errors = _group_evidence(
        snapshot,
        group_id=UNNAMED_GROUP_ID,
        expected_name=UNNAMED_GROUP_NAME,
    )
    source_list, entries, mapped_issue_ids, list_errors = _list_evidence(
        snapshot,
        list_id=UNNAMED_LIST_ID,
        expected_hash=UNNAMED_HASH,
    )
    global_errors.extend(group_errors)
    global_errors.extend(list_errors)
    if len(ids) != UNNAMED_EXPECTED_COUNT:
        global_errors.append(
            f"population drift: expected {UNNAMED_EXPECTED_COUNT}, found {len(ids)}"
        )

    member_issue_ids = {
        int(row["issue_id"]) for row in memberships if row["issue_id"] is not None
    }
    rules_by_dependency: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rule in snapshot["rules"]:
        rules_by_dependency[int(rule["legacy_dependency_id"])].append(rule)

    endpoint_by_position: dict[int, set[int]] = defaultdict(set)
    parsed_rows: list[tuple[dict[str, Any], int, int]] = []
    note_hashes: set[str] = set()
    for row in rows:
        dependency_id = int(row["id"])
        match = UNNAMED_NOTE_RE.fullmatch(row["note"])
        if match is None:
            row_errors[dependency_id].append("note does not exactly parse")
            continue
        note_hash, source_text, target_text = match.groups()
        source_position, target_position = int(source_text), int(target_text)
        note_hashes.add(note_hash)
        parsed_rows.append((row, source_position, target_position))
        source_issue_id = int(row["source_issue_id"])
        target_issue_id = int(row["target_issue_id"])
        endpoint_by_position[source_position].add(source_issue_id)
        endpoint_by_position[target_position].add(target_issue_id)

        if int(row["source_user_id"]) != USER_ID or int(row["target_user_id"]) != USER_ID:
            row_errors[dependency_id].append("dependency endpoints are not both owned by user 1")
        if source_position >= target_position:
            row_errors[dependency_id].append("encoded edge does not run forward")
        if source_issue_id not in member_issue_ids or target_issue_id not in member_issue_ids:
            row_errors[dependency_id].append("dependency endpoint is outside dependency group 16")
        if source_position not in entries or target_position not in entries:
            row_errors[dependency_id].append("referenced CBL position does not exist")
        if mapped_issue_ids.get(source_position) != [source_issue_id]:
            row_errors[dependency_id].append("source position does not uniquely map to local issue")
        if mapped_issue_ids.get(target_position) != [target_issue_id]:
            row_errors[dependency_id].append("target position does not uniquely map to local issue")
        row_errors[dependency_id].extend(
            _rule_errors(row, rules_by_dependency[dependency_id], expected_note=None)
        )

    if note_hashes != {UNNAMED_HASH}:
        global_errors.append(f"note hash drift: found {sorted(note_hashes)!r}")
    if source_list is not None and source_list["name"] != UNNAMED_GROUP_NAME:
        global_errors.append(f"CBL source list {UNNAMED_LIST_ID} name drifted")

    positions: list[dict[str, Any]] = []
    for position in sorted(endpoint_by_position):
        endpoint_ids = sorted(endpoint_by_position[position])
        entry = entries.get(position)
        positions.append(
            {
                "position": position,
                "local_issue_ids": endpoint_ids,
                "confirmed_group_mapping_issue_ids": mapped_issue_ids.get(position, []),
                "cbl_series_name": entry["series_name"] if entry else None,
                "cbl_issue_number": entry["issue_number"] if entry else None,
                "cbl_volume_year": entry["volume_year"] if entry else None,
            }
        )
        if len(endpoint_ids) != 1:
            global_errors.append(
                f"position {position} maps to multiple dependency endpoints: {endpoint_ids}"
            )

    result = _family_result(ids, row_errors, global_errors)
    return {
        "family": "the_unnamed_universe",
        "selector": r"^cbl-order:group-16:[^:]+:[0-9]+->[0-9]+$",
        "expected_dependency_count": UNNAMED_EXPECTED_COUNT,
        "dependency_count": len(ids),
        "dependency_ids": ids,
        "id_manifest_sha256": _manifest_sha256(ids),
        "note_hashes": sorted(note_hashes),
        "dependency_group": {key: _json_value(value) for key, value in (group or {}).items()},
        "dependency_group_membership_count": len(memberships),
        "nonnull_sequence_order_membership_ids": [
            int(row["id"]) for row in memberships if row["sequence_order"] is not None
        ],
        "source_list": {
            key: _json_value(value) for key, value in (source_list or {}).items()
        },
        "source_position_count": len(entries),
        "referenced_position_count": len(endpoint_by_position),
        "position_to_local_issue_evidence": positions,
        "forward_edge_count": sum(
            source_position < target_position for _, source_position, target_position in parsed_rows
        ),
        "linked_continuity_rule_count": sum(
            len(rules_by_dependency[dependency_id]) for dependency_id in ids
        ),
        "standalone_prerequisite_evidence": (
            "No row has independent prerequisite provenance: every exact note encodes the "
            "active CBL hash plus forward source positions, every endpoint is a confirmed "
            "member of The Unnamed Universe group, and every linked rule mirrors that "
            "generated compatibility edge."
        ),
        "classification": result,
        "global_exceptions": sorted(set(global_errors)),
        "proof_passes": not global_errors and result["needs_review_count"] == 0,
    }


def _build_ultimate_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify the temporary Ultimate Universe repair family."""
    rows = [row for row in snapshot["dependencies"] if row["note"] == ULTIMATE_REPAIR_NOTE]
    rows.sort(key=lambda row: int(row["id"]))
    ids = [int(row["id"]) for row in rows]
    row_errors: dict[int, list[str]] = defaultdict(list)
    global_errors: list[str] = []

    group, memberships, group_errors = _group_evidence(
        snapshot,
        group_id=ULTIMATE_GROUP_ID,
        expected_name=ULTIMATE_GROUP_NAME,
    )
    source_list, entries, mapped_issue_ids, list_errors = _list_evidence(
        snapshot,
        list_id=ULTIMATE_LIST_ID,
        expected_hash=ULTIMATE_HASH,
    )
    global_errors.extend(group_errors)
    global_errors.extend(list_errors)
    if len(ids) != ULTIMATE_EXPECTED_COUNT:
        global_errors.append(
            f"population drift: expected {ULTIMATE_EXPECTED_COUNT}, found {len(ids)}"
        )
    if source_list is not None and source_list["name"] != (
        "[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)"
    ):
        global_errors.append(f"CBL source list {ULTIMATE_LIST_ID} name drifted")

    member_issue_ids = {
        int(row["issue_id"]) for row in memberships if row["issue_id"] is not None
    }
    positions_by_issue: dict[int, list[int]] = defaultdict(list)
    for position, issue_ids in mapped_issue_ids.items():
        for issue_id in issue_ids:
            positions_by_issue[issue_id].append(position)
    for values in positions_by_issue.values():
        values.sort()

    rules_by_dependency: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rule in snapshot["rules"]:
        rules_by_dependency[int(rule["legacy_dependency_id"])].append(rule)

    edge_evidence: list[dict[str, Any]] = []
    adjacency_ids: list[int] = []
    bridge_ids: list[int] = []
    for row in rows:
        dependency_id = int(row["id"])
        source_issue_id = int(row["source_issue_id"])
        target_issue_id = int(row["target_issue_id"])
        source_positions = positions_by_issue.get(source_issue_id, [])
        target_positions = positions_by_issue.get(target_issue_id, [])

        if int(row["source_user_id"]) != USER_ID or int(row["target_user_id"]) != USER_ID:
            row_errors[dependency_id].append("dependency endpoints are not both owned by user 1")
        if source_issue_id not in member_issue_ids or target_issue_id not in member_issue_ids:
            row_errors[dependency_id].append("dependency endpoint is outside dependency group 15")
        if len(source_positions) != 1 or len(target_positions) != 1:
            row_errors[dependency_id].append("dependency endpoint does not map to one CBL position")
            source_position = source_positions[0] if len(source_positions) == 1 else None
            target_position = target_positions[0] if len(target_positions) == 1 else None
            edge_kind = "unresolved"
        else:
            source_position, target_position = source_positions[0], target_positions[0]
            if source_position >= target_position:
                row_errors[dependency_id].append("repair edge does not run forward")
                edge_kind = "unresolved"
            elif target_position == source_position + 1:
                edge_kind = "strict_adjacency_duplicate"
                adjacency_ids.append(dependency_id)
            else:
                edge_kind = "historical_gap_bridge"
                bridge_ids.append(dependency_id)
        row_errors[dependency_id].extend(
            _rule_errors(row, rules_by_dependency[dependency_id], expected_note=ULTIMATE_REPAIR_NOTE)
        )
        edge_evidence.append(
            {
                "dependency_id": dependency_id,
                "source_issue_id": source_issue_id,
                "target_issue_id": target_issue_id,
                "source_position": source_position,
                "target_position": target_position,
                "kind": edge_kind,
            }
        )

    if len(adjacency_ids) != ULTIMATE_EXPECTED_ADJACENCY_COUNT:
        global_errors.append(
            "adjacency split drift: "
            f"expected {ULTIMATE_EXPECTED_ADJACENCY_COUNT}, found {len(adjacency_ids)}"
        )
    if len(bridge_ids) != ULTIMATE_EXPECTED_BRIDGE_COUNT:
        global_errors.append(
            f"bridge split drift: expected {ULTIMATE_EXPECTED_BRIDGE_COUNT}, found {len(bridge_ids)}"
        )
    created_at_values = sorted({str(_json_value(row["created_at"])) for row in rows})
    if len(created_at_values) != 1:
        global_errors.append("incident-repair dependencies were not created as one batch")

    result = _family_result(ids, row_errors, global_errors)
    return {
        "family": "ultimate_universe_temporary_repair",
        "selector": {"note_equals": ULTIMATE_REPAIR_NOTE},
        "expected_dependency_count": ULTIMATE_EXPECTED_COUNT,
        "dependency_count": len(ids),
        "dependency_ids": ids,
        "id_manifest_sha256": _manifest_sha256(ids),
        "dependency_group": {key: _json_value(value) for key, value in (group or {}).items()},
        "dependency_group_membership_count": len(memberships),
        "nonnull_sequence_order_membership_ids": [
            int(row["id"]) for row in memberships if row["sequence_order"] is not None
        ],
        "source_list": {
            key: _json_value(value) for key, value in (source_list or {}).items()
        },
        "source_position_count": len(entries),
        "incident_repair_code_reference": (
            "app/services/ultimate_universe_production_migration.py::"
            "TEMPORARY_REPAIR_NOTE"
        ),
        "created_at_values": created_at_values,
        "linked_continuity_rule_count": sum(
            len(rules_by_dependency[dependency_id]) for dependency_id in ids
        ),
        "strict_adjacency_duplicate_count": len(adjacency_ids),
        "historical_gap_bridge_count": len(bridge_ids),
        "edge_evidence": edge_evidence,
        "standalone_prerequisite_evidence": (
            "No row has independent prerequisite provenance: every dependency and linked rule "
            "uses the exact incident-repair note, every endpoint maps into the active Ultimate "
            "Universe CBL/group, every resolved edge runs forward, and the complete set divides "
            "into 55 source adjacencies plus 18 forward historical-gap bridges."
        ),
        "classification": result,
        "global_exceptions": sorted(set(global_errors)),
        "proof_passes": not global_errors and result["needs_review_count"] == 0,
    }


async def build_report() -> dict[str, Any]:
    """Build the exact, fail-closed Step 14B production classification report."""
    async with AsyncSessionLocal() as db:
        snapshot = await _load_snapshot(db)
        await db.rollback()

    unnamed = _build_unnamed_report(snapshot)
    ultimate = _build_ultimate_report(snapshot)
    unnamed_ids = set(unnamed["dependency_ids"])
    ultimate_ids = {
        int(row["dependency_id"]) for row in ultimate["edge_evidence"]
    }
    overlap = sorted(unnamed_ids & ultimate_ids)
    if overlap:
        raise RuntimeError(f"Step 14B family overlap: {overlap}")

    reading_plan_order_count = (
        int(unnamed["classification"]["reading_plan_order_count"])
        + int(ultimate["classification"]["reading_plan_order_count"])
    )
    needs_review_ids = sorted(
        list(unnamed["classification"]["needs_review_dependency_ids"])
        + list(ultimate["classification"]["needs_review_dependency_ids"])
    )
    combined_ids = sorted(unnamed_ids | ultimate_ids)
    return {
        "step": "14B",
        "production_project": "comic-pile",
        "user_id": USER_ID,
        "captured_at": _json_value(snapshot["captured_at"]),
        "scope": (
            "The Unnamed Universe cbl-order:group-16:* dependencies and exact temporary "
            "Ultimate Universe incident-repair dependencies only"
        ),
        "read_only": True,
        "families": [unnamed, ultimate],
        "total_dependency_count": len(combined_ids),
        "total_manifest_sha256": _manifest_sha256(combined_ids),
        "reading_plan_order_count": reading_plan_order_count,
        "standalone_prerequisite_count": 0,
        "needs_review_count": len(needs_review_ids),
        "needs_review_dependency_ids": needs_review_ids,
        "family_overlap_dependency_ids": overlap,
        "exceptions": [] if not needs_review_ids else ["See per-family exception ledgers."],
        "result": "PASS" if not needs_review_ids else "NEEDS_REVIEW",
        "migration_authorized": False,
        "step_14a_repeated": False,
        "step_14c_included": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Step 14B generated compatibility dependency audit"
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    report = await build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": report["result"],
                "total_dependency_count": report["total_dependency_count"],
                "reading_plan_order_count": report["reading_plan_order_count"],
                "needs_review_count": report["needs_review_count"],
                "total_manifest_sha256": report["total_manifest_sha256"],
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
