"""Coordinator helpers for the one-shot Step 27 production migration."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroupMembership
from app.services.continuity_plan_writer import plan_rule_marker
from app.services.explicit_reader_order_migration import (
    ExplicitReaderOrderSpec,
    _explicit_classifications,
    _load_step14_index,
    _planned_rule_descriptor as _explicit_planned_rule_descriptor,
    _resolve_selected_dependency_ids,
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
from app.services.ultimate_universe_production_migration import (
    _plan_fingerprint,
    _plan_fingerprint_from_payload,
    _planned_rule_descriptor,
    _rule_descriptor,
    _stable_hash,
)


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


def _expected_rules_from_plan_nodes(nodes: list[dict[str, Any]]) -> set[str]:
    """Project informational convergence rules from persisted plan nodes."""
    expected: set[str] = set()
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
            if not isinstance(node_id, str) or not node_id.startswith("issue-"):
                continue
            try:
                source_ids.append(int(node_id.removeprefix("issue-")))
            except ValueError:
                continue
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
                        key=lambda target: (str(target["type"]), int(cast(int, target["id"]))),
                    ),
                }
        hashes.add(_stable_hash(descriptor))
    return hashes


async def _explicit_already_migrated(
    db: AsyncSession,
    spec: ExplicitReaderOrderSpec,
) -> bool:
    index = _load_step14_index()
    _, families = _explicit_classifications(index)
    selected_ids = _resolve_selected_dependency_ids(spec, by_family=families)
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
    membership_issue_ids = {
        int(issue_id)
        for issue_id in (
            await db.execute(
                select(DependencyGroupMembership.issue_id).where(
                    DependencyGroupMembership.group_id.in_(spec.dependency_group_ids),
                    DependencyGroupMembership.issue_id.is_not(None),
                )
            )
        ).scalars().all()
        if issue_id is not None
    }
    node_issue_ids = {
        int(cast(int, node["ref_id"]))
        for node in nodes
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and isinstance(node.get("ref_id"), int)
    }
    if not membership_issue_ids or membership_issue_ids != node_issue_ids:
        return False
    expected = _expected_rules_from_plan_nodes(cast(list[dict[str, Any]], nodes))
    actual = await _plan_owned_rule_hashes(
        db,
        user_id=spec.user_id,
        plan_id=plan.id,
        sort_convergence_targets=True,
    )
    return expected == actual



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
        (int(cast(int, row["source_id"])), int(cast(int, row["target_id"])))
        for row in report.get("reused_standalone_rules", [])
        if isinstance(row, dict)
    }
    expected = {
        _stable_hash(_planned_rule_descriptor(cast(dict[str, object], rule)))
        for rule in planned_rules
        if isinstance(rule, dict)
        and (
            int(cast(int, rule["source_id"])),
            int(cast(int, rule["target_id"])),
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
        int(cast(int, row["dependency_id"]))
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
    if already_migrated:
        report = {**report, "already_migrated": True, "ok": True}
    return {"status": migration_report_status(report), **report}
