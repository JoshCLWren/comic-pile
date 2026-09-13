"""Coordinator helpers for the one-shot Step 27 production migration."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import func, or_, select
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
    _legacy_prefix,
    _plan_fingerprint,
    _plan_fingerprint_from_payload,
    _planned_rule_descriptor,
    _rule_descriptor,
    _stable_hash,
)


LEGACY_READING_ORDERS_MANIFEST = "legacy-reading-orders"

# Explicit Step 14 families whose reader-order debt is owned by the reviewed
# Step 23B legacy Reading Order adoption. Prefer the legacy manifest in a
# combined batch so both paths never apply against the same dependency IDs.
LEGACY_COVERED_EXPLICIT_MANIFESTS = frozenset(
    {
        "doctor-strange-epic-vol-10",
        "starman-compendiums",
        "starman-jsa-bridge",
    }
)


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


def reconcile_batch_manifest_reports(
    reports: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Prefer Step 23B over overlapping explicit manifests in one batch plan.

    On an unmigrated snapshot both ``legacy-reading-orders`` and the Doctor
    Strange / Starman explicit families can independently report
    ``safe-to-migrate``. Alphabetical apply would mutate the shared dependency
    IDs before Step 23B's exact token check, rolling back the one-shot
    transaction. When the legacy manifest is safe or already migrated, treat
    the overlapping explicit families as covered by that path instead.
    """
    legacy = reports.get(LEGACY_READING_ORDERS_MANIFEST)
    if legacy is None:
        return reports
    legacy_status = str(legacy.get("status") or "")
    if legacy_status not in {"safe-to-migrate", "already-migrated"}:
        return reports

    reconciled = dict(reports)
    for manifest in LEGACY_COVERED_EXPLICIT_MANIFESTS:
        report = reconciled.get(manifest)
        if report is None:
            continue
        if report.get("covered_by") == LEGACY_READING_ORDERS_MANIFEST:
            continue
        status = str(report.get("status") or "")
        if status not in {"safe-to-migrate", "blocked-by-identity-or-source"}:
            continue
        reconciled[manifest] = {
            **report,
            "status": "already-migrated",
            "already_migrated": True,
            "ok": True,
            "covered_by": LEGACY_READING_ORDERS_MANIFEST,
            "errors": [],
        }
    return reconciled


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


def _edges_from_plan_nodes(nodes: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """Return directed issue edges encoded by persisted convergence gates."""
    edges: set[tuple[int, int]] = set()
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
            if not isinstance(node_id, str) or not node_id.startswith("issue-"):
                continue
            try:
                source_id = int(node_id.removeprefix("issue-"))
            except ValueError:
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
        int(cast(int, node["ref_id"]))
        for node in nodes
        if isinstance(node, dict)
        and node.get("node_type") == "issue"
        and isinstance(node.get("ref_id"), int)
    }
    edges = _edges_from_plan_nodes(cast(list[dict[str, Any]], nodes))

    if spec.dependency_group_ids:
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
        if not membership_issue_ids or membership_issue_ids != node_issue_ids:
            return False
    else:
        expected = _groupless_expected_contract(spec, plan)
        if expected is None:
            return False
        expected_issues, expected_edges = expected
        if node_issue_ids != expected_issues or edges != expected_edges:
            return False

    expected_rules = _expected_rules_from_plan_nodes(cast(list[dict[str, Any]], nodes))
    actual = await _plan_owned_rule_hashes(
        db,
        user_id=spec.user_id,
        plan_id=plan.id,
        sort_convergence_targets=True,
    )
    return expected_rules == actual



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
