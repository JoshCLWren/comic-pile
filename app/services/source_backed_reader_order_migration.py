"""Generic Step 27 migration for source-backed reader-order debt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanNode,
    ContinuityPlanWrite,
)
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.continuity_graph import issue_readiness, load_snapshot
from app.services.continuity_plan_writer import replace_compiled_rules, validate_node_ownership
from app.services.ultimate_universe_production_migration import (
    MigrationInvariantError,
    _build_plan,
    _derive_gap_bridges,
    _factual_snapshot,
    _legacy_prefix,
    _plan_fingerprint,
    _plan_fingerprint_from_payload,
    _planned_rule_descriptor,
    _planned_rules,
    _resolved_entries,
    _rule_snapshot,
    _rules_fingerprint,
    _stable_hash,
)
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_roll_pool


@dataclass(frozen=True)
class SourceBackedReaderOrderSpec:
    """Frozen manifest describing one source-backed reader-order migration."""

    user_id: int
    source_list_id: int
    dependency_group_id: int
    expected_content_hash: str
    expected_positions: int
    plan_name: str
    expected_source_path: str | None = None
    reader_order_dependency_ids: tuple[int, ...] = ()


PRODUCTION_ABSOLUTE_UNIVERSE_SPEC = SourceBackedReaderOrderSpec(
    user_id=1,
    source_list_id=11,
    dependency_group_id=14,
    expected_content_hash=(
        "2ec0db202a62e3ac966fee17b45af6cb46a9e91b00889057d737cd566285e3d6"
    ),
    expected_positions=76,
    plan_name="Absolute Universe",
    expected_source_path="DC/Events/CBH/Absolute Universe Reading Order.cbl",
    reader_order_dependency_ids=(
        1296,
        1297,
        1301,
        1588,
        1607,
        1608,
        1834,
        1836,
        1837,
        1839,
        1840,
        1841,
        1843,
        1844,
        1845,
    ),
)


def _dep(dep: Dependency) -> dict[str, object]:
    return {
        "id": dep.id,
        "source_issue_id": dep.source_issue_id,
        "target_issue_id": dep.target_issue_id,
        "note": dep.note,
        "created_at": dep.created_at.isoformat(),
    }


def _require_clean(snapshot: dict[str, Any]) -> None:
    if snapshot.get("ok") is not True or not snapshot.get("snapshot_token"):
        raise MigrationInvariantError(
            f"snapshot is not clean: {snapshot.get('errors')!r}"
        )


async def build_source_backed_reader_order_dry_run(
    db: AsyncSession,
    spec: SourceBackedReaderOrderSpec,
) -> dict[str, Any]:
    """Build a deterministic read-only migration snapshot for one manifest."""
    errors: list[str] = []
    source = await db.get(CBLSourceList, spec.source_list_id)
    if source is None or not source.active:
        return {
            "ok": False,
            "errors": ["source missing or inactive"],
            "snapshot_token": None,
        }
    if source.content_hash != spec.expected_content_hash:
        errors.append("source content hash changed")
    if spec.expected_source_path and source.source_path != spec.expected_source_path:
        errors.append("source path changed")

    group = await db.scalar(
        select(DependencyGroup).where(
            DependencyGroup.id == spec.dependency_group_id,
            DependencyGroup.user_id == spec.user_id,
        )
    )
    if group is None:
        return {
            "ok": False,
            "errors": ["dependency group missing"],
            "snapshot_token": None,
        }

    memberships = list(
        (
            await db.execute(
                select(DependencyGroupMembership).where(
                    DependencyGroupMembership.group_id == group.id
                )
            )
        )
        .scalars()
        .all()
    )
    member_issue_ids = {
        membership.issue_id
        for membership in memberships
        if membership.issue_id is not None
    }
    ordered_membership_ids = [
        membership.id
        for membership in memberships
        if membership.sequence_order is not None
    ]
    if ordered_membership_ids:
        errors.append(
            f"sequence_order unexpectedly populated: {ordered_membership_ids}"
        )

    report = await reconcile_cbl_source_list(
        db,
        user_id=spec.user_id,
        list_id=spec.source_list_id,
        baseline_member_issue_ids=tuple(sorted(member_issue_ids)),
    )
    entries = _resolved_entries(report.entries)
    issue_ids = [int(cast(int, entry["resolved_issue_id"])) for entry in entries]
    issue_set = set(issue_ids)
    if (
        report.total_positions != spec.expected_positions
        or len(entries) != spec.expected_positions
    ):
        errors.append(
            f"expected {spec.expected_positions} resolved positions; "
            f"got total={report.total_positions}, resolved={len(entries)}"
        )
    if (
        report.unresolved_count
        or report.ambiguous_count
        or len(issue_ids) != len(issue_set)
    ):
        errors.append("source reconciliation is unresolved, ambiguous, or duplicate")
    missing_group = sorted(issue_set - member_issue_ids)
    if missing_group:
        errors.append(f"source issues missing from dependency group: {missing_group}")

    overlaps: list[dict[str, object]] = []
    user_plans = (
        await db.execute(
            select(ContinuityPlan).where(ContinuityPlan.user_id == spec.user_id)
        )
    ).scalars()
    for plan in user_plans:
        refs = {
            int(node.get("ref_id", 0))
            for node in plan.nodes_json or []
            if node.get("node_type") == "issue"
        }
        if refs & issue_set:
            overlaps.append(
                {
                    "id": plan.id,
                    "name": plan.name,
                    "overlap_count": len(refs & issue_set),
                }
            )
    if overlaps:
        errors.append(f"existing Reading Plan overlap: {overlaps}")

    prefix = _legacy_prefix(source.content_hash)
    source_deps = list(
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
    escaping = [
        dependency.id
        for dependency in source_deps
        if dependency.source_issue_id not in issue_set
        or dependency.target_issue_id not in issue_set
    ]
    if escaping:
        errors.append(f"source dependencies escape source set: {escaping}")

    explicit_deps: list[Dependency] = []
    if spec.reader_order_dependency_ids:
        explicit_deps = list(
            (
                await db.execute(
                    select(Dependency)
                    .where(Dependency.id.in_(spec.reader_order_dependency_ids))
                    .order_by(Dependency.id)
                )
            )
            .scalars()
            .all()
        )
        missing = sorted(
            set(spec.reader_order_dependency_ids)
            - {dependency.id for dependency in explicit_deps}
        )
        if missing:
            errors.append(f"classified reader-order dependencies missing: {missing}")

    removal_ids = {
        dependency.id for dependency in [*source_deps, *explicit_deps]
    }
    removed_rules = (
        list(
            (
                await db.execute(
                    select(ContinuityRule)
                    .where(
                        ContinuityRule.user_id == spec.user_id,
                        ContinuityRule.legacy_dependency_id.in_(removal_ids),
                    )
                    .order_by(ContinuityRule.id)
                )
            )
            .scalars()
            .all()
        )
        if removal_ids
        else []
    )
    removed_rule_ids = {rule.id for rule in removed_rules}

    graph = await load_snapshot(db, spec.user_id)
    positions = {
        int(cast(int, entry["resolved_issue_id"])): int(
            cast(int, entry["cbl_position"])
        )
        for entry in entries
    }
    explicit_semantics: list[dict[str, object]] = []
    for dependency in explicit_deps:
        source_issue = graph.issues.get(dependency.source_issue_id)
        target_issue = graph.issues.get(dependency.target_issue_id)
        live = (
            source_issue is not None
            and target_issue is not None
            and source_issue.status != "read"
            and target_issue.status != "read"
        )
        implied = (
            dependency.source_issue_id in positions
            and dependency.target_issue_id in positions
            and positions[dependency.source_issue_id]
            < positions[dependency.target_issue_id]
        )
        if live and not implied:
            errors.append(
                f"live reader-order dependency {dependency.id} "
                "is not implied by source plan"
            )
        explicit_semantics.append(
            {
                **_dep(dependency),
                "source_status": None if source_issue is None else source_issue.status,
                "target_status": None if target_issue is None else target_issue.status,
                "live": live,
                "implied_by_plan": implied,
            }
        )

    bridges = _derive_gap_bridges(entries)
    lanes, nodes = _build_plan(
        entries,
        source_path=report.source_path or source.source_path,
        bridges=bridges,
    )
    planned_rules = _planned_rules(nodes, bridges)
    adjacency = {
        (int(rule["source_id"]), int(rule["target_id"]))
        for rule in planned_rules
        if rule["kind"] == "adjacent"
    }
    edge_rules = list(
        (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == spec.user_id,
                    ContinuityRule.source_type == "issue",
                    ContinuityRule.target_type == "issue",
                    ContinuityRule.source_id.in_(issue_set),
                    ContinuityRule.target_id.in_(issue_set),
                )
            )
        )
        .scalars()
        .all()
    )
    reusable: list[ContinuityRule] = []
    conflicts: list[ContinuityRule] = []
    for rule in edge_rules:
        if (rule.source_id, rule.target_id) not in adjacency:
            continue
        if rule.id in removed_rule_ids:
            continue
        is_reusable = (
            rule.satisfaction_type == "item_read"
            and not (rule.note or "").startswith("continuity-plan:")
            and rule.checkpoint_issue_id is None
            and not rule.convergence_targets
        )
        (reusable if is_reusable else conflicts).append(rule)
    if conflicts:
        errors.append(
            f"planned edges conflict with rules: {[rule.id for rule in conflicts]}"
        )

    factual = await _factual_snapshot(  # type: ignore[arg-type]
        db,
        spec=spec,
        ordered_issue_ids=issue_ids,
    )
    affected = [
        thread
        for thread in graph.threads.values()
        if thread.status == "active"
        and thread.queue_position >= 1
        and thread.next_unread_issue_id in issue_set
    ]
    affected_ids = {thread.id for thread in affected}
    next_ids = {
        thread.next_unread_issue_id
        for thread in affected
        if thread.next_unread_issue_id is not None
    }
    raw = (
        list(
            (
                await db.execute(
                    select(Dependency).where(Dependency.target_issue_id.in_(next_ids))
                )
            )
            .scalars()
            .all()
        )
        if next_ids
        else []
    )
    raw_by_target: dict[int, list[Dependency]] = {}
    for dependency in raw:
        raw_by_target.setdefault(dependency.target_issue_id, []).append(dependency)

    current_blocked = await _get_blocked_thread_ids_uncached(spec.user_id, db)
    current_roll = {thread.id for thread in await get_roll_pool(spec.user_id, db)}
    current_eligible = sorted(current_roll & affected_ids)
    if current_eligible != sorted(affected_ids - current_blocked):
        errors.append("persisted Roll eligibility differs from uncached unified blocking")

    planned_sources: dict[int, list[int]] = {}
    for rule in planned_rules:
        if rule["kind"] == "adjacent":
            planned_sources.setdefault(int(rule["target_id"]), []).append(
                int(rule["source_id"])
            )
        else:
            for target in cast(list[dict[str, int]], rule["convergence_targets"]):
                planned_sources.setdefault(int(rule["target_id"]), []).append(
                    int(target["id"])
                )

    future_blocked: set[int] = set()
    behavior: list[dict[str, object]] = []
    for thread in affected:
        next_issue_id = cast(int, thread.next_unread_issue_id)
        removed = [
            dependency.id
            for dependency in raw_by_target.get(next_issue_id, [])
            if dependency.id in removal_ids
            and graph.issues.get(dependency.source_issue_id)
            and graph.issues[dependency.source_issue_id].status != "read"
        ]
        other = [
            dependency.id
            for dependency in raw_by_target.get(next_issue_id, [])
            if dependency.id not in removal_ids
            and graph.issues.get(dependency.source_issue_id)
            and graph.issues[dependency.source_issue_id].status != "read"
        ]
        existing = [
            blocker.rule_id
            for blocker in issue_readiness(next_issue_id, graph)
            if blocker.rule_id not in removed_rule_ids
        ]
        planned = [
            source_id
            for source_id in planned_sources.get(next_issue_id, [])
            if graph.issues.get(source_id)
            and graph.issues[source_id].status != "read"
        ]
        blocked = bool(other or existing or planned)
        if blocked:
            future_blocked.add(thread.id)
        if removed and not blocked:
            errors.append(
                f"planned representation loses protection for next issue {next_issue_id}"
            )
        behavior.append(
            {
                "thread_id": thread.id,
                "next_unread_issue_id": next_issue_id,
                "removed_blocker_ids": removed,
                "other_blocker_ids": other,
                "existing_rule_ids": existing,
                "planned_source_ids": planned,
                "future_blocked": blocked,
            }
        )

    future_eligible = sorted(affected_ids - future_blocked)
    if future_eligible != current_eligible:
        errors.append(
            "affected Roll eligibility would change: "
            f"before={current_eligible}, after={future_eligible}"
        )

    plan_payload = {
        "name": spec.plan_name,
        "ordering_mode": "strict_sequential",
        "lanes": [lane.model_dump() for lane in lanes],
        "nodes": [node.model_dump() for node in nodes],
    }
    state: dict[str, object] = {
        "manifest": {
            "user_id": spec.user_id,
            "source_list_id": spec.source_list_id,
            "dependency_group_id": spec.dependency_group_id,
            "content_hash": spec.expected_content_hash,
            "expected_positions": spec.expected_positions,
            "plan_name": spec.plan_name,
            "reader_order_dependency_ids": list(spec.reader_order_dependency_ids),
        },
        "source": {
            "list_id": source.id,
            "source_path": source.source_path,
            "content_hash": source.content_hash,
            "revision_sha": source.revision_sha,
            "position_count": report.total_positions,
            "resolved_count": report.resolved_count,
            "unresolved_count": report.unresolved_count,
            "ambiguous_count": report.ambiguous_count,
            "first_unread_position": report.first_unread_position,
            "first_unread_issue_id": report.first_unread_issue_id,
        },
        "dependency_group": {
            "id": group.id,
            "membership_count": len(memberships),
            "ordered_membership_count": len(ordered_membership_ids),
            "extra_issue_ids": sorted(member_issue_ids - issue_set),
        },
        "factual": factual,
        "overlapping_plans": overlaps,
        "source_legacy_dependencies": [_dep(dependency) for dependency in source_deps],
        "explicit_reader_order_dependencies": explicit_semantics,
        "removed_linked_continuity_rules": [
            _rule_snapshot(rule) for rule in removed_rules
        ],
        "reused_standalone_rules": [_rule_snapshot(rule) for rule in reusable],
        "conflicting_rules": [_rule_snapshot(rule) for rule in conflicts],
        "historical_gap_bridges": bridges,
        "planned": {
            "plan": plan_payload,
            "rules": planned_rules,
            "adjacent_rule_count": max(len(nodes) - 1, 0),
            "gap_bridge_count": len(bridges),
            "reused_standalone_rule_count": len(reusable),
            "expected_new_plan_rule_count": (
                max(len(nodes) - 1, 0) - len(reusable) + len(bridges)
            ),
        },
        "runtime_behavior": {
            "affected_thread_ids": sorted(affected_ids),
            "current_affected_roll_eligible_thread_ids": current_eligible,
            "simulated_future_eligible_thread_ids": future_eligible,
            "rows": behavior,
        },
    }
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot_token": _stable_hash(state),
        **state,
    }


async def apply_source_backed_reader_order_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    spec: SourceBackedReaderOrderSpec,
) -> dict[str, Any]:
    """Apply one reviewed snapshot inside the caller-owned transaction."""
    _require_clean(snapshot)
    current = await build_source_backed_reader_order_dry_run(db, spec)
    if (
        current.get("snapshot_token") != snapshot["snapshot_token"]
        or current.get("ok") is not True
    ):
        raise MigrationInvariantError("live state changed since dry-run")

    removed_rows = [
        *snapshot["source_legacy_dependencies"],
        *snapshot["explicit_reader_order_dependencies"],
    ]
    removal_ids = [int(cast(int, row["id"])) for row in removed_rows]
    if removal_ids:
        result = await db.execute(
            delete(Dependency).where(Dependency.id.in_(removal_ids))
        )
        if getattr(result, "rowcount", None) != len(removal_ids):
            raise MigrationInvariantError("reader-order dependency delete count mismatch")
    await db.flush()

    if removal_ids:
        surviving = list(
            (
                await db.execute(
                    select(ContinuityRule.id).where(
                        ContinuityRule.legacy_dependency_id.in_(removal_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if surviving:
            raise MigrationInvariantError(
                f"dependency-linked rules survived deletion: {surviving}"
            )

    payload = dict(snapshot["planned"]["plan"])
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
    expected_count = int(
        cast(int, snapshot["planned"]["expected_new_plan_rule_count"])
    )
    if len(rules) != expected_count:
        raise MigrationInvariantError(
            f"expected {expected_count} plan rules, found {len(rules)}"
        )

    reusable_edges = {
        (int(cast(int, row["source_id"])), int(cast(int, row["target_id"])))
        for row in snapshot["reused_standalone_rules"]
    }
    expected = {
        _stable_hash(_planned_rule_descriptor(rule))
        for rule in snapshot["planned"]["rules"]
        if (
            int(cast(int, rule["source_id"])),
            int(cast(int, rule["target_id"])),
        )
        not in reusable_edges
    }
    actual = {
        _stable_hash(
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
    if expected != actual:
        raise MigrationInvariantError(
            "compiled rule semantics diverge from reviewed snapshot"
        )
    if _plan_fingerprint(plan) != _plan_fingerprint_from_payload(payload):
        raise MigrationInvariantError(
            "persisted Reading Plan diverges from reviewed snapshot"
        )

    ordered_membership = await db.scalar(
        select(DependencyGroupMembership.id)
        .where(
            DependencyGroupMembership.group_id == spec.dependency_group_id,
            DependencyGroupMembership.sequence_order.is_not(None),
        )
        .limit(1)
    )
    if ordered_membership is not None:
        raise MigrationInvariantError("sequence_order changed during migration")

    for row in snapshot["reused_standalone_rules"]:
        rule = await db.get(ContinuityRule, int(cast(int, row["id"])))
        if rule is None or _rule_snapshot(rule) != row:
            raise MigrationInvariantError(f"standalone rule {row['id']} changed")

    issue_ids = [
        int(cast(int, node["ref_id"])) for node in payload["nodes"]
    ]
    factual = await _factual_snapshot(  # type: ignore[arg-type]
        db,
        spec=spec,
        ordered_issue_ids=issue_ids,
    )
    for key in (
        "issue_state_hash",
        "thread_state_hash",
        "event_state_hash",
        "identity_state_hash",
    ):
        if factual[key] != snapshot["factual"][key]:
            raise MigrationInvariantError(f"protected reader state changed: {key}")

    affected_ids = {
        int(cast(int, thread_id))
        for thread_id in snapshot["runtime_behavior"]["affected_thread_ids"]
    }
    eligible = sorted(
        {thread.id for thread in await get_roll_pool(spec.user_id, db)} & affected_ids
    )
    if eligible != snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ]:
        raise MigrationInvariantError(
            "affected Roll eligibility changed after migration"
        )

    return {
        "plan_id": plan.id,
        "plan_marker": marker,
        "plan_fingerprint": _plan_fingerprint(plan),
        "plan_rule_count": len(rules),
        "plan_rule_fingerprint": _rules_fingerprint(rules),
        "expected_new_plan_rule_count": expected_count,
        "removed_source_dependency_count": len(snapshot["source_legacy_dependencies"]),
        "removed_explicit_reader_order_dependency_count": len(
            snapshot["explicit_reader_order_dependencies"]
        ),
        "removed_dependencies": removed_rows,
        "removed_linked_continuity_rules": snapshot[
            "removed_linked_continuity_rules"
        ],
        "reused_standalone_rule_count": len(snapshot["reused_standalone_rules"]),
        "affected_roll_eligible_thread_ids": eligible,
        "issue_state_hash": factual["issue_state_hash"],
        "thread_state_hash": factual["thread_state_hash"],
        "event_state_hash": factual["event_state_hash"],
        "identity_state_hash": factual["identity_state_hash"],
        "source_snapshot_token": snapshot["snapshot_token"],
        "rollback_note": (
            "Receipt contains every removed dependency/rule row; rollback remains "
            "manual and fail-closed under #2363."
        ),
    }
