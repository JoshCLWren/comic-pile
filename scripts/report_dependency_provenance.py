"""Read-only Option E dependency provenance and all-status frontier census.

No evidence class authorizes retirement. Unknown or conflicting evidence stays D.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread
from app.models.continuity_rule import ContinuityRule
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.continuity_plan import ContinuityPlan
from app.services.canonical_constraint_compiler import rule_edge_pairs

# Stable evidence cohort from #3588, not a filter on current status or expected counts.
KNOWN_FRONTIER_THREAD_IDS = (
    18849, 18852, 18854, 18876, 18877, 18879, 18881, 18882, 18883, 18884, 18885, 18886,
    18901, 18904, 18905, 18906, 18909, 18915, 18917, 18919, 18924, 18989, 18990, 18991,
)


@dataclass(frozen=True)
class Snapshot:
    """Owned rows captured without touching reader state."""

    threads: Sequence[Thread]
    issues: Sequence[Issue]
    dependencies: Sequence[Dependency]
    rules: Sequence[ContinuityRule]
    entries: Sequence[CustomCBLEntry]
    plan_dependencies: Sequence[ReadingPlanDependency]


async def load_snapshot(db: AsyncSession, user_id: int) -> Snapshot:
    """Load endpoints owned by the reader and edges touching either endpoint.

    Args:
        db: Read-only transaction with autoflush disabled.
        user_id: Reader whose evidence is reported.

    Returns:
        Snapshot including all Thread statuses and unresolved foreign endpoints.
    """
    owned_issues = select(Issue.id).join(Thread, Issue.thread_id == Thread.id).where(
        Thread.user_id == user_id
    )
    threads = (await db.scalars(select(Thread).where(Thread.user_id == user_id))).all()
    issues = (await db.scalars(select(Issue).where(Issue.id.in_(owned_issues)))).all()
    dependencies = (await db.scalars(select(Dependency).where(or_(
        Dependency.source_issue_id.in_(owned_issues),
        Dependency.target_issue_id.in_(owned_issues),
    )))).all()
    rules = (await db.scalars(select(ContinuityRule).where(
        ContinuityRule.user_id == user_id
    ))).all()
    entries = (await db.scalars(select(CustomCBLEntry).join(CustomCBLList).where(
        CustomCBLList.user_id == user_id
    ))).all()
    plan_dependencies = (await db.scalars(select(ReadingPlanDependency).join(ContinuityPlan).where(
        ContinuityPlan.user_id == user_id
    ))).all()
    return Snapshot(threads, issues, dependencies, rules, entries, plan_dependencies)


def _rule_pairs(rule: ContinuityRule) -> list[tuple[int, int]]:
    """Keep malformed historical convergence metadata from aborting the census."""
    try:
        return rule_edge_pairs(rule)
    except (ValueError, TypeError, KeyError, OverflowError):
        return []


def census(snapshot: Snapshot, user_id: int) -> dict[str, object]:
    """Describe provenance and frontier impact deterministically without deciding intent.

    Args:
        snapshot: User-scoped stored evidence.
        user_id: Reader identifier for report attribution.

    Returns:
        JSON-compatible report; evidence classes are observational, never approval.
    """
    threads = {row.id: row for row in snapshot.threads if row.user_id == user_id}
    issues = {row.id: row for row in snapshot.issues if row.thread_id in threads}
    by_thread: dict[int, list[Issue]] = defaultdict(list)
    lists: dict[int, set[int]] = defaultdict(set)
    for issue in issues.values():
        by_thread[issue.thread_id].append(issue)
    for entry in snapshot.entries:
        lists[entry.issue_id].add(entry.list_id)
    frontiers = []
    derived: dict[int, int | None] = {}
    for thread_id, thread in sorted(threads.items()):
        ordered = sorted(by_thread[thread_id], key=lambda row: (row.position, row.id))
        unread = [row.id for row in ordered if row.status != "read"]
        first = unread[0] if unread else None
        derived[thread_id] = first
        pointer = thread.next_unread_issue_id
        pointed = issues.get(pointer) if pointer is not None else None
        frontiers.append({
            "thread_id": thread_id, "title": thread.title, "status": thread.status,
            "known_3588_thread": thread_id in KNOWN_FRONTIER_THREAD_IDS,
            "stored_next_issue_id": pointer, "derived_next_issue_id": first,
            "pointer_mismatch": pointer != first,
            "stored_pointer_in_thread": None if pointer is None else (
                pointed is not None and pointed.thread_id == thread_id
            ),
            "stored_pointer_owned_thread_id": pointed.thread_id if pointed else None,
            "issue_count": len(ordered), "unread_count": len(unread),
            "stored_total_issues": thread.total_issues,
            "stored_issues_remaining": thread.issues_remaining,
            "stored_is_blocked": thread.is_blocked,
        })
    rules_by_pair: dict[tuple[int, int], list[ContinuityRule]] = defaultdict(list)
    rules_by_legacy: dict[int, list[ContinuityRule]] = defaultdict(list)
    for rule in snapshot.rules:
        if rule.user_id != user_id:
            continue
        for pair in _rule_pairs(rule):
            rules_by_pair[pair].append(rule)
        if rule.legacy_dependency_id is not None:
            rules_by_legacy[rule.legacy_dependency_id].append(rule)
    plans_by_dependency: dict[int, set[int]] = defaultdict(set)
    for row in snapshot.plan_dependencies:
        plans_by_dependency[row.dependency_id].add(row.plan_id)
    rules_by_id = {r.id: r for r in snapshot.rules if r.user_id == user_id}
    edges = []
    inert = 0
    for edge in sorted(snapshot.dependencies, key=lambda row: row.id):
        if edge.note is not None and edge.note.startswith("cbl-order:"):
            inert += 1
            continue
        source = issues.get(edge.source_issue_id)
        target = issues.get(edge.target_issue_id)
        pair = (edge.source_issue_id, edge.target_issue_id)
        related = {r.id: r for r in rules_by_pair[pair] + rules_by_legacy[edge.id]}
        referenced_rule_id = None
        malformed_rule_note = False
        for prefix in ("canonical:rule:", "canonical:rule-backfill:"):
            if edge.note and edge.note.startswith(prefix):
                suffix = edge.note.removeprefix(prefix)
                if not suffix.isdecimal():
                    malformed_rule_note = True
                if suffix.isdecimal():
                    referenced_rule_id = int(suffix)
                    if referenced_rule_id in rules_by_id:
                        related[referenced_rule_id] = rules_by_id[referenced_rule_id]
        evidence = [{
            "rule_id": rule.id, "note": rule.note,
            "legacy_dependency_id": rule.legacy_dependency_id,
            "satisfaction_type": rule.satisfaction_type,
            "source_type": rule.source_type, "source_id": rule.source_id,
            "target_type": rule.target_type, "target_id": rule.target_id,
            "checkpoint_issue_id": rule.checkpoint_issue_id,
            "matches_compiled_pair": pair in _rule_pairs(rule),
            "convergence_targets": rule.convergence_targets,
        } for rule in sorted(related.values(), key=lambda row: row.id)]
        # Authorship cannot be proved from an arbitrary note or a rule's existence.
        # Even recognized compiler notes can overwrite older intent on the same pair.
        missing_rule = referenced_rule_id is not None and referenced_rule_id not in related
        # Matching checkpoint evidence cannot establish who authored this dependency.
        classification = "D"
        same_thread = source.thread_id == target.thread_id if source and target else None
        source_lists, target_lists = lists[edge.source_issue_id], lists[edge.target_issue_id]
        active = target is not None and threads[target.thread_id].status == "active"
        unsatisfied = source is not None and source.status != "read"
        edges.append({
            "dependency_id": edge.id, "source_issue_id": edge.source_issue_id,
            "target_issue_id": edge.target_issue_id, "note": edge.note,
            "source_thread_id": source.thread_id if source else None,
            "target_thread_id": target.thread_id if target else None,
            "source_status": source.status if source else None,
            "target_status": target.status if target else None,
            "unresolved_endpoint": source is None or target is None,
            "same_thread": same_thread,
            "source_list_ids": sorted(source_lists), "target_list_ids": sorted(target_lists),
            "cross_list": bool(source_lists and target_lists and source_lists.isdisjoint(
                target_lists
            )),
            "evidence_class": classification,
            "classification_reason": "single_matching_checkpoint_rule" if classification == "B"
            else "unknown_authorship_or_conflicting_provenance",
            "rule_evidence": evidence,
            "note_rule_id": referenced_rule_id,
            "missing_note_rule": missing_rule or malformed_rule_note,
            "plan_ids": sorted(plans_by_dependency[edge.id]),
            "plan_evidence": [{"plan_id": p.plan_id, "explanation": p.explanation}
                for p in sorted(snapshot.plan_dependencies, key=lambda p: p.plan_id)
                if p.dependency_id == edge.id],
            "active_derived_frontier_blocker": bool(active and unsatisfied and target
                and derived[target.thread_id] == target.id),
            "active_stored_frontier_blocker": bool(active and unsatisfied and target
                and threads[target.thread_id].next_unread_issue_id == target.id),
        })
    return {
        "user_id": user_id, "read_only": True,
        "classification_policy": {
            "A": "requires reviewed reader-authorship evidence; never inferred from notes",
            "B": "requires independently verified rule origin; matching alone is insufficient",
            "C": "requires preserved generation evidence; compiler note alone is insufficient",
            "D": "unknown, overwritten or conflicting provenance; requires review",
        },
        "summary": {
            "enforced_edges": len(edges), "inert_cbl_order_edges": inert,
            "same_thread_edges": sum(e["same_thread"] is True for e in edges),
            "cross_thread_edges": sum(e["same_thread"] is False for e in edges),
            "cross_list_edges": sum(bool(e["cross_list"]) for e in edges),
            "evidence_classes": dict(sorted(Counter(e["evidence_class"] for e in edges).items())),
            "active_derived_frontier_blockers": sum(
                bool(e["active_derived_frontier_blocker"]) for e in edges
            ),
            "active_stored_frontier_blockers": sum(
                bool(e["active_stored_frontier_blocker"]) for e in edges
            ),
            "frontier_mismatches": sum(bool(f["pointer_mismatch"]) for f in frontiers),
        },
        "edges": edges, "frontiers": frontiers,
        "known_3588_threads": [next(
            (f for f in frontiers if f["thread_id"] == thread_id),
            {"thread_id": thread_id, "missing_or_deleted": True},
        ) for thread_id in KNOWN_FRONTIER_THREAD_IDS],
    }


async def report(database_url: str, user_id: int) -> dict[str, object]:
    """Capture a repeatable-read, database-enforced read-only report.

    Args:
        database_url: Explicit PostgreSQL asyncpg URL; no implicit production fallback.
        user_id: Reader identifier.

    Returns:
        Deterministic census from one consistent snapshot.
    """
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("An explicit postgresql+asyncpg:// URL is required")
    engine = create_async_engine(database_url, isolation_level="REPEATABLE READ")
    try:
        async with AsyncSession(engine, autoflush=False) as db, db.begin():
            await db.execute(text("SET TRANSACTION READ ONLY"))
            return census(await load_snapshot(db, user_id), user_id)
    finally:
        await engine.dispose()


def main() -> None:
    """Print the complete evidence report as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--user-id", required=True, type=int)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(report(args.database_url, args.user_id)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
