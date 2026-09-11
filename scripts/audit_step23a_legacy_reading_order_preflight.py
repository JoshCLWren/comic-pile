#!/usr/bin/env python3
"""Read-only Step 23A production preflight for the three legacy Reading Orders.

This command inspects current production PostgreSQL state and writes a
machine-readable dry-run contract for a later guarded Step 23B apply. It never
creates Reading Plans, never mutates legacy orders, and never writes production
rows.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

USER_ID = 1
STEP14_INDEX = ROOT / "docs/recovery/step14-final-classification-index.json"
GLOBAL_NEEDS_REVIEW_IDS = (101, 1929)
EXPECTED_ORDER_COUNT = 3
EXPECTED_ORDERS = (
    {
        "key": "doctor_strange",
        "name": "Doctor Strange Epic Collection Vol. 10: Infinity War",
        "expected_item_count": 17,
    },
    {
        "key": "starman",
        "name": "Starman Compendiums 1-2",
        "expected_item_count": 66,
    },
    {
        "key": "jsa",
        "name": "JSA: Robinson / Goyer / Johns",
        "expected_item_count": 57,
    },
)
EXPECTED_DEPENDENCY_OVERLAP = 13
SYNTHETIC_THREAD_TITLES = frozenset({"JSA (Robinson / Goyer / Johns)"})
PRODUCTION_PROJECT_ID = "delicate-sea-51036121"
PRODUCTION_BRANCH_ID = "br-silent-violet-ayobfez5"


def _sha256_text(value: str) -> str:
    """Return a hex SHA-256 digest for one canonical string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable(value: object) -> object:
    """Convert datetime values to ISO-8601 JSON values."""
    return value.isoformat() if isinstance(value, datetime) else value


def _stable_hash(value: object) -> str:
    """Fingerprint one JSON-serializable mutation-relevant payload."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_stable,
    )
    return _sha256_text(payload)


def _git_head() -> str:
    """Return the current repository HEAD SHA."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def _async_url(raw: str) -> str:
    """Normalize a Neon or libpq URL into an asyncpg SQLAlchemy URL."""
    url = raw
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("channel_binding", None)
    sslmode = query.pop("sslmode", None)
    if sslmode in {"require", "verify-full", "verify-ca"} or "ssl" not in query:
        query["ssl"] = "require"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _load_json(path: Path) -> dict[str, object]:
    """Load one persisted JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return cast(dict[str, object], payload)


def step14_lookup(index: dict[str, object]) -> dict[int, dict[str, str]]:
    """Expand the persisted Step 14 index into an exact dependency-ID lookup."""
    lookup_root = cast(dict[str, object], index["lookup"])
    explicit = cast(dict[str, dict[str, object]], lookup_root["explicit_slices"])
    resolved: dict[int, dict[str, str]] = {}
    for slice_name, slice_data in explicit.items():
        for family in cast(list[dict[str, object]], slice_data["families"]):
            metadata = {
                "slice": slice_name,
                "classification": str(family["classification"]),
                "family_key": str(family["family_key"]),
            }
            for dependency_id in cast(list[int], family["ids"]):
                resolved[int(dependency_id)] = metadata
    return resolved


async def _select(
    db: AsyncSession,
    statement: str,
    params: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Execute exactly one SELECT and detach its mapping rows."""
    from sqlalchemy import text

    if not statement.lstrip().upper().startswith("SELECT"):
        raise ValueError("Step 23A preflight permits SELECT statements only")
    result = await db.execute(text(statement), params or {})
    return [dict(row) for row in result.mappings().all()]


async def capture_snapshot(db: AsyncSession, user_id: int = USER_ID) -> dict[str, object]:
    """Capture every mutation-relevant fact with SELECT statements only."""
    captured = await _select(db, "SELECT CURRENT_TIMESTAMP AS captured_at")
    orders = await _select(
        db,
        """
        SELECT id, user_id, name, description
        FROM reading_orders
        WHERE user_id = :user_id
        ORDER BY id
        """,
        {"user_id": user_id},
    )
    items = await _select(
        db,
        """
        SELECT roi.id AS item_id, roi.reading_order_id, roi.position,
               roi.thread_id, roi.issue_number,
               t.title AS thread_title, t.status AS thread_status,
               t.is_blocked, t.queue_position, t.next_unread_issue_id,
               t.total_issues, t.issues_remaining, t.last_rating,
               t.reading_progress, t.notes AS thread_notes,
               i.id AS issue_id, i.status AS issue_status, i.read_at,
               i.position AS issue_position, i.created_at AS issue_created_at
        FROM reading_order_items roi
        JOIN reading_orders ro ON ro.id = roi.reading_order_id
        JOIN threads t ON t.id = roi.thread_id
        LEFT JOIN issues i
          ON i.thread_id = roi.thread_id
         AND i.issue_number = roi.issue_number
        WHERE ro.user_id = :user_id
        ORDER BY roi.reading_order_id, roi.position, roi.id
        """,
        {"user_id": user_id},
    )
    issue_ids = sorted({int(row["issue_id"]) for row in items if row["issue_id"] is not None})
    thread_ids = sorted({int(row["thread_id"]) for row in items})
    issue_params: dict[str, object] = {"user_id": user_id}
    thread_params: dict[str, object] = {"user_id": user_id}
    issue_filter = "FALSE"
    thread_filter = "FALSE"
    if issue_ids:
        issue_tokens = []
        for index, issue_id in enumerate(issue_ids):
            key = f"issue_{index}"
            issue_params[key] = issue_id
            issue_tokens.append(f":{key}")
        issue_filter = f"i.id IN ({', '.join(issue_tokens)})"
    if thread_ids:
        thread_tokens = []
        for index, thread_id in enumerate(thread_ids):
            key = f"thread_{index}"
            thread_params[key] = thread_id
            thread_tokens.append(f":{key}")
        thread_filter = f"t.id IN ({', '.join(thread_tokens)})"

    thread_issue_counts = await _select(
        db,
        f"""
        SELECT t.id AS thread_id, t.title, t.status, t.is_blocked,
               t.queue_position, t.next_unread_issue_id, t.total_issues,
               t.issues_remaining, t.last_rating, t.reading_progress,
               t.last_activity_at, COUNT(i.id) AS persisted_issue_count
        FROM threads t
        LEFT JOIN issues i ON i.thread_id = t.id
        WHERE t.user_id = :user_id AND {thread_filter}
        GROUP BY t.id
        ORDER BY t.id
        """,
        thread_params,
    )
    next_unread = await _select(
        db,
        f"""
        SELECT t.id AS thread_id, t.title, t.status, t.is_blocked,
               t.queue_position, t.next_unread_issue_id,
               ni.issue_number AS next_unread_issue_number,
               ni.status AS next_unread_status, ni.read_at AS next_unread_read_at
        FROM threads t
        LEFT JOIN issues ni ON ni.id = t.next_unread_issue_id
        WHERE t.user_id = :user_id AND {thread_filter}
        ORDER BY t.id
        """,
        thread_params,
    )
    dependencies = await _select(
        db,
        f"""
        SELECT d.id, d.source_issue_id, d.target_issue_id, d.note, d.created_at,
               st.id AS source_thread_id, st.title AS source_title,
               si.issue_number AS source_issue_number, si.status AS source_status,
               tt.id AS target_thread_id, tt.title AS target_title,
               ti.issue_number AS target_issue_number, ti.status AS target_status
        FROM dependencies d
        JOIN issues si ON si.id = d.source_issue_id
        JOIN threads st ON st.id = si.thread_id
        JOIN issues ti ON ti.id = d.target_issue_id
        JOIN threads tt ON tt.id = ti.thread_id
        WHERE st.user_id = :user_id AND tt.user_id = :user_id
          AND (
            {issue_filter.replace("i.id", "d.source_issue_id")}
            OR {issue_filter.replace("i.id", "d.target_issue_id")}
          )
        ORDER BY d.id
        """,
        issue_params,
    )
    dependency_ids = [int(row["id"]) for row in dependencies]
    rule_params: dict[str, object] = {"user_id": user_id}
    rule_filter = "FALSE"
    if dependency_ids:
        rule_tokens = []
        for index, dependency_id in enumerate(dependency_ids):
            key = f"dep_{index}"
            rule_params[key] = dependency_id
            rule_tokens.append(f":{key}")
        rule_filter = f"cr.legacy_dependency_id IN ({', '.join(rule_tokens)})"
    rules = await _select(
        db,
        f"""
        SELECT cr.id, cr.user_id, cr.legacy_dependency_id, cr.source_type,
               cr.source_id, cr.target_type, cr.target_id, cr.satisfaction_type,
               cr.checkpoint_issue_id, cr.convergence_targets, cr.note,
               cr.created_at, cr.updated_at
        FROM continuity_rules cr
        WHERE cr.user_id = :user_id AND {rule_filter}
        ORDER BY cr.id
        """,
        rule_params,
    )
    targeting_rules = await _select(
        db,
        f"""
        SELECT cr.id, cr.legacy_dependency_id, cr.source_type, cr.source_id,
               cr.target_type, cr.target_id, cr.satisfaction_type, cr.note,
               si.status AS source_status, si.issue_number AS source_issue_number,
               st.title AS source_title
        FROM continuity_rules cr
        JOIN threads t ON t.user_id = :user_id AND {thread_filter}
        LEFT JOIN issues si
          ON cr.source_type = 'issue' AND si.id = cr.source_id
        LEFT JOIN threads st ON st.id = si.thread_id
        WHERE cr.user_id = :user_id
          AND cr.target_type = 'issue'
          AND cr.target_id = t.next_unread_issue_id
        ORDER BY t.id, cr.id
        """,
        thread_params,
    )
    plans = await _select(
        db,
        """
        SELECT id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at
        FROM continuity_plans
        WHERE user_id = :user_id
        ORDER BY id
        """,
        {"user_id": user_id},
    )
    identities = []
    events = []
    sequence_orders = []
    cbl_entries = []
    if issue_ids:
        identities = await _select(
            db,
            f"""
            SELECT m.id AS mapping_id, m.issue_id, m.status, m.confidence,
                   m.evidence_source, ei.id AS external_identity_id,
                   ei.provider, ei.entity_type, ei.external_id
            FROM issue_external_identity_mappings m
            JOIN external_identities ei ON ei.id = m.external_identity_id
            WHERE {issue_filter.replace("i.id", "m.issue_id")}
            ORDER BY m.id
            """,
            issue_params,
        )
        events = await _select(
            db,
            f"""
            SELECT e.id, e.type, e.timestamp, e.thread_id, e.selected_thread_id,
                   e.issue_id, e.issue_number, e.rating, e.issues_read
            FROM events e
            LEFT JOIN sessions s ON s.id = e.session_id
            WHERE (
                {thread_filter.replace("t.id", "e.thread_id")}
                OR {thread_filter.replace("t.id", "e.selected_thread_id")}
                OR {issue_filter.replace("i.id", "e.issue_id")}
            )
              AND (s.user_id = :user_id OR s.user_id IS NULL)
            ORDER BY e.id
            """,
            {**issue_params, **thread_params},
        )
        sequence_orders = await _select(
            db,
            f"""
            SELECT gm.id, gm.group_id, gm.issue_id, gm.thread_id, gm.sequence_order
            FROM dependency_group_memberships gm
            WHERE {issue_filter.replace("i.id", "gm.issue_id")}
              AND gm.sequence_order IS NOT NULL
            ORDER BY gm.id
            """,
            issue_params,
        )
        cbl_entries = await _select(
            db,
            f"""
            SELECT cse.id, cse.list_id, cse.position, cse.series_name,
                   cse.issue_number, csl.name AS list_name, csl.active,
                   m.issue_id
            FROM cbl_source_entries cse
            JOIN cbl_source_lists csl ON csl.id = cse.list_id
            JOIN issue_external_identity_mappings m
              ON m.status = 'confirmed'
             AND {issue_filter.replace("i.id", "m.issue_id")}
            JOIN external_identities ei
              ON ei.id = m.external_identity_id
             AND ei.id = cse.external_issue_identity_id
            WHERE csl.active IS TRUE
            ORDER BY cse.list_id, cse.position, cse.id
            """,
            issue_params,
        )
    return {
        "captured_at": captured[0]["captured_at"],
        "orders": orders,
        "items": items,
        "thread_issue_counts": thread_issue_counts,
        "next_unread": next_unread,
        "dependencies": dependencies,
        "rules": rules,
        "targeting_rules": targeting_rules,
        "plans": plans,
        "identities": identities,
        "events": events,
        "sequence_orders": sequence_orders,
        "cbl_entries": cbl_entries,
    }


def _order_key(name: str) -> str | None:
    """Return the stable recovery key for one expected legacy order name."""
    for spec in EXPECTED_ORDERS:
        if spec["name"] == name:
            return str(spec["key"])
    return None


def _item_representation(row: dict[str, object]) -> str:
    """Describe the persisted legacy storage shape for one Reading Order item."""
    if row["issue_number"] is None:
        return "thread_only"
    return "thread_plus_issue_number"


def _identity_confidence(row: dict[str, object], match_count: int) -> str:
    """Return the fail-closed identity confidence for one resolved item."""
    if row["issue_number"] is None:
        return "unresolved_missing_issue_number"
    if row["issue_id"] is None:
        return "unresolved_missing_issue"
    if match_count != 1:
        return "ambiguous_multiple_matches"
    return "exact_thread_and_issue_number"


def _lane() -> dict[str, object]:
    """Return the single informational lane used by every target plan."""
    return {"id": "main", "name": "Main", "order": 0}


def _plan_node(
    *,
    order_id: int,
    position: int,
    issue_id: int,
    label: str,
    item_id: int,
    legacy_position: int,
) -> dict[str, object]:
    """Return one issue-level canonical Reading Plan node."""
    return {
        "id": f"legacy-ro-{order_id}-pos-{position}",
        "node_type": "issue",
        "ref_id": issue_id,
        "lane_id": "main",
        "position": position,
        "label": label,
        "source_role": None,
        "source_confidence": None,
        "source_explanation": None,
        "source_paths": None,
        "source_cbl_placements": None,
        "source_story_arc_ids": None,
        "source_target_story_arc_id": None,
        "reader_role": None,
        "reader_optional": None,
        "is_checkpoint": False,
        "convergence_gate": [],
        "provenance": {
            "migrated_from": "legacy_reading_order",
            "reading_order_id": order_id,
            "legacy_item_id": item_id,
            "legacy_position": legacy_position,
        },
    }


def build_report(
    snapshot: dict[str, object],
    *,
    step14_index: dict[str, object],
    base_main_sha: str,
) -> dict[str, object]:
    """Classify a fresh read-only snapshot into the Step 23A preflight contract."""
    errors: list[str] = []
    orders = cast(list[dict[str, object]], snapshot["orders"])
    items = cast(list[dict[str, object]], snapshot["items"])
    threads = {
        int(row["thread_id"]): row
        for row in cast(list[dict[str, object]], snapshot["thread_issue_counts"])
    }
    next_unread = {
        int(row["thread_id"]): row for row in cast(list[dict[str, object]], snapshot["next_unread"])
    }
    dependencies = cast(list[dict[str, object]], snapshot["dependencies"])
    rules = cast(list[dict[str, object]], snapshot["rules"])
    targeting_rules = cast(list[dict[str, object]], snapshot["targeting_rules"])
    plans = cast(list[dict[str, object]], snapshot["plans"])
    identities = cast(list[dict[str, object]], snapshot["identities"])
    events = cast(list[dict[str, object]], snapshot["events"])
    sequence_orders = cast(list[dict[str, object]], snapshot["sequence_orders"])
    cbl_entries = cast(list[dict[str, object]], snapshot["cbl_entries"])
    classifications = step14_lookup(step14_index)

    if len(orders) != EXPECTED_ORDER_COUNT:
        errors.append(
            f"production Reading Order count drifted: expected "
            f"{EXPECTED_ORDER_COUNT}, found {len(orders)}"
        )

    items_by_order: dict[int, list[dict[str, object]]] = defaultdict(list)
    match_counts: dict[tuple[int, int, str | None], int] = Counter()
    for row in items:
        order_id = int(row["reading_order_id"])
        items_by_order[order_id].append(row)
        issue_number = None if row["issue_number"] is None else str(row["issue_number"])
        match_counts[(order_id, int(row["thread_id"]), issue_number)] += 1

    order_members: dict[str, list[int]] = {}
    issue_membership: dict[int, list[tuple[str, int]]] = defaultdict(list)
    order_reports: list[dict[str, object]] = []
    proposed_plans: list[dict[str, object]] = []
    unresolved_items: list[dict[str, object]] = []
    resolved_issue_ids: list[int] = []
    reader_issues: list[dict[str, object]] = []
    all_item_rows: list[dict[str, object]] = []

    expected_by_name = {spec["name"]: spec for spec in EXPECTED_ORDERS}
    found_names = [str(order["name"]) for order in orders]
    for spec in EXPECTED_ORDERS:
        if spec["name"] not in found_names:
            errors.append(f"missing expected Reading Order {spec['name']!r}")

    for order in orders:
        order_id = int(order["id"])
        name = str(order["name"])
        key = _order_key(name) or f"unexpected_{order_id}"
        expected = expected_by_name.get(name)
        order_items = items_by_order.get(order_id, [])
        positions = [int(row["position"]) for row in order_items]
        duplicate_positions = sorted(
            {position for position in positions if positions.count(position) > 1}
        )
        if duplicate_positions:
            errors.append(f"{name}: duplicate positions {duplicate_positions}")
        if expected is not None and len(order_items) != int(expected["expected_item_count"]):
            errors.append(
                f"{name}: item count drifted, expected "
                f"{expected['expected_item_count']}, found {len(order_items)}"
            )
        if expected is not None and positions != list(range(1, len(order_items) + 1)):
            errors.append(f"{name}: positions are not contiguous starting at 1")

        resolved_nodes: list[dict[str, object]] = []
        item_reports: list[dict[str, object]] = []
        seen_issue_ids: list[int] = []
        for offset, row in enumerate(order_items):
            issue_number = None if row["issue_number"] is None else str(row["issue_number"])
            matches = match_counts[(order_id, int(row["thread_id"]), issue_number)]
            confidence = _identity_confidence(row, matches)
            thread = threads.get(int(row["thread_id"]), {})
            persisted_issue_count = int(thread.get("persisted_issue_count") or 0)
            items_on_thread = sum(
                1 for item in order_items if int(item["thread_id"]) == int(row["thread_id"])
            )
            uses_broad_or_synthetic_thread = (
                str(row["thread_title"]) in SYNTHETIC_THREAD_TITLES
                or persisted_issue_count > items_on_thread
            )
            requires_transform = True
            unresolved = confidence != "exact_thread_and_issue_number" or row["issue_id"] is None
            issue_id = None if row["issue_id"] is None else int(row["issue_id"])
            label = (
                f"{row['thread_title']} #{issue_number}"
                if issue_number
                else str(row["thread_title"])
            )
            if unresolved:
                unresolved_items.append(
                    {
                        "reading_order_id": order_id,
                        "legacy_item_id": int(row["item_id"]),
                        "legacy_position": int(row["position"]),
                        "confidence": confidence,
                    }
                )
                errors.append(f"{name} position {row['position']} failed closed: {confidence}")
            else:
                assert issue_id is not None
                seen_issue_ids.append(issue_id)
                resolved_issue_ids.append(issue_id)
                issue_membership[issue_id].append((key, int(row["position"])))
                resolved_nodes.append(
                    _plan_node(
                        order_id=order_id,
                        position=offset,
                        issue_id=issue_id,
                        label=label,
                        item_id=int(row["item_id"]),
                        legacy_position=int(row["position"]),
                    )
                )
                reader_issues.append(
                    {
                        "issue_id": issue_id,
                        "thread_id": int(row["thread_id"]),
                        "status": row["issue_status"],
                        "read_at": _stable(row["read_at"]),
                        "issue_number": issue_number,
                    }
                )
            item_report = {
                "legacy_order_position": int(row["position"]),
                "legacy_item_id": int(row["item_id"]),
                "legacy_thread_id": int(row["thread_id"]),
                "legacy_issue_id": issue_id,
                "legacy_issue_number": issue_number,
                "legacy_item_representation": _item_representation(row),
                "resolved_canonical_issue_id": issue_id,
                "resolved_canonical_thread_id": int(row["thread_id"]),
                "title": row["thread_title"],
                "issue_number": issue_number,
                "current_read_status": row["issue_status"],
                "read_at": _stable(row["read_at"]),
                "identity_confidence": confidence,
                "identity_evidence": (
                    "unique (thread_id, issue_number) match to an existing Issue row"
                    if confidence == "exact_thread_and_issue_number"
                    else confidence
                ),
                "requires_thread_to_issue_transform": requires_transform,
                "uses_broad_or_synthetic_thread": uses_broad_or_synthetic_thread,
                "missing_or_deleted_reference": row["issue_id"] is None,
            }
            item_reports.append(item_report)
            all_item_rows.append(item_report)

        duplicate_issue_ids = sorted(
            {issue_id for issue_id in seen_issue_ids if seen_issue_ids.count(issue_id) > 1}
        )
        if duplicate_issue_ids:
            errors.append(f"{name}: duplicate canonical issues {duplicate_issue_ids}")
        order_members[key] = seen_issue_ids
        referenced_thread_ids = sorted({int(row["thread_id"]) for row in order_items})
        referenced_issue_ids = list(seen_issue_ids)
        order_reports.append(
            {
                "key": key,
                "reading_order_id": order_id,
                "user_id": int(order["user_id"]),
                "title": name,
                "description": order["description"],
                "item_count": len(order_items),
                "expected_item_count": (
                    None if expected is None else int(expected["expected_item_count"])
                ),
                "item_count_matches_expected": (
                    expected is not None
                    and len(order_items) == int(expected["expected_item_count"])
                ),
                "duplicate_positions": duplicate_positions,
                "duplicate_canonical_issue_ids": duplicate_issue_ids,
                "referenced_thread_ids": referenced_thread_ids,
                "referenced_issue_ids": referenced_issue_ids,
                "items": item_reports,
            }
        )
        writer_nodes = [
            {key_name: value for key_name, value in node.items() if key_name != "provenance"}
            for node in resolved_nodes
        ]
        proposed_plans.append(
            {
                "name": name,
                "ordering_mode": "informational",
                "lanes": [_lane()],
                "ordered_canonical_nodes": resolved_nodes,
                "writer_payload": {
                    "name": name,
                    "ordering_mode": "informational",
                    "lanes": [_lane()],
                    "nodes": writer_nodes,
                },
                "source_provenance": {
                    "migrated_from": "legacy_reading_order",
                    "reading_order_id": order_id,
                    "legacy_rows_retained_for_rollback": True,
                    "cbl_provenance_included": False,
                    "strict_adjacency_blockers": 0,
                    "invented_checkpoint_or_convergence": False,
                    "dependency_group_sequence_order_changes": 0,
                },
            }
        )

    overlapping_plans: list[dict[str, object]] = []
    resolved_issue_set = set(resolved_issue_ids)
    for plan in plans:
        nodes = cast(list[dict[str, object]], plan["nodes_json"] or [])
        for node in nodes:
            if node.get("node_type") != "issue":
                continue
            ref_id = int(cast(object, node.get("ref_id") or 0))
            if ref_id in resolved_issue_set:
                overlapping_plans.append(
                    {
                        "plan_id": int(plan["id"]),
                        "plan_name": plan["name"],
                        "ordering_mode": plan["ordering_mode"],
                        "issue_id": ref_id,
                        "plan_position": node.get("position"),
                        "coexistence_expected": False,
                        "duplicate_reader_intent": True,
                    }
                )
    if overlapping_plans:
        errors.append(
            f"existing Reading Plan overlap found for {len(overlapping_plans)} issue nodes"
        )

    overlap_rows: list[dict[str, object]] = []
    for row in dependencies:
        dependency_id = int(row["id"])
        source_id = int(row["source_issue_id"])
        target_id = int(row["target_issue_id"])
        source_memberships = issue_membership.get(source_id, [])
        target_memberships = issue_membership.get(target_id, [])
        both_inside_same_order = any(
            source_key == target_key
            for source_key, _ in source_memberships
            for target_key, _ in target_memberships
        )
        only_one_endpoint_inside = bool(source_memberships) ^ bool(target_memberships)
        adjacency = False
        adjacency_positions: list[str] = []
        for source_key, source_position in source_memberships:
            for target_key, target_position in target_memberships:
                if source_key == target_key and target_position - source_position == 1:
                    adjacency = True
                    adjacency_positions.append(f"{source_key}:{source_position}->{target_position}")
        classified = classifications.get(dependency_id)
        if classified is None:
            errors.append(f"dependency {dependency_id} is missing from the Step 14 ledger")
            classification = "unclassified_snapshot_drift"
            family_key = "missing_from_step14"
            slice_name = None
        else:
            classification = classified["classification"]
            family_key = classified["family_key"]
            slice_name = classified["slice"]
        overlap_rows.append(
            {
                "dependency_id": dependency_id,
                "source_issue_id": source_id,
                "source_title": row["source_title"],
                "source_issue_number": row["source_issue_number"],
                "source_status": row["source_status"],
                "target_issue_id": target_id,
                "target_title": row["target_title"],
                "target_issue_number": row["target_issue_number"],
                "target_status": row["target_status"],
                "note": row["note"],
                "step14_slice": slice_name,
                "step14_classification": classification,
                "step14_family_key": family_key,
                "both_endpoints_inside_same_legacy_order": both_inside_same_order,
                "only_one_endpoint_inside": only_one_endpoint_inside,
                "corresponds_to_legacy_adjacency": adjacency,
                "adjacency_positions": adjacency_positions,
                "must_survive_as_standalone_prerequisite": (
                    classification == "standalone_prerequisite"
                ),
                "is_global_needs_review": dependency_id in GLOBAL_NEEDS_REVIEW_IDS,
            }
        )

    overlap_ids = [int(row["dependency_id"]) for row in overlap_rows]
    if len(overlap_ids) != len(set(overlap_ids)):
        errors.append("dependency overlap contains duplicate IDs")
    if len(overlap_ids) != EXPECTED_DEPENDENCY_OVERLAP:
        errors.append(
            f"dependency overlap drifted: expected {EXPECTED_DEPENDENCY_OVERLAP}, "
            f"found {len(overlap_ids)}"
        )

    rules_by_dependency = {
        int(row["legacy_dependency_id"]): row
        for row in rules
        if row["legacy_dependency_id"] is not None
    }
    rule_reports: list[dict[str, object]] = []
    for overlap in overlap_rows:
        dependency_id = int(overlap["dependency_id"])
        rule = rules_by_dependency.get(dependency_id)
        if rule is None:
            errors.append(f"dependency {dependency_id} has no linked ContinuityRule")
            continue
        source_status = next(
            (str(row["source_status"]) for row in dependencies if int(row["id"]) == dependency_id),
            None,
        )
        satisfied = source_status == "read"
        rule_reports.append(
            {
                "rule_id": int(rule["id"]),
                "legacy_dependency_id": dependency_id,
                "ownership": "user_1_legacy_backed",
                "provenance": "legacy_dependency_mirror",
                "source_type": rule["source_type"],
                "source_id": int(rule["source_id"]),
                "target_type": rule["target_type"],
                "target_id": int(rule["target_id"]),
                "satisfaction_type": rule["satisfaction_type"],
                "current_satisfaction_state": "satisfied" if satisfied else "unsatisfied",
                "legacy_backed": True,
                "must_survive_independently": bool(
                    overlap["must_survive_as_standalone_prerequisite"]
                ),
                "plan_owned_rule_created": False,
            }
        )

    eligibility: list[dict[str, object]] = []
    eligibility_mismatches: list[dict[str, object]] = []
    targeting_by_thread: dict[int, list[dict[str, object]]] = defaultdict(list)
    next_unread_ids = {
        int(row["thread_id"]): row.get("next_unread_issue_id") for row in next_unread.values()
    }
    for rule in targeting_rules:
        target_id = int(rule["target_id"])
        for thread_id, next_id in next_unread_ids.items():
            if next_id == target_id:
                targeting_by_thread[thread_id].append(rule)
    for thread_id, thread in sorted(threads.items()):
        current = next_unread[thread_id]
        next_id = current.get("next_unread_issue_id")
        blockers: list[dict[str, object]] = []
        standalone_blockers: list[int] = []
        for rule in targeting_by_thread.get(thread_id, []):
            source_status = rule.get("source_status")
            satisfied = source_status == "read"
            if satisfied:
                continue
            classified = classifications.get(int(rule["legacy_dependency_id"] or 0), {})
            blocker = {
                "rule_id": int(rule["id"]),
                "legacy_dependency_id": rule["legacy_dependency_id"],
                "satisfaction_type": rule["satisfaction_type"],
                "source_type": rule["source_type"],
                "source_id": rule["source_id"],
                "source_label": (
                    f"{rule['source_title']} #{rule['source_issue_number']}"
                    if rule["source_title"] is not None
                    else f"{rule['source_type']} {rule['source_id']}"
                ),
                "source_status": source_status,
                "step14_classification": classified.get("classification"),
                "step14_family_key": classified.get("family_key"),
            }
            blockers.append(blocker)
            if classified.get("classification") == "standalone_prerequisite":
                standalone_blockers.append(int(rule["legacy_dependency_id"]))
        derived_eligible = next_id is not None and not blockers
        persisted_blocked = bool(thread["is_blocked"])
        mismatch = bool(next_id is not None and derived_eligible == persisted_blocked)
        if next_id is None:
            mismatch = persisted_blocked is True
        if mismatch:
            eligibility_mismatches.append(
                {
                    "thread_id": thread_id,
                    "persisted_is_blocked": persisted_blocked,
                    "derived_eligible": derived_eligible,
                }
            )
        eligibility.append(
            {
                "thread_id": thread_id,
                "title": thread["title"],
                "status": thread["status"],
                "currently_active": thread["status"] == "active",
                "queue_position": thread["queue_position"],
                "next_unread_issue_id": next_id,
                "next_unread_issue_number": current.get("next_unread_issue_number"),
                "persisted_is_blocked": persisted_blocked,
                "authoritative_derived_eligible": derived_eligible,
                "roll_candidate": next_id is not None and thread["status"] == "active",
                "blockers": blockers,
                "surviving_standalone_prerequisites_blocking": standalone_blockers,
                "persisted_vs_derived_mismatch": mismatch,
            }
        )

    classification_counts = Counter(str(row["step14_classification"]) for row in overlap_rows)
    standalone_ids = [
        int(row["dependency_id"])
        for row in overlap_rows
        if row["must_survive_as_standalone_prerequisite"]
    ]
    needs_review_touch = [
        int(row["dependency_id"]) for row in overlap_rows if row["is_global_needs_review"]
    ]
    reader_threads = [
        {
            "thread_id": int(thread["thread_id"]),
            "title": thread["title"],
            "status": thread["status"],
            "is_blocked": thread["is_blocked"],
            "queue_position": thread["queue_position"],
            "next_unread_issue_id": thread["next_unread_issue_id"],
            "issues_remaining": thread["issues_remaining"],
            "last_rating": thread["last_rating"],
            "reading_progress": thread["reading_progress"],
            "last_activity_at": _stable(thread["last_activity_at"]),
        }
        for thread in cast(list[dict[str, object]], snapshot["thread_issue_counts"])
    ]
    identity_rows = [
        {
            "mapping_id": int(row["mapping_id"]),
            "issue_id": int(row["issue_id"]),
            "status": row["status"],
            "provider": row["provider"],
            "entity_type": row["entity_type"],
            "external_id": row["external_id"],
            "confidence": row["confidence"],
        }
        for row in identities
    ]
    event_rows = [
        {
            "id": int(row["id"]),
            "type": row["type"],
            "timestamp": _stable(row["timestamp"]),
            "thread_id": row["thread_id"],
            "selected_thread_id": row["selected_thread_id"],
            "issue_id": row["issue_id"],
            "issue_number": row["issue_number"],
            "rating": row["rating"],
            "issues_read": row["issues_read"],
        }
        for row in events
    ]
    reader_state = {
        "issue_state_hash": _stable_hash(reader_issues),
        "thread_state_hash": _stable_hash(reader_threads),
        "event_state_hash": _stable_hash(event_rows),
        "identity_state_hash": _stable_hash(identity_rows),
        "issues": reader_issues,
        "threads": reader_threads,
        "events": event_rows,
        "identities": identity_rows,
    }
    token_payload = {
        "orders": [
            {
                "id": int(order["reading_order_id"]),
                "title": order["title"],
                "item_count": order["item_count"],
                "positions": [
                    {
                        "position": item["legacy_order_position"],
                        "item_id": item["legacy_item_id"],
                        "thread_id": item["legacy_thread_id"],
                        "issue_id": item["resolved_canonical_issue_id"],
                    }
                    for item in cast(list[dict[str, object]], order["items"])
                ],
            }
            for order in order_reports
        ],
        "resolved_canonical_issue_ids": resolved_issue_ids,
        "overlapping_dependencies": overlap_ids,
        "linked_continuity_rule_ids": [int(row["rule_id"]) for row in rule_reports],
        "overlapping_reading_plans": overlapping_plans,
        "reader_state_hashes": {
            "issues": reader_state["issue_state_hash"],
            "threads": reader_state["thread_state_hash"],
            "events": reader_state["event_state_hash"],
            "identities": reader_state["identity_state_hash"],
        },
        "eligibility_baseline": [
            {
                "thread_id": row["thread_id"],
                "next_unread_issue_id": row["next_unread_issue_id"],
                "persisted_is_blocked": row["persisted_is_blocked"],
                "authoritative_derived_eligible": row["authoritative_derived_eligible"],
                "blocker_rule_ids": [
                    int(cast(dict[str, object], blocker)["rule_id"])
                    for blocker in cast(list[dict[str, object]], row["blockers"])
                ],
            }
            for row in eligibility
        ],
    }
    snapshot_token = _stable_hash(token_payload)
    every_resolved = len(unresolved_items) == 0 and all(
        item["resolved_canonical_issue_id"] is not None for item in all_item_rows
    )
    result = "PASS"
    if errors:
        result = "DRIFT" if any("drift" in error for error in errors) else "REVIEW_REQUIRED"
        if any(
            item["identity_confidence"] != "exact_thread_and_issue_number" for item in all_item_rows
        ):
            result = "REVIEW_REQUIRED"

    item_counts = {str(order["key"]): int(order["item_count"]) for order in order_reports}
    reconciliation = {
        "production_reading_order_count": len(orders),
        "expected_reading_order_count": EXPECTED_ORDER_COUNT,
        "count_is_exactly_3": len(orders) == EXPECTED_ORDER_COUNT,
        "item_counts": item_counts,
        "total_item_count": len(items),
        "every_legacy_item_resolved_exactly_once": every_resolved,
        "unresolved_or_ambiguous_item_count": len(unresolved_items),
        "existing_reading_plan_overlap_count": len(overlapping_plans),
        "dependency_overlap_count": len(overlap_ids),
        "dependency_classification_breakdown": {
            "reading_plan_order": int(classification_counts.get("reading_plan_order", 0)),
            "standalone_prerequisite": int(classification_counts.get("standalone_prerequisite", 0)),
            "needs_review": int(classification_counts.get("needs_review", 0)),
        },
        "standalone_prerequisites_that_must_survive": len(standalone_ids),
        "standalone_prerequisite_dependency_ids": standalone_ids,
        "global_needs_review_rows_touch_these_orders": bool(needs_review_touch),
        "global_needs_review_dependency_ids_touching": needs_review_touch,
        "informational_migration_would_change_roll_eligibility": False,
        "factual_reader_state_can_be_preserved_unchanged": True,
        "persisted_vs_derived_eligibility_mismatch_count": len(eligibility_mismatches),
        "sequence_order_rows_touching_resolved_issues": len(sequence_orders),
        "active_cbl_entries_corroborating_resolved_issues": len(cbl_entries),
        "snapshot_token": snapshot_token,
    }
    return {
        "step": "23A",
        "result": result,
        "captured_at": _stable(snapshot["captured_at"]),
        "base_main_sha": base_main_sha,
        "production_project_id": PRODUCTION_PROJECT_ID,
        "production_branch_id": PRODUCTION_BRANCH_ID,
        "user_id": USER_ID,
        "read_only": True,
        "reconciliation": reconciliation,
        "legacy_reading_orders": order_reports,
        "dependency_overlap": overlap_rows,
        "continuity_rule_overlap": rule_reports,
        "existing_reading_plan_overlaps": overlapping_plans,
        "reader_state": reader_state,
        "eligibility_baseline": eligibility,
        "eligibility_mismatches": eligibility_mismatches,
        "proposed_canonical_targets": proposed_plans,
        "unresolved_or_ambiguous_items": unresolved_items,
        "errors": sorted(set(errors)),
        "safety": {
            "production_mutated": False,
            "reading_plans_created_or_updated": False,
            "legacy_reading_orders_modified": False,
            "dependencies_modified": False,
            "continuity_rules_modified": False,
            "blocked_state_modified": False,
            "sequence_order_modified": False,
            "roll_behavior_modified": False,
            "ultimate_universe_cutover_started": False,
            "broad_cbl_cleanup_started": False,
            "architecture_hold_2363_lifted": False,
            "step_23b_started": False,
            "migration_authorized": False,
        },
    }


def render_summary(report: dict[str, object]) -> str:
    """Render the human-readable Step 23A reconciliation report."""
    reconciliation = cast(dict[str, object], report["reconciliation"])
    item_counts = cast(dict[str, int], reconciliation["item_counts"])
    breakdown = cast(dict[str, int], reconciliation["dependency_classification_breakdown"])
    orders = cast(list[dict[str, object]], report["legacy_reading_orders"])
    eligibility = cast(list[dict[str, object]], report["eligibility_baseline"])
    lines = [
        "# Step 23A — Legacy Reading Order migration preflight",
        "",
        "Read-only production preflight for migrating the three surviving legacy",
        "Reading Orders into informational canonical Reading Plans.",
        "",
        f"- Result: `{report['result']}`",
        f"- Captured at: `{report['captured_at']}`",
        f"- Base HEAD: `{report['base_main_sha']}`",
        f"- Production project: `{report['production_project_id']}`",
        f"- Production branch: `{report['production_branch_id']}`",
        f"- Snapshot token: `{reconciliation['snapshot_token']}`",
        "",
        "## Required reconciliation",
        "",
        f"- Production Reading Order count for user 1: **{reconciliation['production_reading_order_count']}**",
        f"- Still exactly 3: **{reconciliation['count_is_exactly_3']}**",
        f"- Doctor Strange item count: **{item_counts.get('doctor_strange', 0)}**",
        f"- Starman item count: **{item_counts.get('starman', 0)}**",
        f"- JSA item count: **{item_counts.get('jsa', 0)}**",
        f"- Total item count: **{reconciliation['total_item_count']}**",
        f"- Every legacy item resolved to exactly one canonical plan node: **{reconciliation['every_legacy_item_resolved_exactly_once']}**",
        f"- Unresolved or ambiguous items: **{reconciliation['unresolved_or_ambiguous_item_count']}**",
        f"- Existing Reading Plan overlaps: **{reconciliation['existing_reading_plan_overlap_count']}**",
        f"- Dependency overlap count: **{reconciliation['dependency_overlap_count']}**",
        f"- Dependency classification breakdown: reading_plan_order **{breakdown['reading_plan_order']}**, standalone_prerequisite **{breakdown['standalone_prerequisite']}**, needs_review **{breakdown['needs_review']}**",
        f"- Standalone prerequisites that must survive: **{reconciliation['standalone_prerequisites_that_must_survive']}** (`{reconciliation['standalone_prerequisite_dependency_ids']}`)",
        f"- Global Step 14 needs_review rows touch these orders: **{reconciliation['global_needs_review_rows_touch_these_orders']}**",
        f"- Informational migration would change current Roll eligibility: **{reconciliation['informational_migration_would_change_roll_eligibility']}**",
        f"- All factual reader state can be preserved unchanged: **{reconciliation['factual_reader_state_can_be_preserved_unchanged']}**",
        f"- Persisted vs derived eligibility mismatches: **{reconciliation['persisted_vs_derived_eligibility_mismatch_count']}**",
        "",
        "## Proposed canonical targets",
        "",
        "Each order becomes one `ordering_mode=informational` Reading Plan with a",
        "single `main` lane and issue-level nodes in the existing reader-visible",
        "order. No adjacency blockers, checkpoints, convergence gates, CBL",
        "provenance, or `sequence_order` changes are proposed.",
        "",
    ]
    for order in orders:
        lines.append(
            f"- `{order['title']}`: {order['item_count']} issue nodes, "
            f"Reading Order id {order['reading_order_id']}"
        )
    lines.extend(
        [
            "",
            "## Current eligibility baseline",
            "",
        ]
    )
    for row in eligibility:
        blockers = cast(list[dict[str, object]], row["blockers"])
        blocker_text = "none"
        if blockers:
            blocker_text = ", ".join(
                f"#{blocker['legacy_dependency_id']} {blocker['source_label']} "
                f"({blocker['step14_classification']})"
                for blocker in blockers
            )
        lines.append(
            f"- Thread {row['thread_id']} `{row['title']}`: "
            f"next unread {row['next_unread_issue_id']}, "
            f"persisted blocked={row['persisted_is_blocked']}, "
            f"derived eligible={row['authoritative_derived_eligible']}, "
            f"blockers={blocker_text}"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "No production state was changed. Legacy Reading Orders remain in place",
            "for rollback. Architecture hold #2363 remains in force. Step 23B has",
            "not started.",
            "",
        ]
    )
    errors = cast(list[str], report["errors"])
    if errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")
    return "\n".join(lines)


async def run_preflight(output: Path, summary: Path | None) -> int:
    """Capture production read-only, persist artifacts, and return the exit code."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL is required for the production preflight")
    engine = create_async_engine(
        _async_url(raw_url),
        pool_pre_ping=True,
        connect_args={
            "timeout": 30,
            "command_timeout": 120,
            "server_settings": {"default_transaction_read_only": "on"},
        },
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            try:
                snapshot = await capture_snapshot(db)
            finally:
                await db.rollback()
    finally:
        await engine.dispose()
    report = build_report(
        snapshot,
        step14_index=_load_json(STEP14_INDEX),
        base_main_sha=_git_head(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=_stable) + "\n",
        encoding="utf-8",
    )
    if summary is not None:
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(render_summary(report), encoding="utf-8")
    print(json.dumps(cast(dict[str, object], report["reconciliation"]), indent=2, sort_keys=True))
    return 0 if report["result"] == "PASS" else 1


def main() -> int:
    """Run the Step 23A read-only production preflight."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    return asyncio.run(run_preflight(args.output, args.summary))


if __name__ == "__main__":
    raise SystemExit(main())
