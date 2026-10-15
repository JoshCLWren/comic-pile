"""Read-only, user-scoped Custom CBL versus legacy Reading Plan census.

Run with an explicit asyncpg URL and user ID. Pairing requires a durable
reading_plan_sources.custom_cbl_list_id link; matching names are not evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)


@dataclass(frozen=True)
class Snapshot:
    """User-owned rows captured in one read-only transaction."""

    lists: Sequence[CustomCBLList]
    entries: Sequence[CustomCBLEntry]
    plans: Sequence[ContinuityPlan]
    memberships: Sequence[ReadingPlanIssue]
    sources: Sequence[ReadingPlanSource]
    placements: Sequence[ReadingPlanSourcePlacement] = field(default_factory=tuple)


def _entry_evidence(row: CustomCBLEntry) -> dict[str, object]:
    """Preserve all list-local fields currently stored on an entry."""
    return {
        "entry_id": row.id,
        "issue_id": row.issue_id,
        "position": row.position,
        "gate": row.gate,
        "skipped": row.skipped,
        "checkpoint": row.is_checkpoint,
        "checkpoint_target_issue_ids": row.checkpoint_target_issue_ids,
    }


def _source_evidence(row: ReadingPlanSource, owned_list_ids: set[int]) -> dict[str, object]:
    """Redact a source link that does not resolve to a user-owned list."""
    owned = row.custom_cbl_list_id is None or row.custom_cbl_list_id in owned_list_ids
    return {
        "source_id": row.id,
        "raw_source_path": row.raw_source_path,
        "repository": row.repository,
        "source_path": row.source_path,
        "cbl_source_list_id": row.cbl_source_list_id,
        "custom_cbl_list_id": row.custom_cbl_list_id if owned else None,
        "foreign_or_missing_list_link": not owned,
        "revision_sha": row.revision_sha,
        "content_hash": row.content_hash,
        "metadata": row.metadata_json,
    }


def _plan_node_evidence(
    plan: ContinuityPlan, issues: Sequence[ReadingPlanIssue]
) -> dict[str, object]:
    """Expose raw plan JSON and compare its issue nodes with durable memberships."""
    raw_nodes = plan.nodes_json
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    malformed_nodes = (
        [{"container": raw_nodes}]
        if not isinstance(raw_nodes, list)
        else [
            {"index": index, "node": node}
            for index, node in enumerate(nodes)
            if not isinstance(node, dict)
            or (node.get("node_type") == "issue" and type(node.get("ref_id")) is not int)
        ]
    )
    node_ids = [
        node["ref_id"]
        for node in nodes
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and type(node.get("ref_id")) is int
    ]
    duplicate_ids = sorted(issue_id for issue_id, count in Counter(node_ids).items() if count > 1)
    reader_evidence = [
        {"index": index, "node": node}
        for index, node in enumerate(nodes)
        if isinstance(node, dict)
        and (node.get("reader_role") is not None or node.get("reader_optional") is not None)
    ]
    anomalies = []
    if reader_evidence:
        anomalies.append("unclassified_plan_json_skip_exclusion_evidence")
    if any(row.is_checkpoint for row in issues):
        anomalies.append("unclassified_plan_checkpoint_evidence")
    if malformed_nodes:
        anomalies.append("malformed_plan_nodes")
    if duplicate_ids:
        anomalies.append("duplicate_plan_issue_nodes")
    if Counter(node_ids) != Counter(row.issue_id for row in issues):
        anomalies.append("plan_json_membership_mismatch")
    conflicts = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or node.get("node_type") != "issue":
            continue
        candidates = [row for row in issues if row.issue_id == node.get("ref_id")]
        if (
            candidates
            and ("position" in node or "lane_id" in node)
            and not any(
                ("position" not in node or node["position"] == row.display_position)
                and ("lane_id" not in node or node["lane_id"] == row.lane_id)
                for row in candidates
            )
        ):
            conflicts.append(
                {
                    "index": index,
                    "node": node,
                    "memberships": [
                        {
                            "occurrence_id": row.occurrence_id,
                            "lane_id": row.lane_id,
                            "position": row.display_position,
                            "is_checkpoint": row.is_checkpoint,
                        }
                        for row in sorted(candidates, key=lambda row: row.occurrence_id)
                    ],
                }
            )
    if conflicts:
        anomalies.append("plan_json_membership_position_conflict")
    declared = plan.lanes_json
    declared_ids = (
        {
            lane["id"]
            for lane in declared
            if isinstance(lane, dict) and isinstance(lane.get("id"), str)
        }
        if isinstance(declared, list)
        else set()
    )
    empty_lanes = sorted(declared_ids - {row.lane_id for row in issues})
    if empty_lanes:
        anomalies.append("declared_lanes_without_memberships")
    return {
        "plan_lanes": declared,
        "declared_lanes_without_memberships": empty_lanes,
        "plan_json_position_conflicts": conflicts,
        "plan_nodes": raw_nodes,
        "plan_json_optional_or_skipped_evidence": reader_evidence,
        "malformed_plan_nodes": malformed_nodes,
        "duplicate_plan_issue_node_ids": duplicate_ids,
        "anomalies": anomalies,
    }


async def load_snapshot(db: AsyncSession, user_id: int) -> Snapshot:
    """Read a user's lists and plans without writing or loading other users' content."""
    lists = (await db.scalars(select(CustomCBLList).where(CustomCBLList.user_id == user_id))).all()
    plans = (
        await db.scalars(select(ContinuityPlan).where(ContinuityPlan.user_id == user_id))
    ).all()
    list_ids = [row.id for row in lists]
    plan_ids = [row.id for row in plans]
    entries = (
        (await db.scalars(select(CustomCBLEntry).where(CustomCBLEntry.list_id.in_(list_ids)))).all()
        if list_ids
        else []
    )
    memberships = (
        (
            await db.scalars(select(ReadingPlanIssue).where(ReadingPlanIssue.plan_id.in_(plan_ids)))
        ).all()
        if plan_ids
        else []
    )
    sources = (
        (
            await db.scalars(
                select(ReadingPlanSource).where(ReadingPlanSource.plan_id.in_(plan_ids))
            )
        ).all()
        if plan_ids
        else []
    )
    placements = (
        (
            await db.scalars(
                select(ReadingPlanSourcePlacement).where(
                    ReadingPlanSourcePlacement.plan_id.in_(plan_ids)
                )
            )
        ).all()
        if plan_ids
        else []
    )
    return Snapshot(lists, entries, plans, memberships, sources, placements)


def reconcile(snapshot: Snapshot, user_id: int) -> dict[str, object]:
    """Report every explicit pair and every unpaired project without choosing authority."""
    entries_by_list: dict[int, list[CustomCBLEntry]] = defaultdict(list)
    issues_by_plan: dict[int, list[ReadingPlanIssue]] = defaultdict(list)
    sources_by_plan: dict[int, list[ReadingPlanSource]] = defaultdict(list)
    placements_by_plan: dict[int, list[ReadingPlanSourcePlacement]] = defaultdict(list)
    for row in snapshot.entries:
        entries_by_list[row.list_id].append(row)
    for row in snapshot.memberships:
        issues_by_plan[row.plan_id].append(row)
    for row in snapshot.sources:
        sources_by_plan[row.plan_id].append(row)
    for row in snapshot.placements:
        placements_by_plan[row.plan_id].append(row)
    lists = {row.id: row for row in snapshot.lists}
    owned_list_ids = set(lists)
    plans = {row.id: row for row in snapshot.plans}
    links: dict[int, set[int]] = defaultdict(set)
    lists_by_plan: dict[int, set[int]] = defaultdict(set)
    for source in snapshot.sources:
        if source.custom_cbl_list_id in lists:
            links[source.custom_cbl_list_id].add(source.plan_id)
            lists_by_plan[source.plan_id].add(source.custom_cbl_list_id)
    reports: list[dict[str, object]] = []
    paired_plans: set[int] = set()
    for list_id, custom_list in sorted(lists.items()):
        left = sorted(entries_by_list[list_id], key=lambda row: (row.position, row.id))
        pair_ids = sorted(links[list_id])
        if not pair_ids:
            reports.append(
                {
                    "list_id": list_id,
                    "list_name": custom_list.name,
                    "list_mode": custom_list.mode,
                    "status": "unpaired_list",
                    "list_count": len(left),
                    "entries": [_entry_evidence(row) for row in left],
                    "anomalies": ["unclassified_list_checkpoint_evidence"]
                    if any(row.is_checkpoint or row.checkpoint_target_issue_ids for row in left)
                    else [],
                    "resolution": "unresolved",
                }
            )
            continue
        for plan_id in pair_ids:
            paired_plans.add(plan_id)
            plan = plans[plan_id]
            right = sorted(
                issues_by_plan[plan_id],
                key=lambda row: (row.lane_id, row.display_position, row.occurrence_id),
            )
            if len(lists_by_plan[plan_id]) > 1 or len(pair_ids) > 1:
                link_anomalies = []
                if len(lists_by_plan[plan_id]) > 1:
                    link_anomalies.append("plan_linked_to_multiple_lists")
                if len(pair_ids) > 1:
                    link_anomalies.append("list_linked_to_multiple_plans")
                node_evidence = _plan_node_evidence(plan, right)
                reports.append(
                    {
                        "list_id": list_id,
                        "list_name": custom_list.name,
                        "list_mode": custom_list.mode,
                        "plan_id": plan_id,
                        "plan_name": plan.name,
                        "status": "ambiguous_link",
                        "resolution": "unresolved",
                        "list_count": len(left),
                        "plan_count": len(right),
                        "linked_list_ids": sorted(lists_by_plan[plan_id]),
                        "linked_plan_ids": pair_ids,
                        "list_entries": [_entry_evidence(row) for row in left],
                        "plan_issues": [
                            {
                                "issue_id": row.issue_id,
                                "occurrence_id": row.occurrence_id,
                                "lane_id": row.lane_id,
                                "position": row.display_position,
                                "is_checkpoint": row.is_checkpoint,
                                "reader_optional": row.reader_optional,
                                "reader_role": row.reader_role,
                                "source_metadata": row.source_metadata_json,
                            }
                            for row in right
                        ],
                        "sources": [
                            _source_evidence(row, owned_list_ids)
                            for row in sorted(sources_by_plan[plan_id], key=lambda row: row.id)
                        ],
                        "source_placements": [
                            {
                                "occurrence_id": row.occurrence_id,
                                "source_id": row.plan_source_id,
                                "source_position": row.source_position,
                            }
                            for row in sorted(
                                placements_by_plan[plan_id],
                                key=lambda row: (
                                    row.occurrence_id,
                                    row.plan_source_id,
                                    -1 if row.source_position is None else row.source_position,
                                    row.id,
                                ),
                            )
                        ],
                        "plan_json_optional_or_skipped_evidence": node_evidence[
                            "plan_json_optional_or_skipped_evidence"
                        ],
                        "plan_nodes": node_evidence["plan_nodes"],
                        "plan_lanes": node_evidence["plan_lanes"],
                        "declared_lanes_without_memberships": node_evidence[
                            "declared_lanes_without_memberships"
                        ],
                        "plan_json_position_conflicts": node_evidence[
                            "plan_json_position_conflicts"
                        ],
                        "malformed_plan_nodes": node_evidence["malformed_plan_nodes"],
                        "duplicate_plan_issue_node_ids": node_evidence[
                            "duplicate_plan_issue_node_ids"
                        ],
                        "anomalies": link_anomalies + node_evidence["anomalies"],
                    }
                )
                continue
            left_positions = {row.issue_id: row.position for row in left}
            left_ids = set(left_positions)
            right_ids = {row.issue_id for row in right}
            common = left_ids & right_ids
            list_order = [row.issue_id for row in left if row.issue_id in common]
            lanes = sorted({row.lane_id for row in right})
            lane_orders = []
            for lane in lanes:
                lane_ids = {row.issue_id for row in right if row.lane_id == lane}
                lane_list_order = [row.issue_id for row in left if row.issue_id in lane_ids]
                lane_plan_order = [
                    row.issue_id for row in right if row.lane_id == lane and row.issue_id in common
                ]
                full_plan_order = [row.issue_id for row in right if row.lane_id == lane]
                lane_orders.append(
                    {
                        "lane_id": lane,
                        "list_order": lane_list_order,
                        "plan_order": lane_plan_order,
                        "full_plan_order": full_plan_order,
                        "order_conflict": lane_list_order != lane_plan_order,
                    }
                )
            plan_order = lane_orders[0]["plan_order"] if len(lanes) == 1 else None
            order_conflict = lane_orders[0]["order_conflict"] if len(lanes) == 1 else None
            source_evidence = [
                _source_evidence(row, owned_list_ids)
                for row in sorted(sources_by_plan[plan_id], key=lambda row: row.id)
            ]
            placement_evidence = [
                {
                    "occurrence_id": row.occurrence_id,
                    "source_id": row.plan_source_id,
                    "source_position": row.source_position,
                }
                for row in sorted(
                    placements_by_plan[plan_id],
                    key=lambda row: (
                        row.occurrence_id,
                        row.plan_source_id,
                        -1 if row.source_position is None else row.source_position,
                        row.id,
                    ),
                )
            ]
            anomalies: list[str] = []
            duplicate_list_ids = sorted(
                issue_id
                for issue_id, count in Counter(row.issue_id for row in left).items()
                if count > 1
            )
            if duplicate_list_ids:
                anomalies.append("duplicate_list_membership_issues")
            if len(lanes) > 1:
                anomalies.append("extra_lanes_order_unresolved")
            if any(source["foreign_or_missing_list_link"] for source in source_evidence):
                anomalies.append("foreign_or_missing_list_link")
            if any(row.is_checkpoint or row.checkpoint_target_issue_ids for row in left):
                anomalies.append("unclassified_list_checkpoint_evidence")
            if order_conflict:
                anomalies.append("shared_issue_order_conflict")
            if left_ids != right_ids:
                anomalies.append("membership_difference")
            duplicate_membership_ids = sorted(
                issue_id
                for issue_id, count in Counter(row.issue_id for row in right).items()
                if count > 1
            )
            if duplicate_membership_ids:
                anomalies.append("duplicate_plan_membership_issues")
            position_conflicts = [
                {
                    "issue_id": plan_row.issue_id,
                    "list_position": list_row.position,
                    "plan_position": plan_row.display_position,
                    "plan_lane_id": plan_row.lane_id,
                }
                for plan_row in right
                for list_row in left
                if plan_row.issue_id == list_row.issue_id
                and list_row.position != plan_row.display_position
            ]
            if position_conflicts:
                anomalies.append("shared_issue_position_conflict")
            node_evidence = _plan_node_evidence(plan, right)
            anomalies.extend(node_evidence["anomalies"])
            metadata_evidence = [
                {
                    "issue_id": row.issue_id,
                    "occurrence_id": row.occurrence_id,
                    "lane_id": row.lane_id,
                    "reader_optional": row.reader_optional,
                    "reader_role": row.reader_role,
                    "source_metadata": row.source_metadata_json,
                }
                for row in right
                if row.reader_optional is not None
                or row.reader_role is not None
                or row.source_metadata_json
            ]
            if metadata_evidence or any(source["metadata"] for source in source_evidence):
                anomalies.append("unclassified_skip_exclusion_evidence")
            reports.append(
                {
                    "list_id": list_id,
                    "list_name": custom_list.name,
                    "list_mode": custom_list.mode,
                    "plan_id": plan_id,
                    "plan_name": plan.name,
                    "status": "paired",
                    "list_count": len(left),
                    "plan_count": len(right),
                    "plan_issues": [
                        {
                            "issue_id": row.issue_id,
                            "occurrence_id": row.occurrence_id,
                            "lane_id": row.lane_id,
                            "position": row.display_position,
                            "is_checkpoint": row.is_checkpoint,
                            "reader_optional": row.reader_optional,
                            "reader_role": row.reader_role,
                            "source_metadata": row.source_metadata_json,
                        }
                        for row in right
                    ],
                    "list_entries": [_entry_evidence(row) for row in left],
                    "list_only": [
                        _entry_evidence(row) for row in left if row.issue_id not in right_ids
                    ],
                    "plan_only": [
                        {
                            "occurrence_id": row.occurrence_id,
                            "issue_id": row.issue_id,
                            "lane_id": row.lane_id,
                            "position": row.display_position,
                            "is_checkpoint": row.is_checkpoint,
                            "reader_optional": row.reader_optional,
                            "reader_role": row.reader_role,
                            "source_metadata": row.source_metadata_json,
                        }
                        for row in right
                        if row.issue_id not in left_ids
                    ],
                    "shared_order_list": list_order,
                    "shared_order_plan": plan_order,
                    "order_conflict": order_conflict,
                    "lane_orders": lane_orders,
                    "plan_json_optional_or_skipped_evidence": node_evidence[
                        "plan_json_optional_or_skipped_evidence"
                    ],
                    "plan_nodes": node_evidence["plan_nodes"],
                    "plan_lanes": node_evidence["plan_lanes"],
                    "declared_lanes_without_memberships": node_evidence[
                        "declared_lanes_without_memberships"
                    ],
                    "plan_json_position_conflicts": node_evidence["plan_json_position_conflicts"],
                    "malformed_plan_nodes": node_evidence["malformed_plan_nodes"],
                    "duplicate_list_membership_issue_ids": duplicate_list_ids,
                    "duplicate_list_entries": [
                        _entry_evidence(row) for row in left if row.issue_id in duplicate_list_ids
                    ],
                    "duplicate_plan_issue_node_ids": node_evidence["duplicate_plan_issue_node_ids"],
                    "duplicate_plan_membership_issue_ids": duplicate_membership_ids,
                    "position_conflicts": position_conflicts,
                    "list_checkpoints": [
                        {
                            "issue_id": row.issue_id,
                            "position": row.position,
                            "target_issue_ids": row.checkpoint_target_issue_ids,
                        }
                        for row in left
                        if row.is_checkpoint or row.checkpoint_target_issue_ids
                    ],
                    "plan_optional_or_skipped_evidence": metadata_evidence,
                    "lanes": lanes,
                    "sources": source_evidence,
                    "source_placements": placement_evidence,
                    "anomalies": anomalies,
                    "resolution": "unresolved" if anomalies else "aligned",
                }
            )
    unpaired_plans = []
    for plan_id, plan in sorted(plans.items()):
        if plan_id in paired_plans:
            continue
        issues = sorted(
            issues_by_plan[plan_id],
            key=lambda row: (row.lane_id, row.display_position, row.occurrence_id),
        )
        sources = [
            _source_evidence(row, owned_list_ids)
            for row in sorted(sources_by_plan[plan_id], key=lambda row: row.id)
        ]
        nodes = _plan_node_evidence(plan, issues)
        anomalies = list(nodes["anomalies"])
        if any(source["foreign_or_missing_list_link"] for source in sources):
            anomalies.append("foreign_or_missing_list_link")
        evidence = [
            {
                "issue_id": row.issue_id,
                "occurrence_id": row.occurrence_id,
                "lane_id": row.lane_id,
                "position": row.display_position,
                "is_checkpoint": row.is_checkpoint,
                "reader_optional": row.reader_optional,
                "reader_role": row.reader_role,
                "source_metadata": row.source_metadata_json,
            }
            for row in issues
        ]
        metadata = [
            row
            for row in evidence
            if row["reader_optional"] is not None
            or row["reader_role"] is not None
            or row["source_metadata"]
        ]
        if metadata or any(source["metadata"] for source in sources):
            anomalies.append("unclassified_skip_exclusion_evidence")
        lanes = sorted({row.lane_id for row in issues})
        if len(lanes) > 1:
            anomalies.append("extra_lanes_order_unresolved")
        duplicates = sorted(
            issue_id
            for issue_id, count in Counter(row.issue_id for row in issues).items()
            if count > 1
        )
        if duplicates:
            anomalies.append("duplicate_plan_membership_issues")
        unpaired_plans.append(
            {
                "plan_id": plan_id,
                "plan_name": plan.name,
                "plan_count": len(issues),
                "issues": evidence,
                "sources": sources,
                "source_placements": [
                    {
                        "occurrence_id": row.occurrence_id,
                        "source_id": row.plan_source_id,
                        "source_position": row.source_position,
                    }
                    for row in sorted(
                        placements_by_plan[plan_id],
                        key=lambda row: (
                            row.occurrence_id,
                            row.plan_source_id,
                            -1 if row.source_position is None else row.source_position,
                            row.id,
                        ),
                    )
                ],
                "plan_json_optional_or_skipped_evidence": nodes[
                    "plan_json_optional_or_skipped_evidence"
                ],
                "plan_nodes": nodes["plan_nodes"],
                "plan_lanes": nodes["plan_lanes"],
                "declared_lanes_without_memberships": nodes["declared_lanes_without_memberships"],
                "plan_json_position_conflicts": nodes["plan_json_position_conflicts"],
                "malformed_plan_nodes": nodes["malformed_plan_nodes"],
                "duplicate_plan_issue_node_ids": nodes["duplicate_plan_issue_node_ids"],
                "duplicate_plan_membership_issue_ids": duplicates,
                "plan_optional_or_skipped_evidence": metadata,
                "lanes": lanes,
                "anomalies": anomalies,
                "resolution": "unresolved",
            }
        )
    return {
        "user_id": user_id,
        "lists": reports,
        "unpaired_plans": unpaired_plans,
        "summary": {
            "list_count": len(lists),
            "plan_count": len(plans),
            "paired_reports": sum(row["status"] == "paired" for row in reports),
            "ambiguous_link_reports": sum(row["status"] == "ambiguous_link" for row in reports),
            "unpaired_list_count": sum(row["status"] == "unpaired_list" for row in reports),
            "unpaired_plan_count": len(unpaired_plans),
            "list_only_count": sum(
                len(row.get("list_only", row.get("entries", []))) for row in reports
            ),
            "plan_only_count": sum(len(row.get("plan_only", [])) for row in reports)
            + sum(len(row["issues"]) for row in unpaired_plans),
        },
    }


async def report(database_url: str, user_id: int) -> dict[str, object]:
    """Capture a consistent read-only database snapshot and reconcile it."""
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("An explicit postgresql+asyncpg URL is required")
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as db:
            async with db.begin():
                await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                snapshot = await load_snapshot(db, user_id)
                return reconcile(snapshot, user_id)
    finally:
        await engine.dispose()


def main() -> None:
    """Print deterministic JSON or a readable per-project census."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(report(args.database_url, args.user_id))
    if args.summary:
        print(json.dumps(result["summary"], sort_keys=True, indent=2))
        for row in result["lists"]:
            print(
                f"List {row['list_id']} {row['list_name']}: {row['status']}; "
                f"{row['list_count']} entries; anomalies={row.get('anomalies', [])}"
            )
            for key in (
                "list_only",
                "plan_only",
                "position_conflicts",
                "lane_orders",
                "plan_lanes",
                "declared_lanes_without_memberships",
                "plan_json_position_conflicts",
                "duplicate_list_entries",
                "list_checkpoints",
                "plan_optional_or_skipped_evidence",
                "plan_json_optional_or_skipped_evidence",
                "sources",
                "source_placements",
                "entries",
                "list_entries",
                "plan_issues",
                "linked_list_ids",
                "linked_plan_ids",
            ):
                if row.get(key):
                    print(f"  {key}: {json.dumps(row[key], sort_keys=True)}")
        for row in result["unpaired_plans"]:
            print(f"Plan {row['plan_id']} {row['plan_name']}: unpaired; {row['plan_count']} issues")
            for key in (
                "issues",
                "sources",
                "source_placements",
                "plan_nodes",
                "malformed_plan_nodes",
                "plan_optional_or_skipped_evidence",
                "plan_json_optional_or_skipped_evidence",
                "anomalies",
            ):
                if row.get(key):
                    print(f"  {key}: {json.dumps(row[key], sort_keys=True)}")
    else:
        print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
