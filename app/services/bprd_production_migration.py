"""Production-scoped B.P.R.D. Step 22 migration primitives.

This module converts the audited Plague of Frogs-era execution state from five
legacy dependency-owned edges into one strict canonical Reading Plan. Dry-run is
read-only. Apply requires the exact dry-run snapshot token. Rollback requires an
apply receipt and refuses to overwrite a Reading Plan edited after cutover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode
from app.services.continuity_plan_writer import (
    replace_compiled_rules,
    validate_node_ownership,
)
from comic_pile.dependencies import refresh_user_blocked_status


class MigrationInvariantError(RuntimeError):
    """Raised when live state no longer matches the reviewed migration contract."""


@dataclass(frozen=True)
class IssueExpectation:
    """One audited canonical issue used by the migration."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    status: str


@dataclass(frozen=True)
class ThreadExpectation:
    """One audited thread-state invariant at migration time."""

    thread_id: int
    title: str
    status: str
    is_blocked: bool
    next_unread_issue_id: int | None
    issues_remaining: int
    reading_progress: str


@dataclass(frozen=True)
class LegacyEdgeExpectation:
    """One legacy dependency and its linked continuity-rule row."""

    dependency_id: int
    rule_id: int
    source_issue_id: int
    target_issue_id: int
    note: str | None


@dataclass(frozen=True)
class BPRDMigrationSpec:
    """All reviewed identities required to perform one scoped migration."""

    user_id: int
    plan_name: str
    issues: tuple[IssueExpectation, ...]
    threads: tuple[ThreadExpectation, ...]
    legacy_edges: tuple[LegacyEdgeExpectation, ...]
    dependency_group_id: int

    @property
    def issue_ids(self) -> tuple[int, ...]:
        """Return canonical Reading Plan order."""
        return tuple(issue.issue_id for issue in self.issues)

    @property
    def thread_ids(self) -> tuple[int, ...]:
        """Return the audited B.P.R.D. thread IDs."""
        return tuple(thread.thread_id for thread in self.threads)


PRODUCTION_BPRD_SPEC = BPRDMigrationSpec(
    user_id=1,
    plan_name="B.P.R.D.",
    issues=(
        IssueExpectation(25035, 3382, "B.P.R.D.: PLAGUE OF FROGS", "1", "read"),
        IssueExpectation(25036, 3382, "B.P.R.D.: PLAGUE OF FROGS", "2", "read"),
        IssueExpectation(25037, 3382, "B.P.R.D.: PLAGUE OF FROGS", "3", "read"),
        IssueExpectation(25038, 3382, "B.P.R.D.: PLAGUE OF FROGS", "4", "read"),
        IssueExpectation(25039, 3382, "B.P.R.D.: PLAGUE OF FROGS", "5", "read"),
        IssueExpectation(25040, 3383, "B.P.R.D.: THE DEAD", "1", "read"),
        IssueExpectation(25041, 3383, "B.P.R.D.: THE DEAD", "2", "read"),
        IssueExpectation(25042, 3383, "B.P.R.D.: THE DEAD", "3", "read"),
        IssueExpectation(25043, 3383, "B.P.R.D.: THE DEAD", "4", "read"),
        IssueExpectation(25044, 3383, "B.P.R.D.: THE DEAD", "5", "read"),
        IssueExpectation(25045, 3383, "B.P.R.D.: THE DEAD", "6", "read"),
        IssueExpectation(25046, 3384, "B.P.R.D.: THE BLACK FLAME", "1", "read"),
        IssueExpectation(25052, 3385, "B.P.R.D.: WAR ON FROGS", "1", "read"),
        IssueExpectation(25056, 3385, "B.P.R.D.: WAR ON FROGS", "Revival", "read"),
        IssueExpectation(25053, 3385, "B.P.R.D.: WAR ON FROGS", "2", "read"),
        IssueExpectation(25055, 3385, "B.P.R.D.: WAR ON FROGS", "4", "read"),
        IssueExpectation(25047, 3384, "B.P.R.D.: THE BLACK FLAME", "2", "unread"),
        IssueExpectation(25048, 3384, "B.P.R.D.: THE BLACK FLAME", "3", "unread"),
        IssueExpectation(25049, 3384, "B.P.R.D.: THE BLACK FLAME", "4", "unread"),
        IssueExpectation(25050, 3384, "B.P.R.D.: THE BLACK FLAME", "5", "unread"),
        IssueExpectation(25051, 3384, "B.P.R.D.: THE BLACK FLAME", "6", "unread"),
        IssueExpectation(25054, 3385, "B.P.R.D.: WAR ON FROGS", "3", "unread"),
    ),
    threads=(
        ThreadExpectation(
            3382,
            "B.P.R.D.: PLAGUE OF FROGS",
            "completed",
            False,
            None,
            0,
            "completed",
        ),
        ThreadExpectation(
            3383,
            "B.P.R.D.: THE DEAD",
            "completed",
            False,
            None,
            0,
            "completed",
        ),
        ThreadExpectation(
            3384,
            "B.P.R.D.: THE BLACK FLAME",
            "active",
            False,
            25047,
            5,
            "in_progress",
        ),
        ThreadExpectation(
            3385,
            "B.P.R.D.: WAR ON FROGS",
            "active",
            True,
            25054,
            1,
            "in_progress",
        ),
    ),
    legacy_edges=(
        LegacyEdgeExpectation(1358, 117, 25039, 25040, None),
        LegacyEdgeExpectation(1359, 125, 25045, 25046, None),
        LegacyEdgeExpectation(1360, 625, 25046, 25052, None),
        LegacyEdgeExpectation(
            1575,
            626,
            25055,
            25047,
            "B.P.R.D. Plague of Frogs omnibus interleave: "
            "War on Frogs #4 before The Black Flame #2",
        ),
        LegacyEdgeExpectation(
            1576,
            627,
            25051,
            25054,
            "B.P.R.D. Plague of Frogs omnibus interleave: "
            "The Black Flame #6 before War on Frogs #3",
        ),
    ),
    dependency_group_id=9,
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


def _plan_nodes(spec: BPRDMigrationSpec) -> list[ContinuityPlanNode]:
    return [
        ContinuityPlanNode(
            id=f"issue-{issue_id}",
            node_type="issue",
            ref_id=issue_id,
            lane_id="main",
            position=position,
        )
        for position, issue_id in enumerate(spec.issue_ids)
    ]


def _plan_lanes() -> list[ContinuityPlanLane]:
    return [ContinuityPlanLane(id="main", name="Reading order", order=0)]


def _plan_fingerprint(plan: ContinuityPlan) -> str:
    return _stable_hash(
        {
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "nodes": plan.nodes_json,
            "lanes": plan.lanes_json,
        }
    )


def _planned_edges(spec: BPRDMigrationSpec) -> list[tuple[int, int]]:
    return list(zip(spec.issue_ids, spec.issue_ids[1:], strict=False))


def _detect_cycle(
    existing_rules: list[ContinuityRule],
    *,
    removed_rule_ids: set[int],
    new_edges: list[tuple[int, int]],
) -> tuple[int, int] | None:
    graph: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for rule in existing_rules:
        if rule.id in removed_rule_ids or rule.satisfaction_type == "converged":
            continue
        source = (rule.source_type, rule.source_id)
        target = (rule.target_type, rule.target_id)
        if source != target:
            graph.setdefault(source, set()).add(target)

    def reaches(start: tuple[str, int], wanted: tuple[str, int]) -> bool:
        stack = [start]
        visited: set[tuple[str, int]] = set()
        while stack:
            node = stack.pop()
            if node == wanted:
                return True
            if node in visited:
                continue
            visited.add(node)
            stack.extend(graph.get(node, ()))
        return False

    for source_id, target_id in new_edges:
        source = ("issue", source_id)
        target = ("issue", target_id)
        if reaches(target, source):
            return source_id, target_id
        graph.setdefault(source, set()).add(target)
    return None


async def _factual_snapshot(
    db: AsyncSession,
    spec: BPRDMigrationSpec,
) -> dict[str, Any]:
    issue_rows = (
        await db.execute(
            select(Issue, Thread)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Issue.id.in_(spec.issue_ids))
        )
    ).all()
    issues_by_id = {issue.id: (issue, thread) for issue, thread in issue_rows}
    issues = []
    for issue_id in spec.issue_ids:
        row = issues_by_id.get(issue_id)
        if row is None:
            continue
        issue, thread = row
        issues.append(
            {
                "id": issue.id,
                "thread_id": issue.thread_id,
                "thread_title": thread.title,
                "issue_number": issue.issue_number,
                "status": issue.status,
                "read_at": _json_value(issue.read_at),
                "position": issue.position,
            }
        )

    thread_rows = (
        await db.execute(select(Thread).where(Thread.id.in_(spec.thread_ids)))
    ).scalars().all()
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
        }
        for thread in sorted(thread_rows, key=lambda row: row.id)
    ]

    event_rows = (
        await db.execute(
            select(Event).where(
                or_(
                    Event.issue_id.in_(spec.issue_ids),
                    Event.thread_id.in_(spec.thread_ids),
                    Event.selected_thread_id.in_(spec.thread_ids),
                )
            )
        )
    ).scalars().all()
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

    mapping_rows = (
        await db.execute(
            select(IssueExternalIdentityMapping, ExternalIdentity)
            .join(
                ExternalIdentity,
                ExternalIdentity.id
                == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(IssueExternalIdentityMapping.issue_id.in_(spec.issue_ids))
        )
    ).all()
    identities = [
        {
            "mapping_id": mapping.id,
            "issue_id": mapping.issue_id,
            "status": mapping.status,
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


async def build_bprd_dry_run(
    db: AsyncSession,
    spec: BPRDMigrationSpec = PRODUCTION_BPRD_SPEC,
) -> dict[str, Any]:
    """Inspect exact migration preconditions without performing writes."""
    errors: list[str] = []
    factual = await _factual_snapshot(db, spec)

    issue_rows = {row["id"]: row for row in factual["issues"]}
    for expected in spec.issues:
        actual = issue_rows.get(expected.issue_id)
        if actual is None:
            errors.append(f"missing issue {expected.issue_id}")
            continue
        expected_shape = (
            expected.thread_id,
            expected.thread_title,
            expected.issue_number,
            expected.status,
        )
        actual_shape = (
            actual["thread_id"],
            actual["thread_title"],
            actual["issue_number"],
            actual["status"],
        )
        if actual_shape != expected_shape:
            errors.append(
                f"issue {expected.issue_id} changed: "
                f"expected {expected_shape!r}, got {actual_shape!r}"
            )

    thread_rows = {row["id"]: row for row in factual["threads"]}
    for expected in spec.threads:
        actual = thread_rows.get(expected.thread_id)
        if actual is None:
            errors.append(f"missing thread {expected.thread_id}")
            continue
        expected_shape = (
            expected.title,
            expected.status,
            expected.is_blocked,
            expected.next_unread_issue_id,
            expected.issues_remaining,
            expected.reading_progress,
        )
        actual_shape = (
            actual["title"],
            actual["status"],
            actual["is_blocked"],
            actual["next_unread_issue_id"],
            actual["issues_remaining"],
            actual["reading_progress"],
        )
        if actual_shape != expected_shape:
            errors.append(
                f"thread {expected.thread_id} changed: "
                f"expected {expected_shape!r}, got {actual_shape!r}"
            )

    user_plans = (
        await db.execute(
            select(ContinuityPlan).where(ContinuityPlan.user_id == spec.user_id)
        )
    ).scalars().all()
    overlapping_plans = []
    expected_issue_ids = set(spec.issue_ids)
    for plan in user_plans:
        referenced = {
            int(node.get("ref_id", 0))
            for node in plan.nodes_json
            if node.get("node_type") == "issue"
        }
        if plan.name == spec.plan_name or referenced & expected_issue_ids:
            overlapping_plans.append(
                {
                    "id": plan.id,
                    "name": plan.name,
                    "ordering_mode": plan.ordering_mode,
                }
            )
    if overlapping_plans:
        errors.append(
            f"B.P.R.D. Reading Plan already exists/overlaps: {overlapping_plans!r}"
        )

    dependency_ids = tuple(edge.dependency_id for edge in spec.legacy_edges)
    dependencies = (
        await db.execute(select(Dependency).where(Dependency.id.in_(dependency_ids)))
    ).scalars().all()
    dependencies_by_id = {row.id: row for row in dependencies}
    legacy_dependencies = []
    for expected in spec.legacy_edges:
        dependency = dependencies_by_id.get(expected.dependency_id)
        if dependency is None:
            errors.append(f"missing legacy dependency {expected.dependency_id}")
            continue
        actual_shape = (
            dependency.source_issue_id,
            dependency.target_issue_id,
            dependency.note,
        )
        expected_shape = (
            expected.source_issue_id,
            expected.target_issue_id,
            expected.note,
        )
        if actual_shape != expected_shape:
            errors.append(
                f"legacy dependency {expected.dependency_id} changed: "
                f"expected {expected_shape!r}, got {actual_shape!r}"
            )
        legacy_dependencies.append(
            {
                "id": dependency.id,
                "source_issue_id": dependency.source_issue_id,
                "target_issue_id": dependency.target_issue_id,
                "created_at": _json_value(dependency.created_at),
                "note": dependency.note,
            }
        )

    legacy_rule_rows = (
        await db.execute(
            select(ContinuityRule).where(
                ContinuityRule.legacy_dependency_id.in_(dependency_ids)
            )
        )
    ).scalars().all()
    legacy_rules_by_dependency = {
        row.legacy_dependency_id: row for row in legacy_rule_rows
    }
    legacy_rules = []
    for expected in spec.legacy_edges:
        rule = legacy_rules_by_dependency.get(expected.dependency_id)
        if rule is None:
            errors.append(
                f"missing linked continuity rule for dependency {expected.dependency_id}"
            )
            continue
        actual_shape = (
            rule.id,
            rule.source_type,
            rule.source_id,
            rule.target_type,
            rule.target_id,
            rule.satisfaction_type,
            rule.note,
        )
        expected_shape = (
            expected.rule_id,
            "issue",
            expected.source_issue_id,
            "issue",
            expected.target_issue_id,
            "item_read",
            expected.note,
        )
        if actual_shape != expected_shape:
            errors.append(
                f"legacy rule for dependency {expected.dependency_id} changed: "
                f"expected {expected_shape!r}, got {actual_shape!r}"
            )
        legacy_rules.append(
            {
                "id": rule.id,
                "user_id": rule.user_id,
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
        )

    group = (
        await db.execute(
            select(DependencyGroup).where(
                DependencyGroup.id == spec.dependency_group_id,
                DependencyGroup.user_id == spec.user_id,
            )
        )
    ).scalar_one_or_none()
    group_snapshot: dict[str, object] | None = None
    if group is None:
        errors.append(f"missing dependency group {spec.dependency_group_id}")
    else:
        memberships = (
            await db.execute(
                select(DependencyGroupMembership).where(
                    DependencyGroupMembership.group_id == group.id
                )
            )
        ).scalars().all()
        membership_issue_ids = {
            row.issue_id for row in memberships if row.issue_id is not None
        }
        ordered_count = sum(row.sequence_order is not None for row in memberships)
        if membership_issue_ids != expected_issue_ids:
            errors.append(
                f"dependency group {group.id} membership changed: "
                f"expected {sorted(expected_issue_ids)}, "
                f"got {sorted(membership_issue_ids)}"
            )
        if ordered_count:
            errors.append(
                f"dependency group {group.id} unexpectedly has "
                f"{ordered_count} ordered memberships"
            )
        group_snapshot = {
            "id": group.id,
            "name": group.name,
            "membership_count": len(memberships),
            "ordered_membership_count": ordered_count,
            "issue_ids": sorted(membership_issue_ids),
        }

    all_rules = (
        await db.execute(
            select(ContinuityRule).where(ContinuityRule.user_id == spec.user_id)
        )
    ).scalars().all()
    intended_edges = _planned_edges(spec)
    intended_edge_set = set(intended_edges)
    removable_rule_ids = {edge.rule_id for edge in spec.legacy_edges}
    for rule in all_rules:
        edge = (rule.source_id, rule.target_id)
        if (
            rule.source_type == "issue"
            and rule.target_type == "issue"
            and edge in intended_edge_set
            and rule.id not in removable_rule_ids
        ):
            errors.append(
                "plan-rule conflict on intended edge "
                f"{rule.source_id}->{rule.target_id}: rule {rule.id}"
            )
    cycle_edge = _detect_cycle(
        all_rules,
        removed_rule_ids=removable_rule_ids,
        new_edges=intended_edges,
    )
    if cycle_edge is not None:
        errors.append(
            "canonical plan would create continuity cycle at edge "
            f"{cycle_edge[0]}->{cycle_edge[1]}"
        )

    bprd_list_ids = set(
        (
            await db.execute(
                select(CBLSourceList.id).where(
                    CBLSourceList.active.is_(True),
                    or_(
                        CBLSourceList.name.ilike("%B.P.R.D.%"),
                        CBLSourceList.name.ilike("%BPRD%"),
                        CBLSourceList.source_path.ilike("%B.P.R.D.%"),
                        CBLSourceList.source_path.ilike("%BPRD%"),
                    ),
                )
            )
        ).scalars().all()
    )
    bprd_list_ids.update(
        (
            await db.execute(
                select(CBLSourceEntry.list_id)
                .join(CBLSourceList, CBLSourceList.id == CBLSourceEntry.list_id)
                .where(
                    CBLSourceList.active.is_(True),
                    or_(
                        CBLSourceEntry.series_name.ilike("%B.P.R.D.%"),
                        CBLSourceEntry.series_name.ilike("%Black Flame%"),
                        CBLSourceEntry.series_name.ilike("%War on Frogs%"),
                        CBLSourceEntry.series_name.ilike("%Universal Machine%"),
                        CBLSourceEntry.series_name.ilike("%Garden of Souls%"),
                        CBLSourceEntry.series_name.ilike("%Killing Ground%"),
                    ),
                )
                .distinct()
            )
        ).scalars().all()
    )

    nodes = _plan_nodes(spec)
    lanes = _plan_lanes()
    planned = {
        "name": spec.plan_name,
        "ordering_mode": "strict_sequential",
        "lanes": [lane.model_dump() for lane in lanes],
        "nodes": [node.model_dump() for node in nodes],
        "rule_edges": [
            {"source_issue_id": source, "target_issue_id": target}
            for source, target in intended_edges
        ],
    }
    state = {
        "factual": factual,
        "overlapping_plans": overlapping_plans,
        "legacy_dependencies": legacy_dependencies,
        "legacy_rules": legacy_rules,
        "dependency_group": group_snapshot,
        "bprd_source_list_ids": sorted(bprd_list_ids),
        "planned": planned,
    }
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot_token": _stable_hash(state),
        **state,
    }


def _require_snapshot(snapshot: dict[str, Any]) -> str:
    token = snapshot.get("snapshot_token")
    if not isinstance(token, str) or not token:
        raise MigrationInvariantError("dry-run snapshot is missing snapshot_token")
    if snapshot.get("ok") is not True:
        raise MigrationInvariantError(
            f"dry-run snapshot was not clean: {snapshot.get('errors')!r}"
        )
    return token


async def apply_bprd_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    spec: BPRDMigrationSpec = PRODUCTION_BPRD_SPEC,
) -> dict[str, Any]:
    """Apply the reviewed migration inside the caller's current transaction."""
    expected_token = _require_snapshot(snapshot)
    current = await build_bprd_dry_run(db, spec)
    if current["snapshot_token"] != expected_token:
        raise MigrationInvariantError(
            "live B.P.R.D. state changed since dry-run; generate a new snapshot"
        )
    if current["ok"] is not True:
        raise MigrationInvariantError(f"preflight failed: {current['errors']!r}")

    dependency_ids = tuple(edge.dependency_id for edge in spec.legacy_edges)
    result = await db.execute(
        delete(Dependency).where(Dependency.id.in_(dependency_ids))
    )
    if result.rowcount != len(dependency_ids):
        raise MigrationInvariantError(
            f"expected to remove {len(dependency_ids)} legacy dependencies, "
            f"removed {result.rowcount}"
        )
    await db.flush()

    nodes = _plan_nodes(spec)
    lanes = _plan_lanes()
    await validate_node_ownership(db, user_id=spec.user_id, nodes=nodes)
    plan = ContinuityPlan(
        user_id=spec.user_id,
        name=spec.plan_name,
        ordering_mode="strict_sequential",
        lanes_json=[lane.model_dump() for lane in lanes],
        nodes_json=[node.model_dump() for node in nodes],
    )
    db.add(plan)
    await db.flush()
    await replace_compiled_rules(
        db,
        user_id=spec.user_id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await refresh_user_blocked_status(spec.user_id, db)
    await db.flush()

    marker = f"continuity-plan:{plan.id}"
    plan_rules = (
        await db.execute(
            select(ContinuityRule)
            .where(
                ContinuityRule.user_id == spec.user_id,
                ContinuityRule.note == marker,
            )
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    if len(plan_rules) != len(spec.issue_ids) - 1:
        raise MigrationInvariantError(
            f"expected {len(spec.issue_ids) - 1} plan-owned rules, "
            f"found {len(plan_rules)}"
        )

    remaining_legacy = (
        await db.execute(
            select(Dependency.id).where(Dependency.id.in_(dependency_ids))
        )
    ).scalars().all()
    if remaining_legacy:
        raise MigrationInvariantError(
            f"legacy dependencies survived migration: {remaining_legacy}"
        )

    factual = await _factual_snapshot(db, spec)
    before_factual = snapshot["factual"]
    for key in ("issue_state_hash", "event_state_hash", "identity_state_hash"):
        if factual[key] != before_factual[key]:
            raise MigrationInvariantError(
                f"migration changed protected factual state: {key}"
            )

    return {
        "plan_id": plan.id,
        "plan_marker": marker,
        "plan_fingerprint": _plan_fingerprint(plan),
        "plan_rule_count": len(plan_rules),
        "issue_state_hash": factual["issue_state_hash"],
        "event_state_hash": factual["event_state_hash"],
        "identity_state_hash": factual["identity_state_hash"],
        "thread_state_hash": factual["thread_state_hash"],
        "source_snapshot_token": expected_token,
    }


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise MigrationInvariantError(f"expected ISO timestamp, got {value!r}")
    return datetime.fromisoformat(value)


async def rollback_bprd_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    receipt: dict[str, Any],
    spec: BPRDMigrationSpec = PRODUCTION_BPRD_SPEC,
) -> dict[str, Any]:
    """Restore the captured five-edge legacy state after a failed cutover."""
    _require_snapshot(snapshot)
    plan_id = receipt.get("plan_id")
    expected_fingerprint = receipt.get("plan_fingerprint")
    if not isinstance(plan_id, int) or not isinstance(expected_fingerprint, str):
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
    plan_rules = (
        await db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == spec.user_id,
                ContinuityRule.note == marker,
            )
        )
    ).scalars().all()
    if len(plan_rules) != len(spec.issue_ids) - 1:
        raise MigrationInvariantError(
            "plan-owned rule set changed after cutover; refusing automatic rollback"
        )

    dependency_ids = {edge.dependency_id for edge in spec.legacy_edges}
    edge_filters = [
        (Dependency.source_issue_id == edge.source_issue_id)
        & (Dependency.target_issue_id == edge.target_issue_id)
        for edge in spec.legacy_edges
    ]
    conflicting_dependencies = (
        await db.execute(
            select(Dependency).where(
                or_(Dependency.id.in_(dependency_ids), *edge_filters)
            )
        )
    ).scalars().all()
    if conflicting_dependencies:
        raise MigrationInvariantError(
            "legacy dependency IDs/edges are no longer free; "
            "refusing automatic rollback"
        )

    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == spec.user_id,
            ContinuityRule.note == marker,
        )
    )
    await db.delete(plan)
    await db.flush()

    legacy_dependencies = snapshot.get("legacy_dependencies")
    legacy_rules = snapshot.get("legacy_rules")
    if not isinstance(legacy_dependencies, list) or not isinstance(legacy_rules, list):
        raise MigrationInvariantError("dry-run snapshot lacks rollback rows")

    for row in legacy_dependencies:
        if not isinstance(row, dict):
            raise MigrationInvariantError("invalid dependency row in dry-run snapshot")
        db.add(
            Dependency(
                id=int(row["id"]),
                source_issue_id=int(row["source_issue_id"]),
                target_issue_id=int(row["target_issue_id"]),
                created_at=_parse_datetime(row["created_at"]),
                note=row.get("note"),
            )
        )
    await db.flush()

    for row in legacy_rules:
        if not isinstance(row, dict):
            raise MigrationInvariantError(
                "invalid continuity-rule row in dry-run snapshot"
            )
        db.add(
            ContinuityRule(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                legacy_dependency_id=int(row["legacy_dependency_id"]),
                source_type=str(row["source_type"]),
                source_id=int(row["source_id"]),
                target_type=str(row["target_type"]),
                target_id=int(row["target_id"]),
                satisfaction_type=str(row["satisfaction_type"]),
                checkpoint_issue_id=row.get("checkpoint_issue_id"),
                convergence_targets=row.get("convergence_targets"),
                note=row.get("note"),
                created_at=_parse_datetime(row["created_at"]),
                updated_at=_parse_datetime(row["updated_at"]),
            )
        )
    await db.flush()
    await refresh_user_blocked_status(spec.user_id, db)
    await db.flush()

    restored_ids = set(
        (
            await db.execute(
                select(Dependency.id).where(Dependency.id.in_(dependency_ids))
            )
        ).scalars().all()
    )
    if restored_ids != dependency_ids:
        raise MigrationInvariantError(
            "rollback failed to restore legacy dependencies: "
            f"{sorted(restored_ids)}"
        )

    return {
        "restored_dependency_ids": sorted(restored_ids),
        "removed_plan_id": plan_id,
        "factual": await _factual_snapshot(db, spec),
    }
