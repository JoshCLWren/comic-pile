"""Guarded Step 23 Ultimate Universe CBL cutover migration.

Step 23A is a read-only preflight that proves production can be represented
canonically without changing affected Roll eligibility. Step 23B adds mutation
guards on top of that reviewed snapshot: ``apply_ultimate_universe_migration``
and ``rollback_ultimate_universe_migration`` perform the cutover inside the
caller's transaction and refuse to proceed unless the live database still
matches the exact reviewed snapshot token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, cast

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import (
    CBLPlacement,
    ContinuityPlanLane,
    ContinuityPlanNode,
    ContinuityPlanWrite,
    ConvergenceGateTarget,
)
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.continuity_graph import issue_readiness, load_snapshot
from app.services.continuity_plan_writer import (
    replace_compiled_rules,
    validate_node_ownership,
)
from comic_pile.dependencies import _get_blocked_thread_ids_uncached, refresh_user_blocked_status
from comic_pile.queue import get_roll_pool

TEMPORARY_REPAIR_NOTE = "Temporary authoritative Ultimate Universe CBL order incident repair"


class MigrationInvariantError(RuntimeError):
    """Raised when live state no longer matches the reviewed migration contract."""


@dataclass(frozen=True)
class UltimateUniverseDryRunSpec:
    """Reviewed identities for one source-scoped dry-run."""

    user_id: int
    source_list_id: int
    dependency_group_id: int
    expected_content_hash: str
    expected_positions: int
    plan_name: str = "Ultimate Universe"


PRODUCTION_ULTIMATE_UNIVERSE_SPEC = UltimateUniverseDryRunSpec(
    user_id=1,
    source_list_id=12,
    dependency_group_id=15,
    expected_content_hash="d8944942bb6115ea9607ac6be0ac53e59368b90a929d44412900b3b9cae8b66a",
    expected_positions=130,
)


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _stable_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_value,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _legacy_prefix(content_hash: str) -> str:
    return f"cbl-order:source:{content_hash}:"


def _resolved_entries(report_entries: tuple[dict[str, object], ...]) -> list[dict[str, object]]:
    return sorted(
        [
            dict(entry)
            for entry in report_entries
            if isinstance(entry.get("resolved_issue_id"), int)
        ],
        key=lambda entry: int(cast(int, entry["cbl_position"])),
    )


def _derive_gap_bridges(entries: list[dict[str, object]]) -> list[dict[str, int]]:
    """Derive compact strict-order bridges across historical read gaps."""
    bridges: list[dict[str, int]] = []
    latest_unread: dict[str, object] | None = None
    previous: dict[str, object] | None = None
    for entry in entries:
        if entry.get("read_status") != "unread":
            previous = entry
            continue
        if (
            previous is not None
            and previous.get("read_status") == "read"
            and latest_unread is not None
        ):
            bridges.append(
                {
                    "source_position": int(cast(int, latest_unread["cbl_position"])),
                    "source_issue_id": int(cast(int, latest_unread["resolved_issue_id"])),
                    "target_position": int(cast(int, entry["cbl_position"])),
                    "target_issue_id": int(cast(int, entry["resolved_issue_id"])),
                }
            )
        latest_unread = entry
        previous = entry
    return bridges


def _build_plan(
    entries: list[dict[str, object]],
    *,
    source_path: str,
    bridges: list[dict[str, int]],
) -> tuple[list[ContinuityPlanLane], list[ContinuityPlanNode]]:
    """Build the exact strict plan payload proposed by the dry-run."""
    bridge_source_by_target = {
        bridge["target_issue_id"]: bridge["source_issue_id"] for bridge in bridges
    }
    nodes: list[ContinuityPlanNode] = []
    for position, entry in enumerate(entries):
        issue_id = int(cast(int, entry["resolved_issue_id"]))
        source_position = int(cast(int, entry["cbl_position"]))
        bridge_source = bridge_source_by_target.get(issue_id)
        convergence_gate = (
            [
                ConvergenceGateTarget(
                    node_type="issue",
                    node_id=f"issue-{bridge_source}",
                )
            ]
            if bridge_source is not None
            else []
        )
        nodes.append(
            ContinuityPlanNode(
                id=f"issue-{issue_id}",
                node_type="issue",
                ref_id=issue_id,
                lane_id="main",
                position=position,
                label=f"{entry.get('series_name')} #{entry.get('issue_number')}",
                source_paths=(source_path,),
                source_cbl_placements=(
                    CBLPlacement(source_path=source_path, position=source_position),
                ),
                convergence_gate=convergence_gate,
            )
        )
    return [ContinuityPlanLane(id="main", name="Reading order", order=0)], nodes


def _planned_rules(
    nodes: list[ContinuityPlanNode],
    bridges: list[dict[str, int]],
) -> list[dict[str, object]]:
    """Describe strict adjacency plus migration-specific convergence bridges."""
    rules: list[dict[str, object]] = []
    ordered = sorted(nodes, key=lambda node: node.position)
    for source, target in zip(ordered, ordered[1:], strict=False):
        rules.append(
            {
                "kind": "adjacent",
                "source_type": source.node_type,
                "source_id": source.ref_id,
                "target_type": target.node_type,
                "target_id": target.ref_id,
                "satisfaction_type": "item_read",
            }
        )
    for bridge in bridges:
        rules.append(
            {
                "kind": "historical_gap",
                "source_type": "issue",
                "source_id": bridge["target_issue_id"],
                "target_type": "issue",
                "target_id": bridge["target_issue_id"],
                "satisfaction_type": "converged",
                "convergence_targets": [
                    {"type": "issue", "id": bridge["source_issue_id"]}
                ],
            }
        )
    return rules


def _rule_snapshot(rule: ContinuityRule) -> dict[str, object]:
    return {
        "id": rule.id,
        "legacy_dependency_id": rule.legacy_dependency_id,
        "source_type": rule.source_type,
        "source_id": rule.source_id,
        "target_type": rule.target_type,
        "target_id": rule.target_id,
        "satisfaction_type": rule.satisfaction_type,
        "checkpoint_issue_id": rule.checkpoint_issue_id,
        "convergence_targets": rule.convergence_targets,
        "note": rule.note,
        "created_at": _json_value(rule.created_at),
        "updated_at": _json_value(rule.updated_at),
    }


async def _factual_snapshot(
    db: AsyncSession,
    *,
    spec: UltimateUniverseDryRunSpec,
    ordered_issue_ids: list[int],
) -> dict[str, object]:
    """Capture reader facts that a future cutover must not change."""
    issue_rows = list(
        (
            await db.execute(
                select(Issue, Thread)
                .join(Thread, Thread.id == Issue.thread_id)
                .where(Issue.id.in_(ordered_issue_ids), Thread.user_id == spec.user_id)
            )
        ).all()
    )
    issues_by_id = {issue.id: (issue, thread) for issue, thread in issue_rows}
    issues = []
    thread_ids: set[int] = set()
    for issue_id in ordered_issue_ids:
        issue, thread = issues_by_id[issue_id]
        thread_ids.add(thread.id)
        issues.append(
            {
                "id": issue.id,
                "thread_id": thread.id,
                "thread_title": thread.title,
                "issue_number": issue.issue_number,
                "position": issue.position,
                "status": issue.status,
                "read_at": _json_value(issue.read_at),
            }
        )

    threads = [
        {
            "id": thread.id,
            "title": thread.title,
            "status": thread.status,
            "is_blocked": thread.is_blocked,
            "queue_position": thread.queue_position,
            "next_unread_issue_id": thread.next_unread_issue_id,
            "issues_remaining": thread.issues_remaining,
            "reading_progress": thread.reading_progress,
            "last_rating": thread.last_rating,
            "last_activity_at": _json_value(thread.last_activity_at),
        }
        for thread in sorted(
            (
                await db.execute(
                    select(Thread).where(
                        Thread.user_id == spec.user_id,
                        Thread.id.in_(thread_ids),
                    )
                )
            )
            .scalars()
            .all(),
            key=lambda row: row.id,
        )
    ]

    event_rows = list(
        (
            await db.execute(
                select(Event).where(
                    or_(
                        Event.issue_id.in_(ordered_issue_ids),
                        Event.thread_id.in_(thread_ids),
                        Event.selected_thread_id.in_(thread_ids),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    events = [
        {
            "id": event.id,
            "type": event.type,
            "timestamp": _json_value(event.timestamp),
            "selected_thread_id": event.selected_thread_id,
            "thread_id": event.thread_id,
            "issue_id": event.issue_id,
            "issue_number": event.issue_number,
            "rating": event.rating,
            "issues_read": event.issues_read,
            "selection_method": event.selection_method,
        }
        for event in sorted(event_rows, key=lambda row: row.id)
    ]

    mapping_rows = list(
        (
            await db.execute(
                select(IssueExternalIdentityMapping, ExternalIdentity)
                .join(
                    ExternalIdentity,
                    ExternalIdentity.id
                    == IssueExternalIdentityMapping.external_identity_id,
                )
                .where(IssueExternalIdentityMapping.issue_id.in_(ordered_issue_ids))
            )
        ).all()
    )
    identities = [
        {
            "mapping_id": mapping.id,
            "issue_id": mapping.issue_id,
            "mapping_status": mapping.status,
            "evidence_source": mapping.evidence_source,
            "confidence": mapping.confidence,
            "external_identity_id": identity.id,
            "provider": identity.provider,
            "entity_type": identity.entity_type,
            "external_id": identity.external_id,
        }
        for mapping, identity in sorted(mapping_rows, key=lambda row: row[0].id)
    ]
    return {
        "issues": issues,
        "threads": threads,
        "events": events,
        "identities": identities,
        "issue_state_hash": _stable_hash(issues),
        "thread_state_hash": _stable_hash(threads),
        "event_state_hash": _stable_hash(events),
        "identity_state_hash": _stable_hash(identities),
    }


async def build_ultimate_universe_dry_run(
    db: AsyncSession,
    spec: UltimateUniverseDryRunSpec = PRODUCTION_ULTIMATE_UNIVERSE_SPEC,
) -> dict[str, Any]:
    """Inspect the Step 23A cutover without writing any database row."""
    errors: list[str] = []

    source_list = await db.get(CBLSourceList, spec.source_list_id)
    if source_list is None or not source_list.active:
        return {
            "ok": False,
            "errors": [f"source list {spec.source_list_id} is missing or inactive"],
            "snapshot_token": None,
        }
    if source_list.content_hash != spec.expected_content_hash:
        errors.append(
            "source content hash changed: "
            f"expected {spec.expected_content_hash}, got {source_list.content_hash}"
        )

    group = await db.scalar(
        select(DependencyGroup).where(
            DependencyGroup.id == spec.dependency_group_id,
            DependencyGroup.user_id == spec.user_id,
        )
    )
    if group is None:
        return {
            "ok": False,
            "errors": [f"dependency group {spec.dependency_group_id} is missing"],
            "snapshot_token": None,
        }

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
    membership_issue_ids = {
        membership.issue_id
        for membership in memberships
        if membership.issue_id is not None
    }
    ordered_memberships = [
        membership.id for membership in memberships if membership.sequence_order is not None
    ]
    if ordered_memberships:
        errors.append(
            f"group {group.id} unexpectedly has ordered memberships: {ordered_memberships}"
        )

    report = await reconcile_cbl_source_list(
        db,
        user_id=spec.user_id,
        list_id=spec.source_list_id,
        baseline_member_issue_ids=tuple(sorted(membership_issue_ids)),
    )
    entries = _resolved_entries(report.entries)
    if report.total_positions != spec.expected_positions:
        errors.append(
            f"expected {spec.expected_positions} source positions, got {report.total_positions}"
        )
    if len(entries) != spec.expected_positions:
        errors.append(
            f"expected {spec.expected_positions} uniquely resolved positions, got {len(entries)}"
        )
    if report.unresolved_count or report.ambiguous_count:
        errors.append(
            "source reconciliation is not clean: "
            f"unresolved={report.unresolved_count}, ambiguous={report.ambiguous_count}"
        )
    resolved_issue_ids = [
        int(cast(int, entry["resolved_issue_id"])) for entry in entries
    ]
    if len(resolved_issue_ids) != len(set(resolved_issue_ids)):
        errors.append("source positions do not resolve one-to-one to canonical issues")
    if set(resolved_issue_ids) != membership_issue_ids:
        errors.append(
            "dependency-group issue membership differs from reconciled source issue set"
        )

    overlapping_plans: list[dict[str, object]] = []
    issue_id_set = set(resolved_issue_ids)
    user_plans = list(
        (
            await db.execute(
                select(ContinuityPlan).where(ContinuityPlan.user_id == spec.user_id)
            )
        )
        .scalars()
        .all()
    )
    for plan in user_plans:
        referenced = {
            int(node.get("ref_id", 0))
            for node in plan.nodes_json or []
            if node.get("node_type") == "issue"
        }
        overlap = referenced & issue_id_set
        if overlap:
            overlapping_plans.append(
                {
                    "id": plan.id,
                    "name": plan.name,
                    "ordering_mode": plan.ordering_mode,
                    "overlap_count": len(overlap),
                }
            )
    if overlapping_plans:
        errors.append(f"existing Reading Plan overlap: {overlapping_plans!r}")

    prefix = _legacy_prefix(source_list.content_hash)
    source_dependencies = list(
        (
            await db.execute(
                select(Dependency)
                .where(Dependency.note.like(f"{prefix}%"))
                .order_by(Dependency.id)
            )
        )
        .scalars()
        .all()
    )
    bad_legacy_edges = [
        dep.id
        for dep in source_dependencies
        if dep.source_issue_id not in issue_id_set or dep.target_issue_id not in issue_id_set
    ]
    if bad_legacy_edges:
        errors.append(
            f"source-scoped legacy dependencies escape the reconciled issue set: {bad_legacy_edges}"
        )
    source_dependency_ids = {dep.id for dep in source_dependencies}
    linked_source_rules = (
        list(
            (
                await db.execute(
                    select(ContinuityRule)
                    .where(ContinuityRule.legacy_dependency_id.in_(source_dependency_ids))
                    .order_by(ContinuityRule.id)
                )
            )
            .scalars()
            .all()
        )
        if source_dependency_ids
        else []
    )
    if linked_source_rules:
        errors.append(
            "source-scoped legacy dependencies are still referenced by canonical rules: "
            f"{[rule.id for rule in linked_source_rules]}"
        )

    temporary_dependencies = list(
        (
            await db.execute(
                select(Dependency)
                .where(
                    Dependency.note == TEMPORARY_REPAIR_NOTE,
                    Dependency.source_issue_id.in_(issue_id_set),
                    Dependency.target_issue_id.in_(issue_id_set),
                )
                .order_by(Dependency.id)
            )
        )
        .scalars()
        .all()
    )
    temporary_dependency_ids = {dep.id for dep in temporary_dependencies}
    temporary_rules = (
        list(
            (
                await db.execute(
                    select(ContinuityRule)
                    .where(
                        ContinuityRule.user_id == spec.user_id,
                        ContinuityRule.legacy_dependency_id.in_(temporary_dependency_ids),
                    )
                    .order_by(ContinuityRule.id)
                )
            )
            .scalars()
            .all()
        )
        if temporary_dependency_ids
        else []
    )
    temporary_rule_ids = {rule.id for rule in temporary_rules}

    bridges = _derive_gap_bridges(entries)
    source_path = report.source_path or source_list.source_path
    lanes, nodes = _build_plan(entries, source_path=source_path, bridges=bridges)
    planned_rules = _planned_rules(nodes, bridges)

    adjacency_edges = {
        (int(rule["source_id"]), int(rule["target_id"]))
        for rule in planned_rules
        if rule["kind"] == "adjacent"
    }
    existing_edge_rules = list(
        (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == spec.user_id,
                    ContinuityRule.source_type == "issue",
                    ContinuityRule.target_type == "issue",
                    ContinuityRule.source_id.in_(issue_id_set),
                    ContinuityRule.target_id.in_(issue_id_set),
                )
            )
        )
        .scalars()
        .all()
    )
    reusable_rules: list[ContinuityRule] = []
    conflicting_rules: list[ContinuityRule] = []
    for rule in existing_edge_rules:
        if (rule.source_id, rule.target_id) not in adjacency_edges:
            continue
        if rule.id in temporary_rule_ids:
            continue
        is_reusable = (
            rule.satisfaction_type == "item_read"
            and not (rule.note or "").startswith("continuity-plan:")
            and rule.checkpoint_issue_id is None
            and not rule.convergence_targets
        )
        (reusable_rules if is_reusable else conflicting_rules).append(rule)
    if conflicting_rules:
        errors.append(
            "planned adjacent edges conflict with existing non-reusable rules: "
            f"{[rule.id for rule in conflicting_rules]}"
        )

    factual = await _factual_snapshot(
        db,
        spec=spec,
        ordered_issue_ids=resolved_issue_ids,
    )

    graph = await load_snapshot(db, spec.user_id)
    affected_threads = [
        thread
        for thread in graph.threads.values()
        if (
            thread.status == "active"
            and thread.queue_position >= 1
            and thread.next_unread_issue_id in issue_id_set
        )
    ]
    affected_thread_ids = {thread.id for thread in affected_threads}
    next_issue_ids = {
        thread.next_unread_issue_id
        for thread in affected_threads
        if thread.next_unread_issue_id is not None
    }

    raw_dependencies = (
        list(
            (
                await db.execute(
                    select(Dependency)
                    .where(Dependency.target_issue_id.in_(next_issue_ids))
                    .order_by(Dependency.id)
                )
            )
            .scalars()
            .all()
        )
        if next_issue_ids
        else []
    )
    raw_by_target: dict[int, list[Dependency]] = {}
    for dependency in raw_dependencies:
        raw_by_target.setdefault(dependency.target_issue_id, []).append(dependency)

    current_blocked_ids = await _get_blocked_thread_ids_uncached(spec.user_id, db)
    current_roll_ids = {thread.id for thread in await get_roll_pool(spec.user_id, db)}
    current_affected_eligible = sorted(current_roll_ids & affected_thread_ids)
    derived_current_eligible = sorted(affected_thread_ids - current_blocked_ids)
    if current_affected_eligible != derived_current_eligible:
        errors.append(
            "persisted Roll eligibility differs from uncached unified blocking: "
            f"roll={current_affected_eligible}, derived={derived_current_eligible}"
        )

    planned_sources_by_target: dict[int, list[int]] = {}
    for rule in planned_rules:
        if rule["kind"] == "adjacent":
            planned_sources_by_target.setdefault(int(rule["target_id"]), []).append(
                int(rule["source_id"])
            )
        else:
            for target in cast(list[dict[str, int]], rule["convergence_targets"]):
                planned_sources_by_target.setdefault(int(rule["target_id"]), []).append(
                    int(target["id"])
                )

    behavior_rows: list[dict[str, object]] = []
    future_blocked_ids: set[int] = set()
    source_protected_targets: set[int] = set()
    planned_direct_targets: set[int] = set()
    lost_source_protection: list[int] = []
    for thread in sorted(affected_threads, key=lambda row: row.id):
        next_issue_id = cast(int, thread.next_unread_issue_id)
        raw_rows = raw_by_target.get(next_issue_id, [])
        source_raw_blockers = [
            dep.id
            for dep in raw_rows
            if dep.id in source_dependency_ids
            and graph.issues.get(dep.source_issue_id) is not None
            and graph.issues[dep.source_issue_id].status != "read"
        ]
        other_raw_blockers = [
            dep.id
            for dep in raw_rows
            if dep.id not in source_dependency_ids
            and dep.id not in temporary_dependency_ids
            and graph.issues.get(dep.source_issue_id) is not None
            and graph.issues[dep.source_issue_id].status != "read"
        ]
        remaining_continuity_blockers = [
            blocker
            for blocker in issue_readiness(next_issue_id, graph)
            if blocker.rule_id not in temporary_rule_ids
        ]
        planned_blockers = [
            source_id
            for source_id in planned_sources_by_target.get(next_issue_id, [])
            if graph.issues.get(source_id) is not None
            and graph.issues[source_id].status != "read"
        ]
        if source_raw_blockers:
            source_protected_targets.add(next_issue_id)
        if planned_blockers:
            planned_direct_targets.add(next_issue_id)
        future_blocked = bool(
            other_raw_blockers or remaining_continuity_blockers or planned_blockers
        )
        if future_blocked:
            future_blocked_ids.add(thread.id)
        if source_raw_blockers and not future_blocked:
            lost_source_protection.append(next_issue_id)
        behavior_rows.append(
            {
                "thread_id": thread.id,
                "thread_title": thread.title,
                "next_unread_issue_id": next_issue_id,
                "currently_blocked": thread.id in current_blocked_ids,
                "current_source_dependency_blocker_ids": source_raw_blockers,
                "future_other_dependency_blocker_ids": other_raw_blockers,
                "future_existing_continuity_blocker_rule_ids": [
                    blocker.rule_id for blocker in remaining_continuity_blockers
                ],
                "future_planned_blocker_source_issue_ids": planned_blockers,
                "simulated_future_blocked": future_blocked,
            }
        )

    future_affected_eligible = sorted(affected_thread_ids - future_blocked_ids)
    if lost_source_protection:
        errors.append(
            "planned representation loses source protection for next-unread issues: "
            f"{sorted(lost_source_protection)}"
        )
    if future_affected_eligible != current_affected_eligible:
        errors.append(
            "affected Roll-eligible thread set would change: "
            f"before={current_affected_eligible}, after={future_affected_eligible}"
        )

    plan_payload = {
        "name": spec.plan_name,
        "ordering_mode": "strict_sequential",
        "lanes": [lane.model_dump() for lane in lanes],
        "nodes": [node.model_dump() for node in nodes],
    }
    state: dict[str, object] = {
        "source": {
            "list_id": source_list.id,
            "source_id": source_list.source_id,
            "name": source_list.name,
            "source_path": source_list.source_path,
            "content_hash": source_list.content_hash,
            "revision_sha": source_list.revision_sha,
            "active": source_list.active,
            "position_count": report.total_positions,
            "resolved_count": report.resolved_count,
            "unresolved_count": report.unresolved_count,
            "ambiguous_count": report.ambiguous_count,
            "first_unread_position": report.first_unread_position,
            "first_unread_issue_id": report.first_unread_issue_id,
        },
        "dependency_group": {
            "id": group.id,
            "name": group.name,
            "membership_count": len(memberships),
            "ordered_membership_count": len(ordered_memberships),
            "issue_ids": sorted(membership_issue_ids),
        },
        "factual": factual,
        "overlapping_plans": overlapping_plans,
        "source_legacy_dependencies": [
            {
                "id": dep.id,
                "source_issue_id": dep.source_issue_id,
                "target_issue_id": dep.target_issue_id,
                "note": dep.note,
                "created_at": _json_value(dep.created_at),
            }
            for dep in source_dependencies
        ],
        "source_linked_continuity_rules": [
            _rule_snapshot(rule) for rule in linked_source_rules
        ],
        "temporary_repair_dependencies": [
            {
                "id": dep.id,
                "source_issue_id": dep.source_issue_id,
                "target_issue_id": dep.target_issue_id,
                "note": dep.note,
                "created_at": _json_value(dep.created_at),
            }
            for dep in temporary_dependencies
        ],
        "temporary_repair_rules": [_rule_snapshot(rule) for rule in temporary_rules],
        "reused_standalone_rules": [
            _rule_snapshot(rule) for rule in sorted(reusable_rules, key=lambda row: row.id)
        ],
        "conflicting_rules": [
            _rule_snapshot(rule) for rule in sorted(conflicting_rules, key=lambda row: row.id)
        ],
        "historical_gap_bridges": bridges,
        "planned": {
            "plan": plan_payload,
            "rules": planned_rules,
            "adjacent_rule_count": len(nodes) - 1 if nodes else 0,
            "gap_bridge_count": len(bridges),
            "reused_standalone_rule_count": len(reusable_rules),
            "expected_new_plan_rule_count": (
                max(len(nodes) - 1, 0) - len(reusable_rules) + len(bridges)
            ),
        },
        "runtime_behavior": {
            "affected_thread_ids": sorted(affected_thread_ids),
            "current_affected_roll_eligible_thread_ids": current_affected_eligible,
            "derived_current_eligible_thread_ids": derived_current_eligible,
            "simulated_future_eligible_thread_ids": future_affected_eligible,
            "source_protected_next_issue_ids": sorted(source_protected_targets),
            "planned_direct_blocked_next_issue_ids": sorted(planned_direct_targets),
            "planned_extra_direct_blockers": sorted(
                planned_direct_targets - source_protected_targets
            ),
            "rows": behavior_rows,
        },
    }
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot_token": _stable_hash(state),
        **state,
    }


def _require_reviewed_snapshot(snapshot: dict[str, Any]) -> None:
    """Validate a Step 23A snapshot is a clean, reviewable cutover contract."""
    token = snapshot.get("snapshot_token")
    if not isinstance(token, str) or not token:
        raise MigrationInvariantError("dry-run snapshot is missing snapshot_token")
    if snapshot.get("ok") is not True:
        raise MigrationInvariantError(
            f"dry-run snapshot was not clean: {snapshot.get('errors')!r}"
        )


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise MigrationInvariantError(f"expected ISO timestamp, got {value!r}")
    return datetime.fromisoformat(value)


def _plan_fingerprint(plan: ContinuityPlan) -> str:
    """Return the exact storage fingerprint of one migrated Reading Plan."""
    return _stable_hash(
        {
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "nodes": plan.nodes_json,
            "lanes": plan.lanes_json,
        }
    )


def _plan_fingerprint_from_payload(payload: dict[str, object]) -> str:
    """Return the fingerprint a snapshot expects the migrated plan to store."""
    return _stable_hash(
        {
            "name": payload["name"],
            "ordering_mode": payload["ordering_mode"],
            "nodes": payload["nodes"],
            "lanes": payload["lanes"],
        }
    )


def _rule_descriptor(rule: ContinuityRule) -> dict[str, object]:
    """Return the blocking semantics of one compiled rule for fingerprinting."""
    return {
        "source_type": rule.source_type,
        "source_id": rule.source_id,
        "target_type": rule.target_type,
        "target_id": rule.target_id,
        "satisfaction_type": rule.satisfaction_type,
        "checkpoint_issue_id": rule.checkpoint_issue_id,
        "convergence_targets": rule.convergence_targets,
    }


def _rules_fingerprint(rules: list[ContinuityRule]) -> str:
    """Return a stable fingerprint over an ordered set of compiled rules."""
    return _stable_hash(
        [
            _rule_descriptor(rule)
            for rule in sorted(rules, key=lambda row: row.id)
        ]
    )


def _planned_rule_descriptor(rule: dict[str, object]) -> dict[str, object]:
    """Project a dry-run planned rule into the compiled rule descriptor space."""
    return {
        "source_type": rule["source_type"],
        "source_id": int(cast(int, rule["source_id"])),
        "target_type": rule["target_type"],
        "target_id": int(cast(int, rule["target_id"])),
        "satisfaction_type": rule["satisfaction_type"],
        "checkpoint_issue_id": None,
        "convergence_targets": rule.get("convergence_targets"),
    }


def _achieve_node_issue_ids(snapshot: dict[str, Any]) -> list[int]:
    """Return the reviewed source-ordered canonical issue IDs for the cutover."""
    return [
        int(cast(int, node["ref_id"]))
        for node in snapshot["planned"]["plan"]["nodes"]
    ]


def _snapshot_reusable_edges(snapshot: dict[str, Any]) -> set[tuple[int, int]]:
    """Return edges already satisfied by surviving standalone prerequisite rules."""
    return {
        (int(cast(int, row["source_id"])), int(cast(int, row["target_id"])))
        for row in snapshot.get("reused_standalone_rules", [])
    }


async def apply_ultimate_universe_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    spec: UltimateUniverseDryRunSpec = PRODUCTION_ULTIMATE_UNIVERSE_SPEC,
) -> dict[str, Any]:
    """Apply the reviewed Step 23A cutover inside the caller's transaction.

    The caller owns commit/rollback. Every destructive write is preceded by a
    live dry-run whose snapshot token must match the reviewed snapshot exactly.
    """
    _require_reviewed_snapshot(snapshot)
    current = await build_ultimate_universe_dry_run(db, spec)
    if current["snapshot_token"] != snapshot["snapshot_token"]:
        raise MigrationInvariantError(
            "live Ultimate Universe state changed since dry-run; "
            "generate a new reviewed snapshot"
        )
    if current["ok"] is not True:
        raise MigrationInvariantError(f"preflight failed: {current['errors']!r}")

    issue_ids = _achieve_node_issue_ids(snapshot)
    issue_id_set = set(issue_ids)

    source_ids = [int(cast(int, row["id"])) for row in snapshot["source_legacy_dependencies"]]
    temporary_ids = [
        int(cast(int, row["id"])) for row in snapshot["temporary_repair_dependencies"]
    ]

    if source_ids:
        result = await db.execute(delete(Dependency).where(Dependency.id.in_(source_ids)))
        deleted_count = getattr(result, "rowcount", None)
        if deleted_count != len(source_ids):
            raise MigrationInvariantError(
                f"expected to remove {len(source_ids)} source-scoped dependencies, "
                f"removed {deleted_count}"
            )
    await db.flush()

    if temporary_ids:
        result = await db.execute(delete(Dependency).where(Dependency.id.in_(temporary_ids)))
        deleted_count = getattr(result, "rowcount", None)
        if deleted_count != len(temporary_ids):
            raise MigrationInvariantError(
                f"expected to remove {len(temporary_ids)} temporary repair "
                f"dependencies, removed {deleted_count}"
            )
    await db.flush()

    if temporary_ids:
        surviving_temporary_rules = list(
            (
                await db.execute(
                    select(ContinuityRule.id).where(
                        ContinuityRule.legacy_dependency_id.in_(temporary_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if surviving_temporary_rules:
            raise MigrationInvariantError(
                "temporary incident-repair rules survived dependency deletion: "
                f"{surviving_temporary_rules}"
            )

    plan_payload = dict(snapshot["planned"]["plan"])
    ContinuityPlanWrite.model_validate(plan_payload)
    lanes = [ContinuityPlanLane(**lane) for lane in plan_payload["lanes"]]
    nodes = [ContinuityPlanNode(**node) for node in plan_payload["nodes"]]
    await validate_node_ownership(db, user_id=spec.user_id, nodes=nodes)

    plan = ContinuityPlan(
        user_id=spec.user_id,
        name=str(plan_payload["name"]),
        ordering_mode="strict_sequential",
        lanes_json=[lane.model_dump() for lane in lanes],
        nodes_json=[node.model_dump() for node in nodes],
    )
    db.add(plan)
    await db.flush()
    marker = f"continuity-plan:{plan.id}"
    await replace_compiled_rules(
        db,
        user_id=spec.user_id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await refresh_user_blocked_status(spec.user_id, db)
    await db.flush()

    plan_rules = list(
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

    expected_count = int(cast(int, snapshot["planned"]["expected_new_plan_rule_count"]))
    if len(plan_rules) != expected_count:
        raise MigrationInvariantError(
            f"expected {expected_count} plan-owned rules, found {len(plan_rules)}"
        )

    reusable_edges = _snapshot_reusable_edges(snapshot)
    expected_descriptors = [
        _planned_rule_descriptor(rule)
        for rule in snapshot["planned"]["rules"]
        if (
            int(cast(int, rule["source_id"])),
            int(cast(int, rule["target_id"])),
        )
        not in reusable_edges
    ]
    expected_keys = {
        json.dumps(
            descriptor, sort_keys=True, separators=(",", ":"), default=_json_value
        )
        for descriptor in expected_descriptors
    }
    actual_keys = {
        json.dumps(
            _rule_descriptor(rule), sort_keys=True, separators=(",", ":"), default=_json_value
        )
        for rule in plan_rules
    }
    if expected_keys != actual_keys:
        raise MigrationInvariantError(
            "compiled rule set diverges from the reviewed snapshot"
        )
    if len(plan_rules) != len(expected_descriptors):
        raise MigrationInvariantError(
            "plan-owned rule count diverges from the reviewed snapshot semantics"
        )

    actual_plan_fingerprint = _plan_fingerprint(plan)
    expected_plan_fingerprint = _plan_fingerprint_from_payload(plan_payload)
    if actual_plan_fingerprint != expected_plan_fingerprint:
        raise MigrationInvariantError(
            "persisted Reading Plan fingerprint diverges from the reviewed snapshot"
        )

    ordered_membership_count = await db.scalar(
        select(DependencyGroupMembership.id)
        .where(
            DependencyGroupMembership.group_id == spec.dependency_group_id,
            DependencyGroupMembership.sequence_order.is_not(None),
        )
        .limit(1)
    )
    if ordered_membership_count is not None:
        raise MigrationInvariantError(
            "dependency group gained ordered memberships during cutover"
        )

    for row in snapshot["reused_standalone_rules"]:
        rule = await db.get(ContinuityRule, int(cast(int, row["id"])))
        if rule is None or _rule_snapshot(rule) != row:
            raise MigrationInvariantError(
                f"reused standalone rule {row['id']} changed during cutover"
            )

    prefix = _legacy_prefix(str(snapshot["source"]["content_hash"]))
    remaining_authority = list(
        (
            await db.execute(
                select(Dependency.id)
                .where(
                    or_(
                        Dependency.note.like(f"{prefix}%"),
                        Dependency.note == TEMPORARY_REPAIR_NOTE,
                    ),
                    Dependency.source_issue_id.in_(issue_id_set),
                    Dependency.target_issue_id.in_(issue_id_set),
                )
            )
        )
        .scalars()
        .all()
    )
    if remaining_authority:
        raise MigrationInvariantError(
            "source-scoped or temporary dependency authority survived cutover: "
            f"{remaining_authority}"
        )

    factual = await _factual_snapshot(db, spec=spec, ordered_issue_ids=issue_ids)
    before_factual = snapshot["factual"]
    for key in ("issue_state_hash", "thread_state_hash", "event_state_hash", "identity_state_hash"):
        if factual[key] != before_factual[key]:
            raise MigrationInvariantError(
                f"cutover changed protected factual state: {key}"
            )

    affected_thread_ids = {
        int(cast(int, thread_id))
        for thread_id in snapshot["runtime_behavior"]["affected_thread_ids"]
    }
    roll_ids = {thread.id for thread in await get_roll_pool(spec.user_id, db)}
    affected_eligible = sorted(roll_ids & affected_thread_ids)
    preflight_eligible = snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ]
    if affected_eligible != preflight_eligible:
        raise MigrationInvariantError(
            "affected Roll-eligible thread set changed after cutover: "
            f"preflight={preflight_eligible}, now={affected_eligible}"
        )

    return {
        "plan_id": plan.id,
        "plan_marker": marker,
        "plan_fingerprint": actual_plan_fingerprint,
        "plan_rule_count": len(plan_rules),
        "plan_rule_fingerprint": _rules_fingerprint(plan_rules),
        "expected_new_plan_rule_count": expected_count,
        "removed_source_dependency_count": len(source_ids),
        "removed_temporary_dependency_count": len(temporary_ids),
        "reused_standalone_rule_count": len(snapshot["reused_standalone_rules"]),
        "issue_state_hash": factual["issue_state_hash"],
        "thread_state_hash": factual["thread_state_hash"],
        "event_state_hash": factual["event_state_hash"],
        "identity_state_hash": factual["identity_state_hash"],
        "affected_roll_eligible_thread_ids": affected_eligible,
        "source_snapshot_token": snapshot["snapshot_token"],
    }


async def rollback_ultimate_universe_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    receipt: dict[str, Any],
    spec: UltimateUniverseDryRunSpec = PRODUCTION_ULTIMATE_UNIVERSE_SPEC,
) -> dict[str, Any]:
    """Restore the reviewed source-12 dependency state after a failed cutover.

    The caller owns commit/rollback. Rollback is refused unless the migrated
    plan, its compiled rule set, and every reused standalone rule still match
    the apply receipt exactly.
    """
    _require_reviewed_snapshot(snapshot)
    plan_id = receipt.get("plan_id")
    expected_fingerprint = receipt.get("plan_fingerprint")
    expected_rule_count = receipt.get("plan_rule_count")
    expected_rule_fingerprint = receipt.get("plan_rule_fingerprint")
    if (
        not isinstance(plan_id, int)
        or not isinstance(expected_fingerprint, str)
        or not isinstance(expected_rule_count, int)
        or not isinstance(expected_rule_fingerprint, str)
    ):
        raise MigrationInvariantError("apply receipt is missing plan identity")

    plan = (
        await db.execute(
            select(ContinuityPlan).where(
                ContinuityPlan.id == plan_id,
                ContinuityPlan.user_id == spec.user_id,
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise MigrationInvariantError(
            f"migrated Reading Plan {plan_id} no longer exists"
        )
    if _plan_fingerprint(plan) != expected_fingerprint:
        raise MigrationInvariantError(
            "migrated Reading Plan was edited after cutover; "
            "refusing automatic rollback"
        )

    marker = f"continuity-plan:{plan.id}"
    plan_rules = list(
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
    if len(plan_rules) != expected_rule_count:
        raise MigrationInvariantError(
            "plan-owned compiled rule set changed after cutover; "
            "refusing automatic rollback"
        )
    if _rules_fingerprint(plan_rules) != expected_rule_fingerprint:
        raise MigrationInvariantError(
            "plan-owned compiled rule set changed after cutover; "
            "refusing automatic rollback"
        )

    for row in snapshot.get("reused_standalone_rules", []):
        rule = await db.get(ContinuityRule, int(cast(int, row["id"])))
        if rule is None or _rule_snapshot(rule) != row:
            raise MigrationInvariantError(
                f"reused standalone rule {row['id']} changed after cutover; "
                "refusing automatic rollback"
            )

    for rule in plan_rules:
        await db.delete(rule)
    await db.flush()
    remaining_plan_rule_ids = list(
        (
            await db.execute(
                select(ContinuityRule.id).where(
                    ContinuityRule.user_id == spec.user_id,
                    ContinuityRule.note == marker,
                )
            )
        )
        .scalars()
        .all()
    )
    if remaining_plan_rule_ids:
        raise MigrationInvariantError(
            "plan-owned rules survived rollback removal: "
            f"{remaining_plan_rule_ids}"
        )

    await db.delete(plan)
    await db.flush()

    source_rows = snapshot.get("source_legacy_dependencies")
    temporary_rows = snapshot.get("temporary_repair_dependencies")
    temporary_rule_rows = snapshot.get("temporary_repair_rules")
    if (
        not isinstance(source_rows, list)
        or not isinstance(temporary_rows, list)
        or not isinstance(temporary_rule_rows, list)
    ):
        raise MigrationInvariantError("dry-run snapshot lacks rollback rows")

    dependency_ids = {int(cast(int, row["id"])) for row in source_rows}
    dependency_ids.update(int(cast(int, row["id"])) for row in temporary_rows)
    edge_filters = [
        (Dependency.source_issue_id == int(cast(int, row["source_issue_id"])))
        & (Dependency.target_issue_id == int(cast(int, row["target_issue_id"])))
        for row in [*source_rows, *temporary_rows]
    ]
    conflicting_dependencies = list(
        (
            await db.execute(
                select(Dependency).where(
                    or_(Dependency.id.in_(dependency_ids), *edge_filters)
                )
            )
        )
        .scalars()
        .all()
    )
    if conflicting_dependencies:
        raise MigrationInvariantError(
            "legacy dependency IDs/edges are no longer free; "
            "refusing automatic rollback"
        )

    for row in source_rows:
        db.add(
            Dependency(
                id=int(cast(int, row["id"])),
                source_issue_id=int(cast(int, row["source_issue_id"])),
                target_issue_id=int(cast(int, row["target_issue_id"])),
                created_at=_parse_datetime(row["created_at"]),
                note=row.get("note"),
            )
        )
    await db.flush()

    for row in temporary_rows:
        db.add(
            Dependency(
                id=int(cast(int, row["id"])),
                source_issue_id=int(cast(int, row["source_issue_id"])),
                target_issue_id=int(cast(int, row["target_issue_id"])),
                created_at=_parse_datetime(row["created_at"]),
                note=row.get("note"),
            )
        )
    await db.flush()

    restored_rule_ids: set[int] = set()
    for row in temporary_rule_rows:
        legacy_dependency_id = int(cast(int, row["legacy_dependency_id"]))
        rule = (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.legacy_dependency_id == legacy_dependency_id
                )
            )
        ).scalar_one_or_none()
        if rule is None:
            rule = ContinuityRule(
                id=int(cast(int, row["id"])),
                user_id=spec.user_id,
                legacy_dependency_id=legacy_dependency_id,
                source_type=str(row["source_type"]),
                source_id=int(cast(int, row["source_id"])),
                target_type=str(row["target_type"]),
                target_id=int(cast(int, row["target_id"])),
                satisfaction_type=str(row["satisfaction_type"]),
                checkpoint_issue_id=row.get("checkpoint_issue_id"),
                convergence_targets=row.get("convergence_targets"),
                note=row.get("note"),
                created_at=_parse_datetime(row["created_at"]),
                updated_at=_parse_datetime(row["updated_at"]),
            )
            db.add(rule)
        else:
            expected_edge = (
                spec.user_id,
                str(row["source_type"]),
                int(cast(int, row["source_id"])),
                str(row["target_type"]),
                int(cast(int, row["target_id"])),
            )
            actual_edge = (
                rule.user_id,
                rule.source_type,
                rule.source_id,
                rule.target_type,
                rule.target_id,
            )
            if actual_edge != expected_edge:
                raise MigrationInvariantError(
                    "legacy dependency trigger restored an unexpected rule edge: "
                    f"expected {expected_edge!r}, got {actual_edge!r}"
                )
            rule.id = int(cast(int, row["id"]))
            rule.satisfaction_type = str(row["satisfaction_type"])
            rule.checkpoint_issue_id = row.get("checkpoint_issue_id")
            rule.convergence_targets = row.get("convergence_targets")
            rule.note = row.get("note")
            rule.created_at = _parse_datetime(row["created_at"])
            rule.updated_at = _parse_datetime(row["updated_at"])
        restored_rule_ids.add(int(cast(int, row["id"])))
    await db.flush()

    temporary_dependency_ids = {int(cast(int, row["id"])) for row in temporary_rows}
    actual_restored_rule_ids = set(
        (
            await db.execute(
                select(ContinuityRule.id).where(
                    ContinuityRule.legacy_dependency_id.in_(temporary_dependency_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if actual_restored_rule_ids != restored_rule_ids:
        raise MigrationInvariantError(
            "rollback failed to restore exact temporary continuity rules: "
            f"{sorted(actual_restored_rule_ids)}"
        )
    for row in temporary_rule_rows:
        rule = await db.get(ContinuityRule, int(cast(int, row["id"])))
        if rule is None or _rule_snapshot(rule) != row:
            raise MigrationInvariantError(
                f"rollback failed to restore exact temporary rule {row['id']}"
            )

    source_restored_ids = {int(cast(int, row["id"])) for row in source_rows}
    if source_restored_ids:
        for row in snapshot.get("reused_standalone_rules", []):
            rule = await db.get(ContinuityRule, int(cast(int, row["id"])))
            if rule is None or _rule_snapshot(rule) != row:
                raise MigrationInvariantError(
                    f"reusable standalone rule {row['id']} was clobbered by the "
                    "legacy dependency sync trigger during rollback; "
                    "refusing automatic rollback"
                )
        source_linked_mirrors = list(
            (
                await db.execute(
                    select(ContinuityRule).where(
                        ContinuityRule.legacy_dependency_id.in_(source_restored_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for rule in source_linked_mirrors:
            await db.delete(rule)
        await db.flush()
        remaining_source_linked_ids = list(
            (
                await db.execute(
                    select(ContinuityRule.id).where(
                        ContinuityRule.legacy_dependency_id.in_(source_restored_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if remaining_source_linked_ids:
            raise MigrationInvariantError(
                "rollback left legacy dependency sync-trigger mirror rules "
                f"attached to restored source dependencies: {remaining_source_linked_ids}"
            )

    await refresh_user_blocked_status(spec.user_id, db)
    await db.flush()

    restored_dependency_ids = set(
        (
            await db.execute(
                select(Dependency.id).where(Dependency.id.in_(dependency_ids))
            )
        )
        .scalars()
        .all()
    )
    if restored_dependency_ids != dependency_ids:
        raise MigrationInvariantError(
            "rollback failed to restore legacy dependencies: "
            f"{sorted(restored_dependency_ids)}"
        )

    ordered_membership_count = await db.scalar(
        select(DependencyGroupMembership.id)
        .where(
            DependencyGroupMembership.group_id == spec.dependency_group_id,
            DependencyGroupMembership.sequence_order.is_not(None),
        )
        .limit(1)
    )
    if ordered_membership_count is not None:
        raise MigrationInvariantError(
            "dependency group gained ordered memberships during rollback"
        )

    issue_ids = _achieve_node_issue_ids(snapshot)
    factual = await _factual_snapshot(db, spec=spec, ordered_issue_ids=issue_ids)
    before_factual = snapshot["factual"]
    for key in ("issue_state_hash", "thread_state_hash", "event_state_hash", "identity_state_hash"):
        if factual[key] != before_factual[key]:
            raise MigrationInvariantError(
                f"rollback changed protected factual state: {key}"
            )

    affected_thread_ids = {
        int(cast(int, thread_id))
        for thread_id in snapshot["runtime_behavior"]["affected_thread_ids"]
    }
    roll_ids = {thread.id for thread in await get_roll_pool(spec.user_id, db)}
    affected_eligible = sorted(roll_ids & affected_thread_ids)
    preflight_eligible = snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ]
    if affected_eligible != preflight_eligible:
        raise MigrationInvariantError(
            "affected Roll-eligible thread set was not restored exactly: "
            f"preflight={preflight_eligible}, now={affected_eligible}"
        )

    return {
        "removed_plan_id": plan_id,
        "restored_dependency_ids": sorted(dependency_ids),
        "restored_source_dependency_count": len(source_rows),
        "restored_temporary_dependency_count": len(temporary_rows),
        "restored_temporary_rule_ids": sorted(restored_rule_ids),
        "factual": factual,
        "affected_roll_eligible_thread_ids": affected_eligible,
    }