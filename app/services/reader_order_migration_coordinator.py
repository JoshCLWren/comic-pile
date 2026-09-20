"""Coordinator helpers for the one-shot Step 27 production migration."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.schemas.continuity_plan import (
    ContinuityPlanNode,
    ContinuityPlanWrite,
    ConvergenceGateTarget,
)
from app.services.continuity_plan_writer import (
    plan_rule_marker,
    replace_compiled_rules,
    validate_node_ownership,
)
from app.services.explicit_reader_order_migration import (
    ExplicitReaderOrderSpec,
    _explicit_classifications,
    _load_step14_index,
    _migration_contract,
    _planned_rule_descriptor as _explicit_planned_rule_descriptor,
    _resolve_selected_dependency_ids,
    _reviewed_step23b_writer_payloads,
    build_explicit_reader_order_dry_run,
)
from app.services.legacy_reading_order_production_migration import (
    _load_step23a_module,
    build_legacy_reading_order_dry_run,
    load_reviewed_step23a_contract,
    reviewed_reading_plan_order_rows,
)
from app.services.source_backed_reader_order_migration import (
    SourceBackedReaderOrderSpec,
    build_source_backed_reader_order_dry_run,
)
from app.services.migration_shared import (
    MigrationInvariantError,
    coerce_int,
    dep_snapshot as _dep,
    legacy_prefix as _legacy_prefix,
    plan_fingerprint as _plan_fingerprint,
    plan_fingerprint_from_payload as _plan_fingerprint_from_payload,
    planned_rule_descriptor as _planned_rule_descriptor,
    refresh_blocked_status,
    rule_descriptor as _rule_descriptor,
    stable_hash as _stable_hash,
)
from comic_pile.queue import get_roll_pool


LEGACY_READING_ORDERS_MANIFEST = "legacy-reading-orders"

def migration_report_status(report: dict[str, Any]) -> str:
    """Return the operator-facing classification for one manifest report."""
    if report.get("already_migrated") is True:
        return "already-migrated"
    if report.get("ok") is True:
        return "safe-to-migrate"
    errors = [str(error) for error in report.get("errors", [])]
    if any("needs_review" in error for error in errors):
        return "blocked-by-needs-review"
    if any(
        phrase in error
        for error in errors
        for phrase in (
            "Roll eligibility would change",
            "loses protection",
            "does not exactly reproduce",
        )
    ):
        return "behavior-mismatch"
    return "blocked-by-identity-or-source"


def manifest_reader_order_dependency_ids(report: dict[str, Any]) -> set[int]:
    """Return the exact classified dependency set declared by one report."""
    manifest = report.get("manifest")
    if isinstance(manifest, dict):
        raw_ids = manifest.get("resolved_reader_order_dependency_ids")
        if isinstance(raw_ids, list):
            return {
                dependency_id
                for dependency_id in raw_ids
                if isinstance(dependency_id, int) and not isinstance(dependency_id, bool)
            }

    overlap = report.get("dependency_overlap")
    if not isinstance(overlap, list):
        return set()
    return {
        coerce_int(row["dependency_id"])
        for row in overlap
        if isinstance(row, dict)
        and row.get("step14_classification") == "reading_plan_order"
        and isinstance(row.get("dependency_id"), int)
        and not isinstance(row.get("dependency_id"), bool)
    }


def _planned_issue_ids(report: dict[str, Any]) -> set[int]:
    """Return issue references in an explicit report's proposed plan."""
    planned = report.get("planned")
    if not isinstance(planned, dict):
        return set()
    plan = planned.get("plan")
    if not isinstance(plan, dict):
        return set()
    nodes = plan.get("nodes")
    if not isinstance(nodes, list):
        return set()
    return {
        coerce_int(node["ref_id"])
        for node in nodes
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and isinstance(node.get("ref_id"), int)
        and not isinstance(node.get("ref_id"), bool)
    }


def _legacy_target_issue_ids(report: dict[str, Any]) -> dict[str, set[int]]:
    """Return Step 23B target issue sets keyed by canonical plan name."""
    targets = report.get("proposed_canonical_targets")
    if not isinstance(targets, list):
        return {}
    result: dict[str, set[int]] = {}
    for target in targets:
        if not isinstance(target, dict):
            continue
        payload = target.get("writer_payload")
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        nodes = payload.get("nodes")
        if not isinstance(name, str) or not isinstance(nodes, list):
            continue
        result[name] = {
            coerce_int(node["ref_id"])
            for node in nodes
            if isinstance(node, dict)
            and node.get("node_type") == "issue"
            and isinstance(node.get("ref_id"), int)
            and not isinstance(node.get("ref_id"), bool)
        }
    return result


def _reviewed_step23b_dependency_ids() -> set[int]:
    """Return the nine Step 23A reading_plan_order IDs owned by Step 23B."""
    return {
        coerce_int(row["dependency_id"])
        for row in reviewed_reading_plan_order_rows(load_reviewed_step23a_contract())
    }


def _reviewed_step23b_target_issue_ids() -> dict[str, set[int]]:
    """Return Step 23B plan issue sets from the reviewed Step 23A contract."""
    evidence = load_reviewed_step23a_contract()
    return _legacy_target_issue_ids(
        {"proposed_canonical_targets": evidence.get("proposed_canonical_targets")}
    )


def reconcile_batch_manifest_reports(
    reports: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Plan exact Step 23B/explicit overlap without hiding residual debt."""
    legacy = reports.get(LEGACY_READING_ORDERS_MANIFEST)
    if legacy is None:
        return reports
    legacy_status = str(legacy.get("status") or "")
    if legacy_status not in {"safe-to-migrate", "already-migrated"}:
        return reports

    legacy_dependency_ids = manifest_reader_order_dependency_ids(legacy)
    legacy_targets = _legacy_target_issue_ids(legacy)
    # After Step 23B applies, live dependency_overlap no longer contains the
    # deleted reading_plan_order rows (and may contain unrelated residual rows).
    # Always recover the reviewed retire set for already-migrated resumes.
    if legacy_status == "already-migrated":
        legacy_dependency_ids = _reviewed_step23b_dependency_ids()
        if not legacy_targets:
            legacy_targets = _reviewed_step23b_target_issue_ids()
    if not legacy_dependency_ids or not legacy_targets:
        return reports
    all_legacy_issue_ids = set().union(*legacy_targets.values())

    reconciled = dict(reports)
    for manifest, report in reports.items():
        if manifest == LEGACY_READING_ORDERS_MANIFEST:
            continue
        # A blocked manifest is never promoted merely because another migration
        # happens to overlap some of its dependency IDs.
        if report.get("status") != "safe-to-migrate":
            continue
        explicit_dependency_ids = manifest_reader_order_dependency_ids(report)
        covered_ids = explicit_dependency_ids & legacy_dependency_ids
        if not covered_ids:
            continue

        planned = report.get("planned")
        plan = planned.get("plan") if isinstance(planned, dict) else None
        plan_name = plan.get("name") if isinstance(plan, dict) else None
        planned_issue_ids = _planned_issue_ids(report)
        target_issue_ids = legacy_targets.get(str(plan_name))
        if (
            target_issue_ids is None
            or not planned_issue_ids
            or not planned_issue_ids <= all_legacy_issue_ids
        ):
            errors = [str(error) for error in report.get("errors", [])]
            errors.append(
                "Step 23B targets do not contain the explicit plan's exact issue set"
            )
            reconciled[manifest] = {
                **report,
                "status": "behavior-mismatch",
                "ok": False,
                "errors": errors,
            }
            continue

        reconciled[manifest] = {
            **report,
            "apply_mode": "existing-plan-overlay",
            "covered_by": LEGACY_READING_ORDERS_MANIFEST,
            "covered_dependency_ids": sorted(covered_ids),
            "remaining_dependency_ids": sorted(explicit_dependency_ids - covered_ids),
            "overlay_added_issue_ids": sorted(planned_issue_ids - target_issue_ids),
        }
    return reconciled


def _expected_rules_from_plan_nodes(nodes: list[dict[str, Any]]) -> set[str]:
    """Project informational convergence rules from persisted plan nodes."""
    expected: set[str] = set()
    issue_ref_by_node_id = {
        node["id"]: node["ref_id"]
        for node in nodes
        if node.get("node_type") == "issue"
        and isinstance(node.get("id"), str)
        and isinstance(node.get("ref_id"), int)
    }
    for node in nodes:
        if node.get("node_type") != "issue":
            continue
        raw_ref = node.get("ref_id")
        if not isinstance(raw_ref, int):
            continue
        gate = node.get("convergence_gate") or []
        if not isinstance(gate, list) or not gate:
            continue
        source_ids: list[int] = []
        for target in gate:
            if not isinstance(target, dict):
                continue
            node_id = target.get("node_id")
            source_id = issue_ref_by_node_id.get(node_id) if isinstance(node_id, str) else None
            if source_id is None:
                continue
            source_ids.append(source_id)
        if not source_ids:
            continue
        expected.add(
            _stable_hash(
                _explicit_planned_rule_descriptor(
                    target_issue_id=raw_ref,
                    source_issue_ids=sorted(source_ids),
                )
            )
        )
    return expected


async def _plan_owned_rule_hashes(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    sort_convergence_targets: bool = False,
) -> set[str]:
    rules = list(
        (
            await db.execute(
                select(ContinuityRule)
                .where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.note == plan_rule_marker(plan_id),
                )
                .order_by(ContinuityRule.id)
            )
        )
        .scalars()
        .all()
    )
    hashes: set[str] = set()
    for rule in rules:
        descriptor = _rule_descriptor(rule)
        if sort_convergence_targets:
            targets = descriptor.get("convergence_targets") or []
            if isinstance(targets, list):
                descriptor = {
                    **descriptor,
                    "convergence_targets": sorted(
                        cast(list[dict[str, object]], targets),
                        key=lambda target: (str(target["type"]), coerce_int(target["id"])),
                    ),
                }
        hashes.add(_stable_hash(descriptor))
    return hashes


def _edges_from_plan_nodes(nodes: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """Return directed issue edges encoded by persisted convergence gates."""
    edges: set[tuple[int, int]] = set()
    issue_ref_by_node_id = {
        node["id"]: node["ref_id"]
        for node in nodes
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and isinstance(node.get("id"), str)
        and isinstance(node.get("ref_id"), int)
    }
    for node in nodes:
        if not isinstance(node, dict) or node.get("node_type") != "issue":
            continue
        raw_ref = node.get("ref_id")
        if not isinstance(raw_ref, int):
            continue
        gate = node.get("convergence_gate") or []
        if not isinstance(gate, list):
            continue
        for target in gate:
            if not isinstance(target, dict):
                continue
            node_id = target.get("node_id")
            source_id = issue_ref_by_node_id.get(node_id) if isinstance(node_id, str) else None
            if source_id is None:
                continue
            edges.add((source_id, raw_ref))
    return edges


def _groupless_expected_contract(
    spec: ExplicitReaderOrderSpec,
    plan: ContinuityPlan,
) -> tuple[set[int], set[tuple[int, int]]] | None:
    """Return expected issue/edge sets for a group-less explicit migration."""
    if spec.expected_issue_ids and spec.expected_edges:
        return set(spec.expected_issue_ids), set(spec.expected_edges)

    for lane in plan.lanes_json or []:
        if not isinstance(lane, dict):
            continue
        contract = lane.get("migration_contract")
        if not isinstance(contract, dict):
            continue
        if contract.get("kind") != "explicit_reader_order":
            continue
        raw_issues = contract.get("issue_ids")
        raw_edges = contract.get("edges")
        if not isinstance(raw_issues, list) or not isinstance(raw_edges, list):
            continue
        issue_ids = {int(issue_id) for issue_id in raw_issues if isinstance(issue_id, int)}
        edges: set[tuple[int, int]] = set()
        for edge in raw_edges:
            if (
                isinstance(edge, list | tuple)
                and len(edge) == 2
                and isinstance(edge[0], int)
                and isinstance(edge[1], int)
            ):
                edges.add((int(edge[0]), int(edge[1])))
        if issue_ids and edges:
            return issue_ids, edges
    return None


def _stamped_migration_contract(
    plan: ContinuityPlan,
) -> tuple[set[int], set[tuple[int, int]]] | None:
    """Read the server-owned issue/edge proof stamped during migration."""
    for lane in plan.lanes_json or []:
        if not isinstance(lane, dict):
            continue
        contract = lane.get("migration_contract")
        if not isinstance(contract, dict) or contract.get("kind") != "explicit_reader_order":
            continue
        raw_issues = contract.get("issue_ids")
        raw_edges = contract.get("edges")
        if not isinstance(raw_issues, list) or not isinstance(raw_edges, list):
            continue
        issues = {
            value
            for value in raw_issues
            if isinstance(value, int) and not isinstance(value, bool)
        }
        edges = {
            (edge[0], edge[1])
            for edge in raw_edges
            if isinstance(edge, list)
            and len(edge) == 2
            and isinstance(edge[0], int)
            and not isinstance(edge[0], bool)
            and isinstance(edge[1], int)
            and not isinstance(edge[1], bool)
        }
        if issues and edges:
            return issues, edges
    return None


async def _explicit_already_migrated(
    db: AsyncSession,
    spec: ExplicitReaderOrderSpec,
) -> bool:
    index = _load_step14_index()
    _, families = _explicit_classifications(index)
    selected_ids = _resolve_selected_dependency_ids(spec, by_family=families)
    if not selected_ids:
        return False
    remaining = await db.scalar(
        select(func.count()).select_from(Dependency).where(Dependency.id.in_(selected_ids))
    )
    if remaining != 0:
        return False
    plans = list(
        (
            await db.execute(
                select(ContinuityPlan).where(
                    ContinuityPlan.user_id == spec.user_id,
                    ContinuityPlan.name == spec.plan_name,
                )
            )
        )
        .scalars()
        .all()
    )
    if len(plans) != 1:
        return False
    plan = plans[0]
    nodes = list(plan.nodes_json or [])
    if not nodes or plan.ordering_mode != "informational":
        return False

    node_issue_ids = {
        coerce_int(node["ref_id"])
        for node in nodes
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and isinstance(node.get("ref_id"), int)
    }
    edges = _edges_from_plan_nodes(cast(list[dict[str, Any]], nodes))

    expected = _groupless_expected_contract(spec, plan)
    if expected is None:
        return False
    expected_issues, expected_edges = expected
    stamped = _stamped_migration_contract(plan)

    if stamped is not None:
        if stamped != expected:
            return False
        if spec.dependency_group_ids:
            # DependencyGroup membership is preserved compatibility state, not
            # canonical Reading Plan membership. Production groups can contain
            # unrelated members or omit cross-group edge endpoints, so replay
            # must validate the server-owned migration contract instead.
            if node_issue_ids != expected_issues:
                return False
            # Grouped plans must match the stamped edge set exactly. A superset
            # of classified edges would make Roll stricter than the Step 14
            # contract while still looking self-consistent after recompile.
            if edges != expected_edges:
                return False
        elif not expected_issues <= node_issue_ids or not expected_edges <= edges:
            # Step 23B overlay onto a larger reviewed baseline may retain
            # additional reviewed edges outside the explicit family contract.
            return False
    elif node_issue_ids != expected_issues or edges != expected_edges:
        return False

    expected_rules = _expected_rules_from_plan_nodes(cast(list[dict[str, Any]], nodes))
    actual = await _plan_owned_rule_hashes(
        db,
        user_id=spec.user_id,
        plan_id=plan.id,
        sort_convergence_targets=True,
    )
    return expected_rules == actual


async def apply_explicit_reader_order_overlay(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    spec: ExplicitReaderOrderSpec,
    covered_dependency_ids: set[int],
) -> dict[str, Any]:
    """Apply an explicit migration onto a Step 23B-created canonical plan.

    Callers must verify the complete dry-run snapshot against live state before
    Step 23B mutates the transaction. This path then re-checks residual
    dependency rows after that mutation.
    """
    if snapshot.get("ok") is not True or not snapshot.get("snapshot_token"):
        raise MigrationInvariantError(f"snapshot is not clean: {snapshot.get('errors')!r}")
    selected_rows = [
        cast(dict[str, object], row)
        for row in snapshot.get("selected_reader_order_dependencies", [])
        if isinstance(row, dict)
    ]
    selected_by_id = {
        coerce_int(row["id"]): row
        for row in selected_rows
        if isinstance(row.get("id"), int) and not isinstance(row.get("id"), bool)
    }
    selected_ids = set(selected_by_id)
    if not covered_dependency_ids or not covered_dependency_ids <= selected_ids:
        raise MigrationInvariantError(
            "overlay dependency coverage does not match the explicit snapshot"
        )
    remaining_ids = selected_ids - covered_dependency_ids

    live_dependencies = list(
        (
            await db.execute(
                select(Dependency)
                .where(Dependency.id.in_(selected_ids))
                .order_by(Dependency.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if {dependency.id for dependency in live_dependencies} != remaining_ids:
        raise MigrationInvariantError("Step 23B overlap or residual dependency state changed")
    for dependency in live_dependencies:
        expected = selected_by_id[dependency.id]
        live = _dep(dependency)
        if any(live[key] != expected.get(key) for key in live):
            raise MigrationInvariantError(
                f"residual dependency {dependency.id} changed since dry-run"
            )

    plans = list(
        (
            await db.execute(
                select(ContinuityPlan)
                .where(
                    ContinuityPlan.user_id == spec.user_id,
                    ContinuityPlan.name == spec.plan_name,
                    ContinuityPlan.ordering_mode == "informational",
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(plans) != 1:
        raise MigrationInvariantError(
            f"expected one Step 23B plan named {spec.plan_name!r}, found {len(plans)}"
        )
    plan = plans[0]
    reviewed_payload = _reviewed_step23b_writer_payloads().get(spec.plan_name)
    if reviewed_payload is not None:
        expected_fingerprint = _plan_fingerprint_from_payload(reviewed_payload)
        sealed = snapshot.get("existing_canonical_plan")
        if isinstance(sealed, dict):
            sealed_fingerprint = sealed.get("plan_fingerprint")
            if sealed_fingerprint != expected_fingerprint:
                raise MigrationInvariantError(
                    "recovered snapshot sealed a drifted Step 23B plan"
                )
            if _plan_fingerprint(plan) != sealed_fingerprint:
                raise MigrationInvariantError(
                    "Step 23B plan drifted since dry-run"
                )
        elif _plan_fingerprint(plan) != expected_fingerprint:
            raise MigrationInvariantError(
                "Step 23B plan does not match reviewed fingerprint"
            )
    existing_nodes = [ContinuityPlanNode.model_validate(node) for node in plan.nodes_json or []]
    existing_by_ref = {
        node.ref_id: node for node in existing_nodes if node.node_type == "issue"
    }

    planned = snapshot.get("planned")
    planned_payload = planned.get("plan") if isinstance(planned, dict) else None
    raw_planned_nodes = (
        planned_payload.get("nodes") if isinstance(planned_payload, dict) else None
    )
    if not isinstance(raw_planned_nodes, list):
        raise MigrationInvariantError("explicit overlay snapshot has no planned nodes")
    planned_nodes = [
        ContinuityPlanNode.model_validate(node)
        for node in raw_planned_nodes
        if isinstance(node, dict)
    ]
    planned_ref_by_id = {node.id: node.ref_id for node in planned_nodes}
    raw_lanes = list(plan.lanes_json or [])
    target_lane_id = raw_lanes[0].get("id") if raw_lanes else None
    if not isinstance(target_lane_id, str):
        raise MigrationInvariantError("Step 23B plan has no target lane for overlay nodes")
    used_node_ids = {node.id for node in existing_nodes}
    added_issue_ids: list[int] = []
    for planned_index, planned_node in enumerate(planned_nodes):
        if planned_node.ref_id in existing_by_ref:
            continue
        node_id = planned_node.id
        if node_id in used_node_ids:
            node_id = f"migration-overlay-{planned_node.ref_id}"
        if node_id in used_node_ids:
            raise MigrationInvariantError("explicit overlay node identifier collides")
        inserted = planned_node.model_copy(deep=True)
        inserted.id = node_id
        inserted.lane_id = target_lane_id
        inserted.convergence_gate = []

        previous = next(
            (
                existing_by_ref[candidate.ref_id]
                for candidate in reversed(planned_nodes[:planned_index])
                if candidate.ref_id in existing_by_ref
            ),
            None,
        )
        following = next(
            (
                existing_by_ref[candidate.ref_id]
                for candidate in planned_nodes[planned_index + 1 :]
                if candidate.ref_id in existing_by_ref
            ),
            None,
        )
        if previous is not None:
            insert_at = existing_nodes.index(previous) + 1
        elif following is not None:
            insert_at = existing_nodes.index(following)
        else:
            insert_at = len(existing_nodes)
        existing_nodes.insert(insert_at, inserted)
        existing_by_ref[inserted.ref_id] = inserted
        used_node_ids.add(inserted.id)
        added_issue_ids.append(inserted.ref_id)

    lane_position = 0
    for node in existing_nodes:
        if node.lane_id == target_lane_id:
            node.position = lane_position
            lane_position += 1

    for planned_node in planned_nodes:
        if not planned_node.convergence_gate:
            continue
        existing_node = existing_by_ref[planned_node.ref_id]
        translated: list[ConvergenceGateTarget] = []
        for target in planned_node.convergence_gate:
            target_ref = planned_ref_by_id.get(target.node_id)
            target_node = existing_by_ref.get(target_ref) if target_ref is not None else None
            if target_node is None:
                raise MigrationInvariantError(
                    "Step 23B plan is missing an explicit convergence target"
                )
            translated.append(
                ConvergenceGateTarget(
                    node_type=target_node.node_type,
                    node_id=target_node.id,
                )
            )
        if existing_node.convergence_gate and existing_node.convergence_gate != translated:
            raise MigrationInvariantError(
                "Step 23B plan already has different convergence semantics"
            )
        existing_node.convergence_gate = translated

    payload = {
        "name": plan.name,
        "ordering_mode": plan.ordering_mode,
        "lanes": list(plan.lanes_json or []),
        "nodes": [node.model_dump() for node in existing_nodes],
    }
    ContinuityPlanWrite.model_validate(payload)
    await validate_node_ownership(db, user_id=spec.user_id, nodes=existing_nodes)

    if remaining_ids:
        deleted = await db.execute(delete(Dependency).where(Dependency.id.in_(remaining_ids)))
        if getattr(deleted, "rowcount", None) != len(remaining_ids):
            raise MigrationInvariantError("explicit overlay dependency delete count mismatch")
    await db.flush()

    stamped_lanes = [dict(lane) for lane in plan.lanes_json or []]
    if not stamped_lanes:
        raise MigrationInvariantError("Step 23B plan has no lane for migration proof")
    stamped_lanes[0] = {
        **stamped_lanes[0],
        "migration_contract": _migration_contract(spec, selected_rows),
    }
    plan.lanes_json = stamped_lanes
    plan.nodes_json = [node.model_dump() for node in existing_nodes]
    await replace_compiled_rules(
        db,
        user_id=spec.user_id,
        plan=plan,
        nodes=existing_nodes,
        ordering_mode="informational",
    )
    await refresh_blocked_status(spec.user_id, db)
    await db.flush()

    expected_rules = {
        _stable_hash(rule)
        for rule in cast(list[dict[str, object]], snapshot["planned"]["rules"])
    }
    actual_rules = await _plan_owned_rule_hashes(
        db,
        user_id=spec.user_id,
        plan_id=plan.id,
        sort_convergence_targets=True,
    )
    if actual_rules != expected_rules:
        raise MigrationInvariantError(
            "overlay compiled rules diverge from the explicit snapshot"
        )

    affected_ids = {
        coerce_int(thread_id)
        for thread_id in snapshot["runtime_behavior"]["affected_thread_ids"]
    }
    eligible = sorted(
        {thread.id for thread in await get_roll_pool(spec.user_id, db)} & affected_ids
    )
    if eligible != snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ]:
        raise MigrationInvariantError(
            "affected Roll eligibility changed after explicit overlay"
        )

    return {
        "plan_id": plan.id,
        "plan_marker": plan_rule_marker(plan.id),
        "apply_mode": "existing-plan-overlay",
        "covered_dependency_ids": sorted(covered_dependency_ids),
        "overlay_added_issue_ids": sorted(added_issue_ids),
        "removed_reader_order_dependency_count": len(remaining_ids),
        "removed_dependencies": [selected_by_id[value] for value in sorted(remaining_ids)],
        "plan_rule_count": len(actual_rules),
        "affected_roll_eligible_thread_ids": eligible,
        "source_snapshot_token": snapshot["snapshot_token"],
    }



def _source_placement_count(plan: ContinuityPlan, source_path: str) -> int:
    count = 0
    for node in plan.nodes_json or []:
        placements = node.get("source_cbl_placements")
        if not isinstance(placements, list):
            continue
        count += sum(
            1
            for placement in placements
            if isinstance(placement, dict)
            and placement.get("source_path") == source_path
        )
    return count


async def _source_legacy_debt_cleared(
    db: AsyncSession,
    spec: SourceBackedReaderOrderSpec,
) -> bool:
    """Prove source-note and classified reader-order removal sets are empty."""
    prefixes = [_legacy_prefix(spec.expected_content_hash)]
    if spec.dependency_group_id is not None:
        prefixes.append(
            f"cbl-order:group-{spec.dependency_group_id}:{spec.expected_content_hash}:"
        )
    remaining_source = await db.scalar(
        select(func.count())
        .select_from(Dependency)
        .where(or_(*(Dependency.note.like(f"{prefix}%") for prefix in prefixes)))
    )
    if remaining_source != 0:
        return False

    selected_explicit_ids = set(spec.reader_order_dependency_ids)
    if spec.classification_family_keys:
        _, families = _explicit_classifications(_load_step14_index())
        for family_key in spec.classification_family_keys:
            matches = families.get(family_key, [])
            for family in matches:
                if family["classification"] != "reading_plan_order":
                    continue
                selected_explicit_ids.update(int(value) for value in family["ids"])
    if not selected_explicit_ids:
        return True
    remaining_explicit = await db.scalar(
        select(func.count())
        .select_from(Dependency)
        .where(Dependency.id.in_(selected_explicit_ids))
    )
    return remaining_explicit == 0


async def _source_already_migrated(
    db: AsyncSession,
    spec: SourceBackedReaderOrderSpec,
    report: dict[str, Any],
) -> bool:
    source = report.get("source")
    planned = report.get("planned")
    if not isinstance(source, dict) or not isinstance(planned, dict):
        return False
    source_path = source.get("source_path")
    plan_payload = planned.get("plan")
    planned_rules = planned.get("rules")
    if (
        not isinstance(source_path, str)
        or not isinstance(plan_payload, dict)
        or not isinstance(planned_rules, list)
    ):
        return False
    if not await _source_legacy_debt_cleared(db, spec):
        return False
    plans = list(
        (
            await db.execute(
                select(ContinuityPlan).where(
                    ContinuityPlan.user_id == spec.user_id,
                    ContinuityPlan.name == spec.plan_name,
                    ContinuityPlan.ordering_mode == "strict_sequential",
                )
            )
        )
        .scalars()
        .all()
    )
    if len(plans) != 1:
        return False
    plan = plans[0]
    if _source_placement_count(plan, source_path) != spec.expected_positions:
        return False
    if _plan_fingerprint(plan) != _plan_fingerprint_from_payload(plan_payload):
        return False

    reusable_edges = {
        (coerce_int(row["source_id"]), coerce_int(row["target_id"]))
        for row in report.get("reused_standalone_rules", [])
        if isinstance(row, dict)
    }
    expected = {
        _stable_hash(_planned_rule_descriptor(cast(dict[str, object], rule)))
        for rule in planned_rules
        if isinstance(rule, dict)
        and (
            coerce_int(rule["source_id"]),
            coerce_int(rule["target_id"]),
        )
        not in reusable_edges
    }
    actual = await _plan_owned_rule_hashes(db, user_id=spec.user_id, plan_id=plan.id)
    expected_count = planned.get("expected_new_plan_rule_count")
    if isinstance(expected_count, int) and len(actual) != expected_count:
        return False
    return expected == actual


async def _legacy_already_migrated(
    db: AsyncSession,
    report: dict[str, Any],
) -> bool:
    targets = report.get("proposed_canonical_targets")
    if not isinstance(targets, list) or len(targets) != 3:
        return False
    user_id = int(_load_step23a_module().USER_ID)
    for raw_target in targets:
        if not isinstance(raw_target, dict):
            return False
        payload = raw_target.get("writer_payload")
        if not isinstance(payload, dict):
            return False
        name = payload.get("name")
        if not isinstance(name, str):
            return False
        plans = list(
            (
                await db.execute(
                    select(ContinuityPlan).where(
                        ContinuityPlan.user_id == user_id,
                        ContinuityPlan.name == name,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(plans) != 1:
            return False
        plan = plans[0]
        if plan.ordering_mode != "informational":
            return False
        if _plan_fingerprint(plan) != _plan_fingerprint_from_payload(payload):
            return False
        owned = await _plan_owned_rule_hashes(db, user_id=user_id, plan_id=plan.id)
        if owned:
            return False

    evidence = load_reviewed_step23a_contract()
    retired_ids = [
        coerce_int(row["dependency_id"])
        for row in reviewed_reading_plan_order_rows(evidence)
    ]
    remaining = await db.scalar(
        select(func.count()).select_from(Dependency).where(Dependency.id.in_(retired_ids))
    )
    return remaining == 0


def _normalize_legacy_report(report: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when the reviewed Step 23A token no longer matches."""
    if report.get("ok") is True and report.get("snapshot_guard_passed") is not True:
        errors = [str(error) for error in report.get("errors", [])]
        errors.append("reviewed Step 23A snapshot token no longer matches")
        return {**report, "ok": False, "errors": errors}
    return report


async def _step23b_retire_set_applied(db: AsyncSession) -> bool:
    """Return True when Step 23B retire set and reviewed plan fingerprints hold."""
    retired_ids = sorted(_reviewed_step23b_dependency_ids())
    remaining = await db.scalar(
        select(func.count()).select_from(Dependency).where(Dependency.id.in_(retired_ids))
    )
    if remaining != 0:
        return False
    payloads = _reviewed_step23b_writer_payloads()
    if len(payloads) != 3:
        return False
    user_id = int(_load_step23a_module().USER_ID)
    for plan_name, payload in payloads.items():
        plans = list(
            (
                await db.execute(
                    select(ContinuityPlan).where(
                        ContinuityPlan.user_id == user_id,
                        ContinuityPlan.name == plan_name,
                        ContinuityPlan.ordering_mode == "informational",
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(plans) != 1:
            return False
        plan = plans[0]
        if _plan_fingerprint(plan) != _plan_fingerprint_from_payload(payload):
            return False
        owned = await _plan_owned_rule_hashes(db, user_id=user_id, plan_id=plan.id)
        if owned:
            return False
    return True


async def build_manifest_report(
    db: AsyncSession,
    *,
    manifest: str,
    source_manifests: dict[str, SourceBackedReaderOrderSpec],
    explicit_manifests: dict[str, ExplicitReaderOrderSpec],
) -> dict[str, Any]:
    """Build and classify one source-backed, explicit-family, or Step 23B dry-run."""
    if manifest == LEGACY_READING_ORDERS_MANIFEST:
        report = _normalize_legacy_report(await build_legacy_reading_order_dry_run(db))
        already_migrated = await _legacy_already_migrated(db, report)
    elif manifest in source_manifests:
        spec = source_manifests[manifest]
        report = await build_source_backed_reader_order_dry_run(db, spec)
        already_migrated = await _source_already_migrated(db, spec, report)
    else:
        spec = explicit_manifests[manifest]
        report = await build_explicit_reader_order_dry_run(db, spec)
        already_migrated = await _explicit_already_migrated(db, spec)
        if (
            not already_migrated
            and report.get("ok") is not True
            and await _step23b_retire_set_applied(db)
        ):
            # Step 23B already retired the overlapping IDs. Rebuild an overlay
            # snapshot that reconstructs covered rows from the reviewed contract
            # and still plans the full classified hard-gate set (same as one-shot).
            # Keep the recovered report even when Roll equivalence fails so the
            # operator sees behavior-mismatch instead of a false "missing deps"
            # identity block after covered gates were planned.
            recovered = await build_explicit_reader_order_dry_run(
                db,
                spec,
                tolerate_step23b_covered_absence=True,
            )
            report = {
                **recovered,
                "recovered_after_step23b": True,
            }
            already_migrated = await _explicit_already_migrated(db, spec)
    if already_migrated:
        report = {**report, "already_migrated": True, "ok": True}
    return {"status": migration_report_status(report), **report}
