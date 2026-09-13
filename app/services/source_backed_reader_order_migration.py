"""Generic Step 27 migration for source-backed reader-order debt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import delete, or_, select
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
from app.services.explicit_reader_order_migration import (
    _explicit_classifications,
    _load_step14_index,
)
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
    _invalidate_continuity_snapshot,
    refresh_user_blocked_status,
)
from comic_pile.queue import get_roll_pool


@dataclass(frozen=True)
class SourceBackedReaderOrderSpec:
    """Frozen manifest describing one source-backed reader-order migration."""

    user_id: int
    expected_content_hash: str
    expected_positions: int
    plan_name: str
    source_list_id: int | None = None
    dependency_group_id: int | None = None
    expected_source_path: str | None = None
    reader_order_dependency_ids: tuple[int, ...] = ()
    classification_family_keys: tuple[str, ...] = ()


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
    classification_family_keys=("absolute_universe_reader_order",),
)


PRODUCTION_SOURCE_BACKED_SPECS: dict[str, SourceBackedReaderOrderSpec] = {
    "absolute-universe": PRODUCTION_ABSOLUTE_UNIVERSE_SPEC,
    "fantastic-four-early-years": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="d3f597e1027d4924d0b0f698c54bc78fa155e0f0a4921f85d6ceadedb204a327",
        expected_positions=288,
        plan_name="Fantastic Four 001 - Early Years",
        classification_family_keys=("lee_kirby_fantastic_four",),
    ),
    "ultimate-universe": SourceBackedReaderOrderSpec(
        user_id=1,
        source_list_id=12,
        dependency_group_id=15,
        expected_content_hash="d8944942bb6115ea9607ac6be0ac53e59368b90a929d44412900b3b9cae8b66a",
        expected_positions=130,
        plan_name="Ultimate Universe",
        classification_family_keys=("ultimate_universe_reader_order",),
    ),
    "x-men-era-ten": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="5a221581571c7d55083b15641e23d90112c0875d09c875065a78fbb77f117ec2",
        expected_positions=210,
        plan_name="Late-90s X-Men Reading Order",
        dependency_group_id=4,
        classification_family_keys=(
            "xmen_chronology_reader_order",
            "xmen_hunt_setup_reader_order",
        ),
    ),
    "wolverine": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="1e6b55e99d9317ba68782678710a3e621786c9f57afb1203f44154714acef9b8",
        expected_positions=599,
        plan_name="Wolverine no Events",
    ),
    "alpha-flight": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="be842ff688b9c8c5407308b9b9af82b59ed92df14d1c9cd1a83530a8549c4a32",
        expected_positions=228,
        plan_name="Alpha Flight",
    ),
    "new-gods": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="a028059e278535136625ffd4cc6c3a309e96c3473cd583598bed1183145c87f4",
        expected_positions=262,
        plan_name="The New Gods 001",
    ),
    "americas-best-comics": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="8fc8087894488c1899712d0fdb4195ab403747a57903b30d3cecf100fa906084",
        expected_positions=129,
        plan_name="America's Best Comics",
    ),
    "doom-patrol": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="3c28f4701b5f8d19e6c100253e97099c42088fc9412b83893551daace246c1c4",
        expected_positions=273,
        plan_name="Doom Patrol 1",
    ),
    "teen-titans": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="134c0f89208795c8af81a99baaf63dbe9e53bb6105c52c469200823b15325af6",
        expected_positions=389,
        plan_name="Teen Titans With Events",
    ),
    "supreme": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="ba6aea4858b09f3688e9fc864107c9be3f634c021fa53ea15dbfa119e8042aac",
        expected_positions=94,
        plan_name="Supreme Reading Order",
        classification_family_keys=("supreme_reader_order",),
    ),
    "unnamed-universe": SourceBackedReaderOrderSpec(
        user_id=1,
        expected_content_hash="bb54dfc094a2a7c469b6baa77f6751a8d30ea034ede24d686ba1ab4a968ae0ca",
        expected_positions=71,
        plan_name="The Unnamed Universe",
        dependency_group_id=16,
        expected_source_path="Image/Events/CBH/The Unnamed Universe Reading Order.cbl",
        classification_family_keys=("unnamed_universe_reader_order",),
    ),
}


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
    _invalidate_continuity_snapshot(spec.user_id, db)
    errors: list[str] = []
    if spec.source_list_id is None:
        matching_sources = list(
            (
                await db.execute(
                    select(CBLSourceList)
                    .where(CBLSourceList.content_hash == spec.expected_content_hash)
                    .order_by(CBLSourceList.id)
                )
            )
            .scalars()
            .all()
        )
        if len(matching_sources) != 1:
            return {
                "ok": False,
                "errors": [
                    "expected exactly one source with the manifest content hash; "
                    f"found {len(matching_sources)}"
                ],
                "snapshot_token": None,
            }
        source = matching_sources[0]
    else:
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

    group = None
    if spec.dependency_group_id is not None:
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

    memberships = (
        list(
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
        if group is not None
        else []
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
        list_id=source.id,
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
    if group is not None and missing_group:
        errors.append(f"source issues missing from dependency group: {missing_group}")

    if group is None and issue_set:
        memberships = list(
            (
                await db.execute(
                    select(DependencyGroupMembership)
                    .where(DependencyGroupMembership.issue_id.in_(issue_set))
                    .order_by(DependencyGroupMembership.id)
                )
            )
            .scalars()
            .all()
        )
        ordered_membership_ids = [
            membership.id
            for membership in memberships
            if membership.sequence_order is not None
        ]
        if ordered_membership_ids:
            errors.append(
                f"sequence_order unexpectedly populated: {ordered_membership_ids}"
            )

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

    prefixes = [_legacy_prefix(source.content_hash)]
    if spec.dependency_group_id is not None:
        prefixes.append(
            f"cbl-order:group-{spec.dependency_group_id}:{source.content_hash}:"
        )
    source_deps = list(
        (
            await db.execute(
                select(Dependency)
                .where(
                    or_(
                        *(Dependency.note.like(f"{prefix}%") for prefix in prefixes)
                    )
                )
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

    selected_explicit_ids = set(spec.reader_order_dependency_ids)
    if spec.classification_family_keys:
        _, families = _explicit_classifications(_load_step14_index())
        for family_key in spec.classification_family_keys:
            matches = families.get(family_key, [])
            if not matches:
                errors.append(f"Step 14 family is missing: {family_key}")
                continue
            for family in matches:
                if family["classification"] != "reading_plan_order":
                    errors.append(f"Step 14 family is not reading_plan_order: {family_key}")
                    continue
                selected_explicit_ids.update(int(value) for value in family["ids"])

    explicit_deps: list[Dependency] = []
    if selected_explicit_ids:
        explicit_deps = list(
            (
                await db.execute(
                    select(Dependency)
                    .where(Dependency.id.in_(selected_explicit_ids))
                    .order_by(Dependency.id)
                )
            )
            .scalars()
            .all()
        )
        missing = sorted(
            selected_explicit_ids
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
        endpoints_owned = source_issue is not None and target_issue is not None
        if not endpoints_owned:
            errors.append(
                f"classified reader-order dependency {dependency.id} has an "
                "endpoint outside user ownership"
            )
        live = (
            endpoints_owned
            and source_issue is not None
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
                "endpoints_owned": endpoints_owned,
                "source_status": None if source_issue is None else source_issue.status,
                "target_status": None if target_issue is None else target_issue.status,
                "live": live,
                "implied_by_plan": implied,
            }
        )

    classifications, _ = _explicit_classifications(_load_step14_index())
    touching_dependencies = (
        list(
            (
                await db.execute(
                    select(Dependency)
                    .where(
                        or_(
                            Dependency.source_issue_id.in_(issue_set),
                            Dependency.target_issue_id.in_(issue_set),
                        )
                    )
                    .order_by(Dependency.id)
                )
            )
            .scalars()
            .all()
        )
        if issue_set
        else []
    )
    needs_review = [
        dependency
        for dependency in touching_dependencies
        if classifications.get(dependency.id) == "needs_review"
    ]
    preserved_standalone = [
        dependency
        for dependency in touching_dependencies
        if classifications.get(dependency.id) == "standalone_prerequisite"
    ]
    if needs_review:
        errors.append(
            "needs_review dependencies touch this plan: "
            f"{[dependency.id for dependency in needs_review]}"
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

    factual = await _factual_snapshot(
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
            "source_list_id": source.id,
            "dependency_group_id": spec.dependency_group_id,
            "content_hash": spec.expected_content_hash,
            "expected_positions": spec.expected_positions,
            "plan_name": spec.plan_name,
            "reader_order_dependency_ids": list(spec.reader_order_dependency_ids),
            "classification_family_keys": list(spec.classification_family_keys),
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
            "id": None if group is None else group.id,
            "membership_ids": [membership.id for membership in memberships],
            "membership_count": len(memberships),
            "ordered_membership_count": len(ordered_membership_ids),
            "extra_issue_ids": sorted(member_issue_ids - issue_set),
        },
        "factual": factual,
        "overlapping_plans": overlaps,
        "source_legacy_dependencies": [_dep(dependency) for dependency in source_deps],
        "explicit_reader_order_dependencies": explicit_semantics,
        "preserved_standalone_dependencies": [
            _dep(dependency) for dependency in preserved_standalone
        ],
        "needs_review_dependencies": [_dep(dependency) for dependency in needs_review],
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

    membership_ids = [
        int(value) for value in snapshot["dependency_group"]["membership_ids"]
    ]
    ordered_membership = (
        await db.scalar(
            select(DependencyGroupMembership.id)
            .where(
                DependencyGroupMembership.id.in_(membership_ids),
                DependencyGroupMembership.sequence_order.is_not(None),
            )
            .limit(1)
        )
        if membership_ids
        else None
    )
    if ordered_membership is not None:
        raise MigrationInvariantError("sequence_order changed during migration")

    for row in snapshot["reused_standalone_rules"]:
        rule = await db.get(ContinuityRule, int(cast(int, row["id"])))
        if rule is None or _rule_snapshot(rule) != row:
            raise MigrationInvariantError(f"standalone rule {row['id']} changed")

    for row in snapshot["preserved_standalone_dependencies"]:
        dependency = await db.get(Dependency, int(row["id"]))
        if dependency is None or _dep(dependency) != row:
            raise MigrationInvariantError(
                f"standalone prerequisite {row['id']} changed"
            )

    issue_ids = [
        int(cast(int, node["ref_id"])) for node in payload["nodes"]
    ]
    factual = await _factual_snapshot(
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
        "preserved_standalone_dependency_count": len(
            snapshot["preserved_standalone_dependencies"]
        ),
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
