"""Migrate reader-owned Crossover reading orders into canonical Reading Plans.

Implements :issue:`3038`. Crossover reading orders are
:class:`~app.models.dependency_group.DependencyGroup` rows whose issue-level
memberships carry ``sequence_order``. That order is a competing reader-owned
order authority next to canonical Reading Plans
(:class:`~app.models.continuity_plan.ContinuityPlan`); this module moves one
group's order intent into a strict-sequential plan without touching reader
state.

The module reuses the Step 27 safety scaffolding from
:mod:`app.services.migration_shared` (frozen manifests, snapshot-token drift
protection, idempotent apply, durable receipts) and the plan compiler
(:func:`~app.services.continuity_plan_writer.replace_compiled_rules`), but it
owns Crossover-specific classification, reconciliation semantics, and product
convergence itself. It does not build a competing migration framework.

Scope boundaries (from #3038):

- Implementation, classification, dry-run tooling, and tests are factory work
  here. Actual production mutation/cutover is manual-only in #3046.
- Legacy crossover state is never deleted by this migration. Retiring the
  crossover order authority (``sequence_order``) and demoting competing
  Crossover UI are #3046 cutover scope, after production verification.
- Reader state (read status, ``read_at``, ratings, history/events, mappings)
  is never mutated; the dry-run proves it and apply re-verifies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.event import Event
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanNode,
    ContinuityPlanWrite,
)
from app.services.continuity_plan_writer import (
    plan_rule_marker,
    replace_compiled_rules,
    validate_node_ownership,
)
from app.services.migration_shared import (
    MigrationInvariantError,
    coerce_int,
    invalidate_continuity_snapshot,
    json_value,
    plan_fingerprint,
    plan_fingerprint_from_payload,
    planned_rule_descriptor,
    refresh_blocked_status,
    require_clean_snapshot,
    rules_fingerprint,
    stable_hash,
)
from comic_pile.dependencies import _get_blocked_thread_ids_uncached
from comic_pile.queue import get_roll_pool

CrossoverClassification = Literal[
    "not_reader_order",
    "already_represented",
    "safely_migratable",
    "merge_needed",
    "ambiguous",
]

#: Confirmation word for the operator CLI apply path.
CROSSOVER_MIGRATION_CONFIRMATION = "CROSSOVER-READER-ORDER"


def crossover_source_path(group_id: int) -> str:
    """Return the provenance path stamped on plan nodes migrated from a group."""
    return f"crossover/group-{group_id}"


@dataclass(frozen=True)
class CrossoverReadingOrderSpec:
    """Frozen manifest describing one Crossover reader-order migration."""

    user_id: int
    dependency_group_id: int
    plan_name: str
    expected_content_hash: str
    expected_positions: int


def _ordered_pairs(
    memberships: list[DependencyGroupMembership],
) -> list[tuple[int, int, int]]:
    """Return ``(membership_id, issue_id, sequence_order)`` sorted by order."""
    ordered = [
        (membership.id, membership.issue_id, membership.sequence_order)
        for membership in memberships
        if membership.issue_id is not None and membership.sequence_order is not None
    ]
    ordered.sort(key=lambda row: (row[2], row[0]))
    return [(mid, coerce_int(iid), coerce_int(seq)) for mid, iid, seq in ordered]


def crossover_content_hash(ordered: list[tuple[int, int, int]]) -> str:
    """Fingerprint the ordered ``(issue_id, sequence_order)`` content of a group."""
    return stable_hash([(issue_id, sequence_order) for _, issue_id, sequence_order in ordered])


async def _load_group(
    db: AsyncSession, *, user_id: int, group_id: int
) -> tuple[DependencyGroup, list[DependencyGroupMembership]]:
    """Load one group with ownership check."""
    group = await db.get(DependencyGroup, group_id)
    if group is None or group.user_id != user_id:
        raise MigrationInvariantError(f"crossover group {group_id} missing or not owned")
    memberships = list(
        (
            await db.execute(
                select(DependencyGroupMembership)
                .where(DependencyGroupMembership.group_id == group.id)
                .order_by(DependencyGroupMembership.id)
            )
        )
        .scalars()
        .all()
    )
    return group, memberships


async def _plan_issue_refs(
    db: AsyncSession, *, user_id: int
) -> list[tuple[ContinuityPlan, list[int]]]:
    """Return ``(plan, ordered issue ref ids)`` for every user plan."""
    plans = list(
        (await db.execute(select(ContinuityPlan).where(ContinuityPlan.user_id == user_id)))
        .scalars()
        .all()
    )
    result: list[tuple[ContinuityPlan, list[int]]] = []
    for plan in plans:
        nodes = sorted(plan.nodes_json or [], key=lambda n: int(n.get("position", 0)))
        refs = [
            int(node["ref_id"])
            for node in nodes
            if node.get("node_type") == "issue" and "ref_id" in node
        ]
        result.append((plan, refs))
    return result


async def classify_crossover_group(
    db: AsyncSession, *, user_id: int, group_id: int
) -> dict[str, Any]:
    """Classify one crossover group for Reading Plan migration.

    Categories:

    - ``not_reader_order``: no ordered issue memberships; nothing to migrate.
    - ``already_represented``: a strict-sequential plan holds the same issues
      in the same order.
    - ``safely_migratable``: clean ordered data with no overlapping plan.
    - ``merge_needed``: an existing plan overlaps the group; a human must
      reconcile rather than duplicate.
    - ``ambiguous``: conflicting or unmigratable state (duplicate orders,
      thread-level members, unordered issue members, unowned issues).
    """
    group, memberships = await _load_group(db, user_id=user_id, group_id=group_id)
    ordered = _ordered_pairs(memberships)
    thread_members = sorted(
        membership.id for membership in memberships if membership.thread_id is not None
    )
    unordered_issue_members = sorted(
        membership.id
        for membership in memberships
        if membership.issue_id is not None and membership.sequence_order is None
    )
    detail: dict[str, Any] = {
        "group_id": group.id,
        "group_name": group.name,
        "ordered_positions": [
            {"membership_id": mid, "issue_id": iid, "sequence_order": seq}
            for mid, iid, seq in ordered
        ],
        "thread_level_member_ids": thread_members,
        "unordered_issue_member_ids": unordered_issue_members,
        "content_hash": crossover_content_hash(ordered),
        "position_count": len(ordered),
    }
    if not ordered:
        return {**detail, "classification": "not_reader_order",
                "reason": "no ordered issue memberships"}
    sequence_orders = [seq for _, _, seq in ordered]
    if len(set(sequence_orders)) != len(sequence_orders):
        duplicates = sorted({s for s in sequence_orders if sequence_orders.count(s) > 1})
        return {**detail, "classification": "ambiguous",
                "reason": f"duplicate sequence_order values: {duplicates}"}
    if thread_members or unordered_issue_members:
        return {**detail, "classification": "ambiguous",
                "reason": "thread-level or unordered issue members cannot be "
                          "ordered without human disposition"}
    issue_ids = [iid for _, iid, _ in ordered]
    owned = set(
        (
            await db.execute(
                select(Issue.id)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Issue.id.in_(issue_ids), Thread.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    unowned = sorted(set(issue_ids) - owned)
    if unowned:
        return {**detail, "classification": "ambiguous",
                "reason": f"issues not owned by user: {unowned}"}

    overlaps: list[dict[str, Any]] = []
    represented_by: dict[str, Any] | None = None
    for plan, refs in await _plan_issue_refs(db, user_id=user_id):
        common = sorted(set(refs) & set(issue_ids))
        if not common:
            continue
        entry = {
            "id": plan.id,
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "overlap_count": len(common),
            "overlap_issue_ids": common,
        }
        overlaps.append(entry)
        if (
            refs == issue_ids
            and plan.ordering_mode == "strict_sequential"
            and represented_by is None
        ):
            represented_by = entry
    detail["overlapping_plans"] = overlaps
    if represented_by is not None:
        return {**detail, "classification": "already_represented",
                "reason": f"strict plan #{represented_by['id']} holds the same order",
                "represented_by_plan_id": represented_by["id"]}
    if overlaps:
        return {**detail, "classification": "merge_needed",
                "reason": "existing Reading Plan(s) overlap; reconcile before migrating"}
    return {**detail, "classification": "safely_migratable",
            "reason": "clean ordered data with no overlapping plan"}


async def inventory_crossover_reader_orders(
    db: AsyncSession, *, user_id: int
) -> list[dict[str, Any]]:
    """Classify every crossover group owned by the user, oldest first."""
    groups = list(
        (
            await db.execute(
                select(DependencyGroup)
                .where(DependencyGroup.user_id == user_id)
                .order_by(DependencyGroup.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        await classify_crossover_group(db, user_id=user_id, group_id=group.id)
        for group in groups
    ]


def _build_crossover_nodes(
    *,
    group_id: int,
    ordered: list[tuple[int, int, int]],
    labels: dict[int, str],
) -> tuple[list[ContinuityPlanLane], list[ContinuityPlanNode]]:
    """Build the strict plan payload for one classified group."""
    source_path = crossover_source_path(group_id)
    nodes = [
        ContinuityPlanNode(
            id=f"issue-{issue_id}",
            node_type="issue",
            ref_id=issue_id,
            lane_id="main",
            position=position,
            label=labels.get(issue_id),
            source_paths=(source_path,),
        )
        for position, (_, issue_id, _) in enumerate(ordered)
    ]
    return [ContinuityPlanLane(id="main", name="Reading order", order=0)], nodes


def _crossover_planned_rules(
    nodes: list[ContinuityPlanNode],
) -> list[dict[str, Any]]:
    """Describe strict adjacency rules for crossover plan nodes."""
    ordered = sorted(nodes, key=lambda node: node.position)
    return [
        {
            "kind": "adjacent",
            "source_type": source.node_type,
            "source_id": source.ref_id,
            "target_type": target.node_type,
            "target_id": target.ref_id,
            "satisfaction_type": "item_read",
        }
        for source, target in zip(ordered, ordered[1:], strict=False)
    ]


async def _factual_snapshot(
    db: AsyncSession,
    *,
    user_id: int,
    ordered_issue_ids: list[int],
) -> dict[str, Any]:
    """Capture reader facts the migration must not change."""
    issue_rows = list(
        (
            await db.execute(
                select(Issue, Thread)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Issue.id.in_(ordered_issue_ids), Thread.user_id == user_id)
            )
        ).all()
    )
    issues_by_id = {issue.id: (issue, thread) for issue, thread in issue_rows}
    thread_ids: set[int] = set()
    issues = []
    for issue_id in ordered_issue_ids:
        issue, thread = issues_by_id[issue_id]
        thread_ids.add(thread.id)
        issues.append(
            {
                "id": issue.id,
                "thread_id": thread.id,
                "issue_number": issue.issue_number,
                "status": issue.status,
                "read_at": json_value(issue.read_at),
            }
        )
    threads = [
        {
            "id": thread.id,
            "status": thread.status,
            "is_blocked": thread.is_blocked,
            "queue_position": thread.queue_position,
            "next_unread_issue_id": thread.next_unread_issue_id,
            "issues_remaining": thread.issues_remaining,
        }
        for thread in sorted(
            (
                await db.execute(
                    select(Thread).where(
                        Thread.user_id == user_id, Thread.id.in_(thread_ids)
                    )
                )
            )
            .scalars()
            .all(),
            key=lambda row: row.id,
        )
    ]
    events = sorted(
        {
            (event.id, event.type, json_value(event.timestamp), event.thread_id,
             event.issue_id, event.rating)
            for event in (
                await db.execute(
                    select(Event).where(
                        or_(
                            Event.issue_id.in_(ordered_issue_ids),
                            Event.thread_id.in_(thread_ids),
                        )
                    )
                )
            )
            .scalars()
            .all()
        }
    )
    return {
        "issues": issues,
        "threads": threads,
        "issue_state_hash": stable_hash(issues),
        "thread_state_hash": stable_hash(threads),
        "event_state_hash": stable_hash(events),
    }


async def build_crossover_reading_order_dry_run(
    db: AsyncSession,
    spec: CrossoverReadingOrderSpec,
) -> dict[str, Any]:
    """Build a deterministic read-only migration snapshot for one group."""
    invalidate_continuity_snapshot(spec.user_id, db)
    errors: list[str] = []
    classification = await classify_crossover_group(
        db, user_id=spec.user_id, group_id=spec.dependency_group_id
    )
    ordered = [
        (row["membership_id"], row["issue_id"], row["sequence_order"])
        for row in classification["ordered_positions"]
    ]
    if classification["content_hash"] != spec.expected_content_hash:
        errors.append("crossover order content changed since manifest")
    if classification["position_count"] != spec.expected_positions:
        errors.append(
            f"expected {spec.expected_positions} ordered positions; "
            f"found {classification['position_count']}"
        )

    issue_ids = [issue_id for _, issue_id, _ in ordered]
    labels: dict[int, str] = {}
    if issue_ids:
        rows = list(
            (
                await db.execute(
                    select(Issue, Thread)
                    .join(Thread, Thread.id == Issue.thread_id)
                    .where(Issue.id.in_(issue_ids))
                )
            ).all()
        )
        for issue, thread in rows:
            labels[issue.id] = f"{thread.title} #{issue.issue_number}"

    planned_payload: dict[str, Any] | None = None
    planned_rules: list[dict[str, Any]] = []
    if classification["classification"] == "safely_migratable":
        lanes, nodes = _build_crossover_nodes(
            group_id=spec.dependency_group_id, ordered=ordered, labels=labels
        )
        planned_rules = _crossover_planned_rules(nodes)
        planned_payload = {
            "name": spec.plan_name,
            "ordering_mode": "strict_sequential",
            "lanes": [lane.model_dump() for lane in lanes],
            "nodes": [node.model_dump() for node in nodes],
        }
        ContinuityPlanWrite.model_validate(planned_payload)

    factual = await _factual_snapshot(
        db, user_id=spec.user_id, ordered_issue_ids=issue_ids
    ) if issue_ids else {
        "issues": [], "threads": [],
        "issue_state_hash": stable_hash([]),
        "thread_state_hash": stable_hash([]),
        "event_state_hash": stable_hash([]),
    }

    affected_thread_ids: set[int] = set()
    if issue_ids:
        graph_threads = list(
            (
                await db.execute(
                    select(Thread).where(
                        Thread.user_id == spec.user_id,
                        Thread.status == "active",
                        Thread.next_unread_issue_id.in_(issue_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        affected_thread_ids = {thread.id for thread in graph_threads}
    current_blocked = await _get_blocked_thread_ids_uncached(spec.user_id, db)
    current_roll = {thread.id for thread in await get_roll_pool(spec.user_id, db)}
    current_eligible = sorted((current_roll & affected_thread_ids) - current_blocked)

    # Simulate canonical plan authority: an affected thread is blocked while any
    # earlier ordered issue is unread. This mirrors crossover_order_blockers so
    # the transfer is behavior-preserving; the delta is reported, not an error,
    # because moving authority to the plan is the migration's purpose.
    read_issue_ids = {
        row["id"] for row in factual["issues"] if row["status"] == "read"
    }
    position_of = {issue_id: pos for pos, (_, issue_id, _) in enumerate(ordered)}
    simulated_blocked: set[int] = set()
    if issue_ids:
        thread_next = {
            thread.id: thread.next_unread_issue_id
            for thread in (
                await db.execute(
                    select(Thread).where(Thread.id.in_(affected_thread_ids))
                )
            )
            .scalars()
            .all()
        }
        for thread_id, next_id in thread_next.items():
            if next_id is None or next_id not in position_of:
                continue
            if any(
                issue_id not in read_issue_ids
                for issue_id in issue_ids[: position_of[next_id]]
            ):
                simulated_blocked.add(thread_id)
    simulated_eligible = sorted(affected_thread_ids - simulated_blocked)

    state: dict[str, Any] = {
        "manifest": {
            "user_id": spec.user_id,
            "dependency_group_id": spec.dependency_group_id,
            "plan_name": spec.plan_name,
            "expected_content_hash": spec.expected_content_hash,
            "expected_positions": spec.expected_positions,
        },
        "classification": classification["classification"],
        "classification_reason": classification["reason"],
        "group": {
            "id": classification["group_id"],
            "name": classification["group_name"],
            "ordered_positions": classification["ordered_positions"],
            "thread_level_member_ids": classification["thread_level_member_ids"],
            "unordered_issue_member_ids": classification["unordered_issue_member_ids"],
            "content_hash": classification["content_hash"],
            "position_count": classification["position_count"],
        },
        "overlapping_plans": classification.get("overlapping_plans", []),
        "planned": None if planned_payload is None else {
            "plan": planned_payload,
            "rules": planned_rules,
            "adjacent_rule_count": max(len(issue_ids) - 1, 0),
            "plan_fingerprint": stable_hash(
                {
                    "name": planned_payload["name"],
                    "ordering_mode": planned_payload["ordering_mode"],
                    "nodes": planned_payload["nodes"],
                    "lanes": planned_payload["lanes"],
                }
            ),
        },
        "factual": factual,
        "runtime_behavior": {
            "affected_thread_ids": sorted(affected_thread_ids),
            "current_affected_roll_eligible_thread_ids": current_eligible,
            "simulated_canonical_eligible_thread_ids": simulated_eligible,
            "newly_blocked_by_plan_authority": sorted(
                set(current_eligible) - set(simulated_eligible)
            ),
        },
        "authority_note": (
            "Crossover sequence_order authority is NOT retired by this migration. "
            "The group, its memberships, and order survive; the plan adds canonical "
            "authority alongside. Retiring crossover order authority and demoting "
            "competing Crossover UI are #3046 cutover scope after verification."
        ),
    }
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot_token": stable_hash(state),
        **state,
    }


async def _find_migrated_plan(
    db: AsyncSession, *, user_id: int, group_id: int, issue_ids: list[int]
) -> ContinuityPlan | None:
    """Find a plan previously migrated from this group, if any."""
    if not issue_ids:
        return None
    marker = crossover_source_path(group_id)
    for plan, _ in await _plan_issue_refs(db, user_id=user_id):
        nodes = sorted(plan.nodes_json or [], key=lambda n: int(n.get("position", 0)))
        refs = [
            int(node["ref_id"])
            for node in nodes
            if node.get("node_type") == "issue" and "ref_id" in node
        ]
        if refs != issue_ids:
            continue
        found = False
        for node in nodes:
            raw_paths = node.get("source_paths")
            if isinstance(raw_paths, list) and marker in raw_paths:
                found = True
                break
        if found and plan.ordering_mode == "strict_sequential":
            return plan
    return None


async def apply_crossover_reading_order_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    spec: CrossoverReadingOrderSpec,
) -> dict[str, Any]:
    """Apply one reviewed snapshot inside the caller-owned transaction."""
    require_clean_snapshot(snapshot)
    current = await build_crossover_reading_order_dry_run(db, spec)
    if (
        current.get("snapshot_token") != snapshot["snapshot_token"]
        or current.get("ok") is not True
    ):
        raise MigrationInvariantError("live state changed since dry-run")

    classification = str(snapshot["classification"])
    issue_ids = [
        coerce_int(row["issue_id"]) for row in snapshot["group"]["ordered_positions"]
    ]
    if classification == "already_represented":
        plan = await _find_migrated_plan(
            db, user_id=spec.user_id,
            group_id=spec.dependency_group_id, issue_ids=issue_ids,
        )
        if plan is None:
            raise MigrationInvariantError(
                "group already represented by a non-migration plan; "
                "no migration needed"
            )
        return {
            "already_applied": True,
            "plan_id": plan.id,
            "plan_fingerprint": plan_fingerprint(plan),
            "source_snapshot_token": snapshot["snapshot_token"],
        }
    if classification != "safely_migratable":
        raise MigrationInvariantError(
            f"cannot apply classification {classification!r}"
        )

    planned = snapshot["planned"]
    if not isinstance(planned, dict):
        raise MigrationInvariantError("clean snapshot has no planned payload")
    payload = dict(planned["plan"])
    ContinuityPlanWrite.model_validate(payload)
    lanes = [ContinuityPlanLane(**lane) for lane in payload["lanes"]]
    nodes = [ContinuityPlanNode(**node) for node in payload["nodes"]]
    await validate_node_ownership(db, user_id=spec.user_id, nodes=nodes)
    plan = ContinuityPlan(
        user_id=spec.user_id,
        name=str(payload["name"]),
        ordering_mode="strict_sequential",
        lanes_json=[lane.model_dump() for lane in lanes],
        nodes_json=[node.model_dump() for node in nodes],
    )
    db.add(plan)
    await db.flush()

    marker = plan_rule_marker(plan.id)
    await replace_compiled_rules(
        db,
        user_id=spec.user_id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await refresh_blocked_status(spec.user_id, db)
    await db.flush()

    rules = list(
        (
            await db.execute(
                select(ContinuityRule)
                .where(
                    ContinuityRule.user_id == spec.user_id,
                    ContinuityRule.note == marker,
                )
                .order_by(ContinuityRule.id)
            )
        )
        .scalars()
        .all()
    )
    expected_count = max(len(nodes) - 1, 0)
    if len(rules) != expected_count:
        raise MigrationInvariantError(
            f"expected {expected_count} plan rules, found {len(rules)}"
        )
    expected_rules = {
        stable_hash(planned_rule_descriptor(rule)) for rule in planned["rules"]
    }
    actual_rules = {
        stable_hash(
            {
                "source_type": rule.source_type,
                "source_id": rule.source_id,
                "target_type": rule.target_type,
                "target_id": rule.target_id,
                "satisfaction_type": rule.satisfaction_type,
                "checkpoint_issue_id": rule.checkpoint_issue_id,
                "convergence_targets": rule.convergence_targets,
            }
        )
        for rule in rules
    }
    if expected_rules != actual_rules:
        raise MigrationInvariantError(
            "compiled rule semantics diverge from reviewed snapshot"
        )
    if plan_fingerprint(plan) != plan_fingerprint_from_payload(payload):
        raise MigrationInvariantError(
            "persisted Reading Plan diverges from reviewed snapshot"
        )

    factual = await _factual_snapshot(
        db, user_id=spec.user_id, ordered_issue_ids=issue_ids
    )
    for key in ("issue_state_hash", "thread_state_hash", "event_state_hash"):
        if factual[key] != snapshot["factual"][key]:
            raise MigrationInvariantError(f"protected reader state changed: {key}")

    affected_ids = {
        coerce_int(thread_id)
        for thread_id in snapshot["runtime_behavior"]["affected_thread_ids"]
    }
    current_blocked = await _get_blocked_thread_ids_uncached(spec.user_id, db)
    current_roll = {thread.id for thread in await get_roll_pool(spec.user_id, db)}
    eligible = sorted((current_roll & affected_ids) - current_blocked)

    return {
        "already_applied": False,
        "plan_id": plan.id,
        "plan_marker": marker,
        "plan_fingerprint": plan_fingerprint(plan),
        "plan_rule_count": len(rules),
        "plan_rule_fingerprint": rules_fingerprint(rules),
        "expected_new_plan_rule_count": expected_count,
        "affected_roll_eligible_thread_ids": eligible,
        "issue_state_hash": factual["issue_state_hash"],
        "thread_state_hash": factual["thread_state_hash"],
        "event_state_hash": factual["event_state_hash"],
        "source_snapshot_token": snapshot["snapshot_token"],
        "rollback_note": (
            "Crossover group and sequence_order untouched; rollback is deleting "
            f"plan {plan.id} and its continuity-plan:{plan.id} rules. Authority "
            "demotion is #3046 cutover scope."
        ),
    }
