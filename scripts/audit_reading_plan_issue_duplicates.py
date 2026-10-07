#!/usr/bin/env python3
"""Audit (and deterministically reconcile) duplicate canonical-issue memberships in Reading Plans (#3037).

Canonical membership invariant: within one Reading Plan a canonical issue may
appear at most once. This script is the repeatable audit/report command for
that invariant.

- Default (audit) mode is read-only: it reports every plan whose ``nodes_json``
  holds two or more issue-type nodes with the same ``ref_id``, and every
  ``reading_plan_issues`` row group violating ``uq_reading_plan_issue_once_per_plan``.
  Exits 0 when clean, 1 when duplicates are found.
- ``--apply`` deterministically reconciles unambiguous duplicates: for each
  repeated issue, the occurrence with the smallest (lane order, position) is
  kept and exact-duplicate later occurrences (identical modulo node id and
  position) are dropped. Occurrences that disagree on semantic fields
  (lane, label, reader role/optional flag, checkpoint) are NOT guessed at:
  they are reported as blockers and left untouched.

Production reconciliation is owned by #3045; this tool only proves the
mechanics. It never touches production unless explicitly pointed at it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.continuity_plan import ContinuityPlan  # noqa: E402
from app.models.reading_plan_membership import ReadingPlanIssue  # noqa: E402
from app.schemas.continuity_plan import ContinuityPlanNode  # noqa: E402
from app.services.reading_plan_normalization import (  # noqa: E402
    ensure_plan_issue_uniqueness,
    rebuild_plan_membership,
)

# Node fields that carry reader-visible semantics. Two occurrences of the same
# issue collapse deterministically only when these all agree (id/position are
# identity/ordering and are excluded by construction).
SEMANTIC_FIELDS = ("lane_id", "label", "reader_role", "reader_optional", "is_checkpoint")


def _issue_nodes(plan: ContinuityPlan) -> list[dict[str, Any]]:
    return [
        node
        for node in (plan.nodes_json or [])
        if isinstance(node, dict) and node.get("node_type") == "issue"
    ]


def _duplicate_groups(
    nodes: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    by_ref: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        try:
            ref_id = int(node.get("ref_id") or 0)
        except (TypeError, ValueError):
            continue
        if ref_id > 0:
            by_ref.setdefault(ref_id, []).append(node)
    return {ref_id: group for ref_id, group in by_ref.items() if len(group) > 1}


def _semantic_key(node: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(node.get(field) for field in SEMANTIC_FIELDS)


async def audit(db) -> dict[str, Any]:
    """Return a read-only duplicate-membership report across all plans."""
    plans = (await db.execute(select(ContinuityPlan).order_by(ContinuityPlan.id))).scalars().all()
    plan_reports: list[dict[str, Any]] = []
    for plan in plans:
        nodes = _issue_nodes(plan)
        dup_groups = _duplicate_groups(nodes)
        if dup_groups:
            plan_reports.append(
                {
                    "plan_id": plan.id,
                    "plan_name": plan.name,
                    "user_id": plan.user_id,
                    "duplicate_issues": [
                        {
                            "issue_id": ref_id,
                            "occurrences": [
                                {
                                    "node_id": node.get("id"),
                                    "lane_id": node.get("lane_id"),
                                    "position": node.get("position"),
                                    **{f: node.get(f) for f in SEMANTIC_FIELDS if f != "lane_id"},
                                }
                                for node in group
                            ],
                        }
                        for ref_id, group in sorted(dup_groups.items())
                    ],
                }
            )
    # Relational backstop: rows violating the once-per-plan unique constraint.
    dup_rows = (
        await db.execute(
            select(
                ReadingPlanIssue.plan_id,
                ReadingPlanIssue.issue_id,
                func.count().label("occurrences"),
            )
            .group_by(ReadingPlanIssue.plan_id, ReadingPlanIssue.issue_id)
            .having(func.count() > 1)
            .order_by(ReadingPlanIssue.plan_id, ReadingPlanIssue.issue_id)
        )
    ).all()
    return {
        "plans_with_duplicate_nodes": plan_reports,
        "duplicate_membership_rows": [
            {"plan_id": plan_id, "issue_id": issue_id, "occurrences": count}
            for plan_id, issue_id, count in dup_rows
        ],
    }


def _collapse_plan_nodes(plan: ContinuityPlan) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministically drop unambiguous duplicate issue nodes.

    Returns (kept_nodes, collapsed, blockers). ``collapsed`` entries name the
    kept and dropped node ids; ``blockers`` name duplicate groups whose
    occurrences disagree on semantic fields and must not be guessed at.
    """
    nodes = list(plan.nodes_json or [])
    lane_order = {lane.get("id"): idx for idx, lane in enumerate(plan.lanes_json or [])}
    dup_groups = _duplicate_groups(_issue_nodes(plan))
    drop_ids: set[str] = set()
    collapsed: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for ref_id, group in sorted(dup_groups.items()):
        keys = {_semantic_key(node) for node in group}
        if len(keys) != 1:
            blockers.append(
                {
                    "plan_id": plan.id,
                    "issue_id": ref_id,
                    "reason": "occurrences disagree on semantic fields",
                    "node_ids": [node.get("id") for node in group],
                }
            )
            continue
        ordered = sorted(
            group,
            key=lambda n: (lane_order.get(n.get("lane_id"), 0), int(n.get("position") or 0)),
        )
        keep, *rest = ordered
        for node in rest:
            drop_ids.add(str(node.get("id")))
        collapsed.append(
            {
                "plan_id": plan.id,
                "issue_id": ref_id,
                "kept_node_id": keep.get("id"),
                "dropped_node_ids": [node.get("id") for node in rest],
            }
        )

    kept = [node for node in nodes if str(node.get("id")) not in drop_ids]
    # Renumber positions per lane contiguously so ordering stays valid.
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for node in kept:
        by_lane.setdefault(str(node.get("lane_id") or ""), []).append(node)
    renumbered: list[dict[str, Any]] = []
    for lane_nodes in by_lane.values():
        lane_nodes.sort(key=lambda n: int(n.get("position") or 0))
        for idx, node in enumerate(lane_nodes):
            node["position"] = idx
            renumbered.append(node)
    return renumbered, collapsed, blockers


async def reconcile(db, *, plan_ids: list[int] | None = None) -> dict[str, Any]:
    """Deterministically collapse unambiguous duplicates; report blockers."""
    query = select(ContinuityPlan).order_by(ContinuityPlan.id)
    if plan_ids:
        query = query.where(ContinuityPlan.id.in_(plan_ids))
    plans = (await db.execute(query)).scalars().all()
    all_collapsed: list[dict[str, Any]] = []
    all_blockers: list[dict[str, Any]] = []
    plans_fixed = 0
    for plan in plans:
        kept, collapsed, blockers = _collapse_plan_nodes(plan)
        all_collapsed.extend(collapsed)
        all_blockers.extend(blockers)
        if not collapsed:
            continue
        plan.nodes_json = kept
        node_models = [ContinuityPlanNode.model_validate(node) for node in kept]
        # Service gate re-validates the deduped set before anything persists.
        ensure_plan_issue_uniqueness(node_models)
        await rebuild_plan_membership(db, plan_id=plan.id, nodes=node_models)
        plans_fixed += 1
    await db.commit()
    return {
        "plans_fixed": plans_fixed,
        "collapsed": all_collapsed,
        "blockers": all_blockers,
    }


async def main_async(args: argparse.Namespace) -> int:
    """Run the audit or reconciliation and return the process exit code."""
    async with AsyncSessionLocal() as db:
        if args.apply:
            result = await reconcile(db, plan_ids=args.plan_id)
            print(json.dumps(result, indent=2, default=str))
            if result["blockers"]:
                print("blockers remain: resolve manually", file=sys.stderr)
                return 2
            return 0
        report = await audit(db)
        print(json.dumps(report, indent=2, default=str))
        dirty = bool(report["plans_with_duplicate_nodes"] or report["duplicate_membership_rows"])
        return 1 if dirty else 0


def main() -> int:
    """Parse arguments and run the audit or reconciliation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Deterministically collapse unambiguous duplicates (default: read-only audit).",
    )
    parser.add_argument(
        "--plan-id",
        action="append",
        type=int,
        default=None,
        help="Restrict --apply to specific plan ids (repeatable).",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
