"""Read-only Step 14 production dependency classification audit.

Produces a machine-readable ledger for every legacy Dependency owned by a user.
Safety: this module performs SELECTs only and never commits or refreshes blocked state.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from sqlalchemy import or_, select

from app.database import AsyncSessionLocal
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.thread import Thread


@dataclass(frozen=True)
class LedgerRow:
    dependency_id: int
    source_issue_id: int | None
    source_thread_id: int | None
    target_issue_id: int | None
    target_thread_id: int | None
    note: str | None
    linked_rule_ids: tuple[int, ...]
    legacy_reading_order_ids: tuple[int, ...]
    plan_ids: tuple[int, ...]
    classification: str
    reason: str
    human_review_required: bool


def classify(note: str | None, linked_rule_ids: tuple[int, ...]) -> tuple[str, str, bool]:
    """Conservative first-pass classifier. Ambiguity is never silently dropped."""
    if note and note.startswith("cbl-order:source:"):
        return (
            "reading_plan_order",
            "source-generated CBL ordering compatibility edge; exact source/endpoints remain in ledger",
            False,
        )
    if linked_rule_ids:
        return (
            "needs_review",
            "legacy edge is mirrored by canonical continuity rule; linkage alone does not prove disposition",
            True,
        )
    return (
        "needs_review",
        "no invariant proves this edge is pure reading order or an independent prerequisite",
        True,
    )


async def audit(user_id: int) -> dict[str, object]:
    async with AsyncSessionLocal() as db:
        thread_ids = set((await db.scalars(select(Thread.id).where(Thread.user_id == user_id))).all())
        issue_ids = set((await db.scalars(select(Issue.id).where(Issue.thread_id.in_(thread_ids)))).all())
        deps = (await db.scalars(select(Dependency).where(or_(Dependency.source_thread_id.in_(thread_ids), Dependency.target_thread_id.in_(thread_ids), Dependency.source_issue_id.in_(issue_ids), Dependency.target_issue_id.in_(issue_ids))).order_by(Dependency.id))).all()
        rules = (await db.scalars(select(ContinuityRule).where(ContinuityRule.user_id == user_id, ContinuityRule.legacy_dependency_id.is_not(None)))).all()
        rule_map: dict[int, list[int]] = {}
        for rule in rules:
            rule_map.setdefault(rule.legacy_dependency_id, []).append(rule.id)
        orders = (await db.scalars(select(ReadingOrder).where(ReadingOrder.user_id == user_id))).all()
        order_ids = [order.id for order in orders]
        order_items = (await db.scalars(select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id.in_(order_ids)))).all() if order_ids else []
        thread_orders: dict[int, set[int]] = {}
        for item in order_items:
            thread_orders.setdefault(item.thread_id, set()).add(item.reading_order_id)
        plans = (await db.scalars(select(ContinuityPlan).where(ContinuityPlan.user_id == user_id))).all()
        rows: list[LedgerRow] = []
        for dep in deps:
            linked = tuple(sorted(rule_map.get(dep.id, [])))
            legacy_orders = tuple(sorted(thread_orders.get(dep.source_thread_id, set()) | thread_orders.get(dep.target_thread_id, set())))
            endpoint_ids = {value for value in (dep.source_issue_id, dep.target_issue_id, dep.source_thread_id, dep.target_thread_id) if value is not None}
            plan_ids = tuple(sorted(plan.id for plan in plans if any(isinstance(node, dict) and node.get("ref_id") in endpoint_ids for node in (plan.nodes_json or []))))
            classification, reason, review = classify(dep.note, linked)
            rows.append(LedgerRow(dep.id, dep.source_issue_id, dep.source_thread_id, dep.target_issue_id, dep.target_thread_id, dep.note, linked, legacy_orders, plan_ids, classification, reason, review))
        payload_rows = [asdict(row) for row in rows]
        snapshot = sha256(json.dumps(payload_rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        counts = Counter(row.classification for row in rows)
        return {"user_id": user_id, "snapshot_token": snapshot, "total": len(rows), "classification_counts": dict(sorted(counts.items())), "rows": payload_rows}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = await audit(args.user_id)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
