"""Step 27 migration for explicitly classified reader-order dependencies.

This service consumes the canonical Step 14 classification artifact rather than
re-interpreting legacy dependency notes. It replaces only dependencies already
classified as ``reading_plan_order`` with one canonical Reading Plan, preserves
standalone prerequisites, and refuses to proceed when review or behavior
invariants are not satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
from pathlib import Path
import re
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanNode,
    ContinuityPlanWrite,
    ConvergenceGateTarget,
)
from app.services.continuity_graph import issue_readiness, load_snapshot
from app.services.continuity_plan_writer import replace_compiled_rules, validate_node_ownership
from app.services.legacy_reading_order_production_migration import (
    load_reviewed_step23a_contract,
    reviewed_reading_plan_order_rows,
)
from app.services.migration_shared import (
    MigrationInvariantError,
    coerce_int,
    dep_snapshot,
    invalidate_continuity_snapshot,
    plan_fingerprint,
    plan_fingerprint_from_payload,
    refresh_blocked_status,
    require_clean_snapshot,
    rule_snapshot,
    rules_fingerprint,
    stable_hash,
)
from app.services.ultimate_universe_production_migration import (
    _factual_snapshot,
)
from comic_pile.dependencies import _get_blocked_thread_ids_uncached
from comic_pile.queue import get_roll_pool

# Backward-compat aliases for external imports
_dep = dep_snapshot
_rule_snapshot = rule_snapshot
_require_clean = require_clean_snapshot

ROOT = Path(__file__).resolve().parents[2]
STEP14_INDEX = ROOT / "docs/recovery/step14-final-classification-index.json"


@dataclass(frozen=True)
class ExplicitReaderOrderSpec:
    """Frozen manifest for one Step 14 classified reader-order migration."""

    user_id: int
    dependency_group_ids: tuple[int, ...]
    expected_group_names: tuple[str, ...]
    plan_name: str
    classification_family_keys: tuple[str, ...] = ()
    # Test/support override. Production manifests should use family keys so the
    # canonical Step 14 artifact remains the source of classification truth.
    reader_order_dependency_ids: tuple[int, ...] = ()
    preserved_dependency_ids: tuple[int, ...] = ()
    # Durable membership/edge contract for group-less manifests. Required for
    # already-migrated detection when dependency_group_ids is empty and the
    # applied plan does not yet carry a stamped migration_contract.
    expected_issue_ids: tuple[int, ...] = ()
    expected_edges: tuple[tuple[int, int], ...] = ()


PRODUCTION_EXPLICIT_READER_ORDER_SPECS: dict[str, ExplicitReaderOrderSpec] = {
    "dc-ko": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(1,),
        expected_group_names=("DC K.O.",),
        plan_name="DC K.O.",
        classification_family_keys=("dc_ko_reader_order",),
    ),
    "starlin-cosmic": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(2,),
        expected_group_names=("Starlin’s Cosmic Marvel Saga early 90s",),
        plan_name="Starlin Cosmic",
        classification_family_keys=(
            "starlin_cosmic",
            "starlin_cosmic_cbl_order",
            "starlin_cosmic_reader_order",
        ),
    ),
    "jli-breakdowns": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(7, 8),
        expected_group_names=(
            "Justice League International / Europe",
            "Breakdowns",
        ),
        plan_name="Justice League International / Breakdowns",
        classification_family_keys=(
            "jli",
            "jli_reader_schedule",
            "jli_reader_order",
        ),
    ),
    "planetary-authority": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(10,),
        expected_group_names=("Planetary / Authority Crossovers",),
        plan_name="Planetary / Authority",
        classification_family_keys=("planetary_authority_reader_order",),
    ),
    "wildcats-satellite": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(12,),
        expected_group_names=("WildC.A.T.s Satellite Reading Order",),
        plan_name="WildC.A.T.s Satellite Reading Order",
        classification_family_keys=("wildcats_satellite_reader_order",),
    ),
    "daredevil-crossovers": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(19,),
        expected_group_names=("Daredevil Crossovers",),
        plan_name="Daredevil Crossovers",
        classification_family_keys=(
            "daredevil_frank_miller_collected_order",
            "daredevil_reader_order",
        ),
    ),
    "clandestine": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(21,),
        expected_group_names=("ClanDestine Reading Order",),
        plan_name="ClanDestine Reading Order",
        classification_family_keys=("clandestine_reader_order",),
    ),
    "astro-city": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(26,),
        expected_group_names=("Astro City",),
        plan_name="Astro City",
        classification_family_keys=(
            "astro_city_recovery_order",
            "astro_city_reader_order",
        ),
    ),
    "hickman-stage-1": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(117,),
        expected_group_names=("Hickman Marvel - Stage 1: Fantastic Four / FF",),
        plan_name="Hickman Marvel - Stage 1: Fantastic Four / FF",
        classification_family_keys=("hickman_marvel_stage_1",),
    ),
    "fourth-world": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(13,),
        expected_group_names=("Fourth World / Mister Miracle",),
        plan_name="Fourth World / Mister Miracle",
        classification_family_keys=("fourth_world_reader_order",),
    ),
    "black-panther-priest": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(17, 190),
        expected_group_names=(
            "Black Panther: Priest Crossovers",
            "Black Panther by Christopher Priest",
        ),
        plan_name="Black Panther by Christopher Priest",
        classification_family_keys=("black_panther_priest_collected_placement",),
    ),
    "doctor-strange-epic-vol-10": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="Doctor Strange Epic Collection Vol. 10: Infinity War",
        classification_family_keys=("doctor_strange_epic_vol_10",),
        # Frozen from docs/recovery/step23a-legacy-reading-order-preflight-evidence.json
        expected_issue_ids=(2243, 2244, 2245, 2249, 2250, 2251, 2252),
        expected_edges=(
            (2243, 2250),
            (2244, 2251),
            (2249, 2252),
            (2250, 2244),
            (2251, 2245),
        ),
    ),
    "starman-compendiums": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="Starman Compendiums 1-2",
        classification_family_keys=(
            "starman_legacy_order",
            "starman_compendium_order",
            "starman_compendium_stitches",
        ),
    ),
    "starman-jsa-bridge": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="JSA: Robinson / Goyer / Johns",
        classification_family_keys=("starman_jsa_bridge",),
        expected_issue_ids=(26360, 101817),
        expected_edges=((26360, 101817),),
    ),
    "majestic-recovery": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="Strange New Visitor / Majestic",
        classification_family_keys=("majestic_recovery_reader_order",),
    ),
    "nova-annual": ExplicitReaderOrderSpec(
        user_id=1,
        dependency_group_ids=(),
        expected_group_names=(),
        plan_name="Nova (2007) Annual Placement",
        classification_family_keys=("nova_annual_reader_placement",),
    ),
}


def _load_step14_index() -> dict[str, Any]:
    value = json.loads(STEP14_INDEX.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("result") != "PASS":
        raise MigrationInvariantError("Step 14 classification index is not a PASS artifact")
    return value


def _explicit_classifications(
    index: dict[str, Any],
) -> tuple[dict[int, str], dict[str, list[dict[str, Any]]]]:
    by_id: dict[int, str] = {}
    by_family: dict[str, list[dict[str, Any]]] = {}
    slices = cast(dict[str, Any], index["lookup"]["explicit_slices"])
    for slice_payload in slices.values():
        for family in cast(list[dict[str, Any]], slice_payload["families"]):
            family_key = str(family["family_key"])
            classification = str(family["classification"])
            by_family.setdefault(family_key, []).append(family)
            for raw_id in cast(list[int], family["ids"]):
                dependency_id = int(raw_id)
                previous = by_id.setdefault(dependency_id, classification)
                if previous != classification:
                    raise MigrationInvariantError(
                        f"Step 14 classification conflict for dependency {dependency_id}"
                    )
    return by_id, by_family


def _generated_reader_order_patterns(index: dict[str, Any]) -> tuple[re.Pattern[str], ...]:
    lookup = cast(dict[str, Any], index["lookup"])
    patterns: list[re.Pattern[str]] = []
    for key in ("14A", "14B_group16"):
        raw = cast(dict[str, Any], lookup[key]).get("note_regex")
        if raw:
            patterns.append(re.compile(str(raw)))
    temporary_note = cast(dict[str, Any], lookup["14B_temporary_ultimate"]).get(
        "note_equals"
    )
    if temporary_note:
        patterns.append(re.compile(f"^{re.escape(str(temporary_note))}$"))
    return tuple(patterns)


def _resolve_selected_dependency_ids(
    spec: ExplicitReaderOrderSpec,
    *,
    by_family: dict[str, list[dict[str, Any]]],
) -> tuple[int, ...]:
    if spec.reader_order_dependency_ids:
        return tuple(sorted(set(spec.reader_order_dependency_ids)))
    if not spec.classification_family_keys:
        raise MigrationInvariantError("manifest has no Step 14 reading_plan_order families")

    ids: set[int] = set()
    for family_key in spec.classification_family_keys:
        matches = by_family.get(family_key, [])
        if not matches:
            raise MigrationInvariantError(
                f"Step 14 family is missing from canonical index: {family_key}"
            )
        for family in matches:
            if family["classification"] != "reading_plan_order":
                raise MigrationInvariantError(
                    f"Step 14 family {family_key} is not reading_plan_order"
                )
            ids.update(int(value) for value in cast(list[int], family["ids"]))
    return tuple(sorted(ids))


def _topological_issue_order(
    issue_ids: set[int],
    edges: set[tuple[int, int]],
) -> list[int] | None:
    successors: dict[int, set[int]] = {issue_id: set() for issue_id in issue_ids}
    indegree: dict[int, int] = dict.fromkeys(issue_ids, 0)
    for source_id, target_id in edges:
        if target_id not in successors[source_id]:
            successors[source_id].add(target_id)
            indegree[target_id] += 1

    ready = [issue_id for issue_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[int] = []
    while ready:
        issue_id = heapq.heappop(ready)
        ordered.append(issue_id)
        for target_id in sorted(successors[issue_id]):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                heapq.heappush(ready, target_id)
    return ordered if len(ordered) == len(issue_ids) else None


def _planned_rule_descriptor(
    *,
    target_issue_id: int,
    source_issue_ids: list[int],
) -> dict[str, object]:
    return {
        "source_type": "issue",
        "source_id": target_issue_id,
        "target_type": "issue",
        "target_id": target_issue_id,
        "satisfaction_type": "converged",
        "checkpoint_issue_id": None,
        "convergence_targets": [
            {"type": "issue", "id": source_id} for source_id in source_issue_ids
        ],
    }


def _migration_contract(
    spec: ExplicitReaderOrderSpec,
    selected_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Build the durable server-owned proof for one explicit migration."""
    edge_pairs = sorted(
        {
            (
                coerce_int(row["source_issue_id"]),
                coerce_int(row["target_issue_id"]),
            )
            for row in selected_rows
        }
    )
    issue_ids = sorted(
        {
            issue_id
            for source_id, target_id in edge_pairs
            for issue_id in (source_id, target_id)
        }
    )
    return {
        "kind": "explicit_reader_order",
        "classification_family_keys": list(spec.classification_family_keys),
        "selected_dependency_ids": [
            coerce_int(row["id"]) for row in selected_rows
        ],
        "issue_ids": issue_ids,
        "edges": [list(edge) for edge in edge_pairs],
        "issue_fingerprint": stable_hash(issue_ids),
        "edge_fingerprint": stable_hash(edge_pairs),
    }


def _reviewed_step23b_writer_payloads() -> dict[str, dict[str, object]]:
    """Return reviewed Step 23A writer payloads keyed by canonical plan name."""
    evidence = load_reviewed_step23a_contract()
    targets = evidence.get("proposed_canonical_targets")
    if not isinstance(targets, list):
        return {}
    payloads: dict[str, dict[str, object]] = {}
    for target in targets:
        if not isinstance(target, dict):
            continue
        payload = target.get("writer_payload")
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if isinstance(name, str) and name:
            payloads[name] = payload
    return payloads


def _reviewed_step23b_plan_names() -> set[str]:
    """Return the three canonical Step 23B Reading Plan names."""
    return set(_reviewed_step23b_writer_payloads())


async def build_explicit_reader_order_dry_run(
    db: AsyncSession,
    spec: ExplicitReaderOrderSpec,
    *,
    tolerate_step23b_covered_absence: bool = False,
) -> dict[str, Any]:
    """Build a deterministic read-only snapshot for one Step 14 family manifest.

    When ``tolerate_step23b_covered_absence`` is true, dependencies already retired
    by Step 23B are reconstructed from the reviewed Step 23A contract. The matching
    Step 23B target plan must still fingerprint-match the reviewed writer payload
    and is sealed into the snapshot; other Step 23B plans may overlap without
    blocking. Residual live dependencies must still be present. Recovered snapshots
    still compile every classified edge as a hard convergence gate (identical to
    one-shot); informational Step 23B node positions are not Roll authority. If
    restoring those gates would change eligibility, report a Roll mismatch.
    """
    invalidate_continuity_snapshot(spec.user_id, db)
    errors: list[str] = []
    index = _load_step14_index()
    by_id, by_family = _explicit_classifications(index)
    generated_patterns = _generated_reader_order_patterns(index)
    selected_ids = _resolve_selected_dependency_ids(spec, by_family=by_family)
    step23b_covered_ids: set[int] = set()
    reviewed_covered_rows: dict[int, dict[str, object]] = {}
    if tolerate_step23b_covered_absence:
        reviewed_covered_rows = {
            coerce_int(row["dependency_id"]): row
            for row in reviewed_reading_plan_order_rows(load_reviewed_step23a_contract())
        }
        step23b_covered_ids = set(reviewed_covered_rows) & set(selected_ids)

    groups = list(
        (
            await db.execute(
                select(DependencyGroup)
                .where(
                    DependencyGroup.user_id == spec.user_id,
                    DependencyGroup.id.in_(spec.dependency_group_ids),
                )
                .order_by(DependencyGroup.id)
            )
        )
        .scalars()
        .all()
    )
    groups_by_id = {group.id: group for group in groups}
    missing_groups = sorted(set(spec.dependency_group_ids) - set(groups_by_id))
    if missing_groups:
        errors.append(f"dependency groups missing: {missing_groups}")
    expected_names = dict(zip(spec.dependency_group_ids, spec.expected_group_names, strict=True))
    for group_id, expected_name in expected_names.items():
        group = groups_by_id.get(group_id)
        if group is not None and group.name != expected_name:
            errors.append(
                f"dependency group {group_id} name changed: expected {expected_name!r}, got {group.name!r}"
            )

    memberships = list(
        (
            await db.execute(
                select(DependencyGroupMembership)
                .where(DependencyGroupMembership.group_id.in_(spec.dependency_group_ids))
                .order_by(DependencyGroupMembership.id)
            )
        )
        .scalars()
        .all()
    )
    ordered_membership_ids = [
        membership.id for membership in memberships if membership.sequence_order is not None
    ]
    if ordered_membership_ids:
        errors.append(
            f"sequence_order unexpectedly populated: {ordered_membership_ids}"
        )
    group_issue_ids = {
        membership.issue_id
        for membership in memberships
        if membership.issue_id is not None
    }

    selected = list(
        (
            await db.execute(
                select(Dependency)
                .where(Dependency.id.in_(selected_ids))
                .order_by(Dependency.id)
            )
        )
        .scalars()
        .all()
    )
    found_ids = {dependency.id for dependency in selected}
    missing_selected = sorted(set(selected_ids) - found_ids)
    tolerated_missing = sorted(set(missing_selected) & step23b_covered_ids)
    unexpected_missing = sorted(set(missing_selected) - step23b_covered_ids)
    if unexpected_missing or (missing_selected and not tolerate_step23b_covered_absence):
        errors.append(
            "classified reader-order dependencies missing: "
            f"{unexpected_missing if tolerate_step23b_covered_absence else missing_selected}"
        )

    graph = await load_snapshot(db, spec.user_id)
    issue_ids: set[int] = set()
    edge_set: set[tuple[int, int]] = set()
    selected_semantics: list[dict[str, object]] = []
    for dependency in selected:
        source_issue = graph.issues.get(dependency.source_issue_id)
        target_issue = graph.issues.get(dependency.target_issue_id)
        if source_issue is None or target_issue is None:
            errors.append(
                f"classified reader-order dependency {dependency.id} has an endpoint outside user ownership"
            )
            continue
        if dependency.source_issue_id == dependency.target_issue_id:
            errors.append(f"classified reader-order dependency {dependency.id} is a self-loop")
            continue
        issue_ids.update((dependency.source_issue_id, dependency.target_issue_id))
        edge_set.add((dependency.source_issue_id, dependency.target_issue_id))
        selected_semantics.append(
            {
                **dep_snapshot(dependency),
                "source_status": source_issue.status,
                "target_status": target_issue.status,
                "source_in_manifest_groups": dependency.source_issue_id in group_issue_ids,
                "target_in_manifest_groups": dependency.target_issue_id in group_issue_ids,
            }
        )

    for dependency_id in tolerated_missing:
        row = reviewed_covered_rows[dependency_id]
        source_issue_id = coerce_int(row["source_issue_id"])
        target_issue_id = coerce_int(row["target_issue_id"])
        source_issue = graph.issues.get(source_issue_id)
        target_issue = graph.issues.get(target_issue_id)
        if source_issue is None or target_issue is None:
            errors.append(
                f"classified reader-order dependency {dependency_id} has an endpoint outside user ownership"
            )
            continue
        issue_ids.update((source_issue_id, target_issue_id))
        edge_set.add((source_issue_id, target_issue_id))
        selected_semantics.append(
            {
                "id": dependency_id,
                "source_issue_id": source_issue_id,
                "target_issue_id": target_issue_id,
                "note": row.get("note"),
                "created_at": "1970-01-01T00:00:00+00:00",
                "source_status": source_issue.status,
                "target_status": target_issue.status,
                "source_in_manifest_groups": source_issue_id in group_issue_ids,
                "target_in_manifest_groups": target_issue_id in group_issue_ids,
                "retired_by_step23b": True,
            }
        )
    selected_semantics.sort(key=lambda row: coerce_int(row["id"]))

    if spec.expected_issue_ids:
        issue_ids.update(spec.expected_issue_ids)
    if spec.expected_edges:
        edge_set.update(spec.expected_edges)
        for source_id, target_id in spec.expected_edges:
            issue_ids.update((source_id, target_id))

    ordered_issue_ids = _topological_issue_order(issue_ids, edge_set)
    if ordered_issue_ids is None:
        errors.append("classified reader-order dependencies contain a cycle")
        ordered_issue_ids = sorted(issue_ids)

    overlapping_plans: list[dict[str, object]] = []
    existing_canonical_plan: dict[str, object] | None = None
    reviewed_payloads = (
        _reviewed_step23b_writer_payloads() if tolerate_step23b_covered_absence else {}
    )
    step23b_plan_names = set(reviewed_payloads)
    if issue_ids:
        plans = (
            await db.execute(
                select(ContinuityPlan).where(ContinuityPlan.user_id == spec.user_id)
            )
        ).scalars()
        for plan in plans:
            refs = {
                int(node.get("ref_id", 0))
                for node in plan.nodes_json or []
                if node.get("node_type") == "issue"
            }
            overlap = refs & issue_ids
            if not overlap:
                continue
            # Non-target Step 23B plans may overlap residual overlays (for example
            # JSA issue 26360 already lives on the Starman plan). The target plan
            # itself must be sealed and fingerprint-checked, not ignored.
            if (
                tolerate_step23b_covered_absence
                and plan.name in step23b_plan_names
                and plan.name != spec.plan_name
            ):
                continue
            if (
                tolerate_step23b_covered_absence
                and plan.name == spec.plan_name
                and plan.name in reviewed_payloads
            ):
                reviewed_payload = reviewed_payloads[plan.name]
                live_fingerprint = plan_fingerprint(plan)
                expected_fingerprint = plan_fingerprint_from_payload(reviewed_payload)
                if live_fingerprint != expected_fingerprint:
                    errors.append(
                        "Step 23B canonical plan drifted from reviewed fingerprint: "
                        f"{plan.name!r}"
                    )
                    continue
                if plan.ordering_mode != "informational":
                    errors.append(
                        f"Step 23B canonical plan ordering_mode changed: {plan.name!r}"
                    )
                    continue
                existing_canonical_plan = {
                    "id": plan.id,
                    "name": plan.name,
                    "ordering_mode": plan.ordering_mode,
                    "plan_fingerprint": live_fingerprint,
                    "nodes": list(plan.nodes_json or []),
                    "lanes": list(plan.lanes_json or []),
                }
                continue
            overlapping_plans.append(
                {"id": plan.id, "name": plan.name, "overlap_count": len(overlap)}
            )
    if tolerate_step23b_covered_absence and spec.plan_name in step23b_plan_names:
        if existing_canonical_plan is None and not any(
            "Step 23B canonical plan drifted" in error
            or "Step 23B canonical plan ordering_mode changed" in error
            for error in errors
        ):
            errors.append(
                f"Step 23B canonical plan missing for recovery: {spec.plan_name!r}"
            )
    if overlapping_plans:
        errors.append(f"existing Reading Plan overlap: {overlapping_plans}")

    explicit_classification_ids = set(by_id)
    related_ids = explicit_classification_ids | set(spec.preserved_dependency_ids)
    related_dependencies = (
        list(
            (
                await db.execute(
                    select(Dependency)
                    .where(Dependency.id.in_(related_ids))
                    .order_by(Dependency.id)
                )
            )
            .scalars()
            .all()
        )
        if related_ids
        else []
    )
    preserved_standalone: list[Dependency] = []
    needs_review: list[Dependency] = []
    unselected_reader_order: list[Dependency] = []
    for dependency in related_dependencies:
        touches_plan = (
            dependency.source_issue_id in issue_ids
            or dependency.target_issue_id in issue_ids
        )
        both_in_plan = (
            dependency.source_issue_id in issue_ids
            and dependency.target_issue_id in issue_ids
        )
        classification = by_id.get(dependency.id)
        if dependency.id in spec.preserved_dependency_ids:
            preserved_standalone.append(dependency)
        elif classification == "standalone_prerequisite" and touches_plan:
            preserved_standalone.append(dependency)
        elif classification == "needs_review" and touches_plan:
            needs_review.append(dependency)
        elif (
            classification == "reading_plan_order"
            and dependency.id not in found_ids
            and both_in_plan
        ):
            unselected_reader_order.append(dependency)
    if needs_review:
        errors.append(
            f"needs_review dependencies touch this plan: {[dependency.id for dependency in needs_review]}"
        )
    if unselected_reader_order:
        errors.append(
            "manifest omits reading_plan_order dependencies inside the proposed plan: "
            f"{[dependency.id for dependency in unselected_reader_order]}"
        )

    internal_dependencies = (
        list(
            (
                await db.execute(
                    select(Dependency)
                    .where(
                        Dependency.source_issue_id.in_(issue_ids),
                        Dependency.target_issue_id.in_(issue_ids),
                    )
                    .order_by(Dependency.id)
                )
            )
            .scalars()
            .all()
        )
        if issue_ids
        else []
    )
    unknown_internal: list[Dependency] = []
    generated_internal: list[Dependency] = []
    preserved_ids = {dependency.id for dependency in preserved_standalone}
    for dependency in internal_dependencies:
        if dependency.id in found_ids or dependency.id in preserved_ids:
            continue
        if dependency.id in by_id:
            continue
        note = dependency.note or ""
        if any(pattern.match(note) for pattern in generated_patterns):
            generated_internal.append(dependency)
        else:
            unknown_internal.append(dependency)
    if generated_internal:
        errors.append(
            "generated reading_plan_order dependencies are still present inside the proposed plan: "
            f"{[dependency.id for dependency in generated_internal]}"
        )
    if unknown_internal:
        errors.append(
            "unclassified dependencies are present inside the proposed plan: "
            f"{[dependency.id for dependency in unknown_internal]}"
        )

    removal_ids = found_ids
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

    # Resume after Step 23B must compile the same hard convergence gates as the
    # normal one-shot path. Step 23B plans are informational with empty gates, so
    # node position is not a Roll authority for covered edges — reconstruct them.
    predecessors: dict[int, list[int]] = {}
    for source_id, target_id in sorted(edge_set):
        predecessors.setdefault(target_id, []).append(source_id)
    for values in predecessors.values():
        values.sort()

    lane = ContinuityPlanLane(id="reader-order", name=spec.plan_name, order=0)
    nodes = [
        ContinuityPlanNode(
            id=f"issue-{issue_id}",
            node_type="issue",
            ref_id=issue_id,
            lane_id=lane.id,
            position=position,
            convergence_gate=[
                ConvergenceGateTarget(node_type="issue", node_id=f"issue-{source_id}")
                for source_id in predecessors.get(issue_id, [])
            ],
        )
        for position, issue_id in enumerate(ordered_issue_ids)
    ]
    plan_payload = {
        "name": spec.plan_name,
        "ordering_mode": "informational",
        "lanes": [lane.model_dump()],
        "nodes": [node.model_dump() for node in nodes],
    }
    ContinuityPlanWrite.model_validate(plan_payload)

    planned_rules = [
        _planned_rule_descriptor(
            target_issue_id=target_id,
            source_issue_ids=source_ids,
        )
        for target_id, source_ids in sorted(predecessors.items())
    ]
    planned_edges = {
        (source_id, target_id)
        for target_id, source_ids in predecessors.items()
        for source_id in source_ids
    }
    if planned_edges != edge_set:
        errors.append("proposed Reading Plan does not exactly reproduce classified reader-order edges")

    target_ids = set(predecessors)
    self_loop_conflicts = (
        list(
            (
                await db.execute(
                    select(ContinuityRule)
                    .where(
                        ContinuityRule.user_id == spec.user_id,
                        ContinuityRule.source_type == "issue",
                        ContinuityRule.target_type == "issue",
                        ContinuityRule.source_id.in_(target_ids),
                        ContinuityRule.source_id == ContinuityRule.target_id,
                    )
                    .order_by(ContinuityRule.id)
                )
            )
            .scalars()
            .all()
        )
        if target_ids
        else []
    )
    self_loop_conflicts = [
        rule for rule in self_loop_conflicts if rule.id not in removed_rule_ids
    ]
    if self_loop_conflicts:
        errors.append(
            f"planned convergence rules conflict with existing rules: {[rule.id for rule in self_loop_conflicts]}"
        )

    ownership_error = any("outside user ownership" in error for error in errors)
    factual = (
        await _factual_snapshot(
            db,
            spec=spec,
            ordered_issue_ids=ordered_issue_ids,
        )
        if ordered_issue_ids and not ownership_error
        else {
            "issues": [],
            "threads": [],
            "events": [],
            "identities": [],
            "issue_state_hash": None,
            "thread_state_hash": None,
            "event_state_hash": None,
            "identity_state_hash": None,
        }
    )

    affected = [
        thread
        for thread in graph.threads.values()
        if thread.status == "active"
        and thread.queue_position >= 1
        and thread.next_unread_issue_id in issue_ids
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

    future_blocked: set[int] = set()
    behavior: list[dict[str, object]] = []
    for thread in affected:
        next_issue_id = coerce_int(thread.next_unread_issue_id)
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
            for source_id in predecessors.get(next_issue_id, [])
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

    state: dict[str, object] = {
        "manifest": {
            "user_id": spec.user_id,
            "dependency_group_ids": list(spec.dependency_group_ids),
            "expected_group_names": list(spec.expected_group_names),
            "plan_name": spec.plan_name,
            "classification_family_keys": list(spec.classification_family_keys),
            "resolved_reader_order_dependency_ids": list(selected_ids),
        },
        "dependency_groups": [
            {
                "id": group.id,
                "name": group.name,
                "issue_membership_count": sum(
                    1
                    for membership in memberships
                    if membership.group_id == group.id and membership.issue_id is not None
                ),
            }
            for group in groups
        ],
        "ordered_membership_count": len(ordered_membership_ids),
        "selected_reader_order_dependencies": selected_semantics,
        "preserved_standalone_dependencies": [
            dep_snapshot(dependency) for dependency in preserved_standalone
        ],
        "needs_review_dependencies": [dep_snapshot(dependency) for dependency in needs_review],
        "unselected_reader_order_dependencies": [
            dep_snapshot(dependency) for dependency in unselected_reader_order
        ],
        "generated_internal_dependencies": [
            dep_snapshot(dependency) for dependency in generated_internal
        ],
        "unclassified_internal_dependencies": [
            dep_snapshot(dependency) for dependency in unknown_internal
        ],
        "removed_linked_continuity_rules": [
            rule_snapshot(rule) for rule in removed_rules
        ],
        "overlapping_plans": overlapping_plans,
        "existing_canonical_plan": existing_canonical_plan,
        "factual": factual,
        "planned": {
            "plan": plan_payload,
            "rules": planned_rules,
            "edge_count": len(edge_set),
            "rule_count": len(planned_rules),
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
        "snapshot_token": stable_hash(state),
        **state,
    }


async def apply_explicit_reader_order_migration(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    spec: ExplicitReaderOrderSpec,
) -> dict[str, Any]:
    """Apply one reviewed classified reader-order snapshot transactionally."""
    require_clean_snapshot(snapshot)
    current = await build_explicit_reader_order_dry_run(db, spec)
    if (
        current.get("snapshot_token") != snapshot["snapshot_token"]
        or current.get("ok") is not True
    ):
        raise MigrationInvariantError("live state changed since dry-run")

    removed_rows = list(snapshot["selected_reader_order_dependencies"])
    removal_ids = [coerce_int(row["id"]) for row in removed_rows]
    if removal_ids:
        result = await db.execute(delete(Dependency).where(Dependency.id.in_(removal_ids)))
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
        ordering_mode="informational",
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
        ordering_mode="informational",
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
    expected_count = coerce_int(snapshot["planned"]["rule_count"])
    if len(rules) != expected_count:
        raise MigrationInvariantError(
            f"expected {expected_count} plan rules, found {len(rules)}"
        )

    expected = {
        stable_hash(rule)
        for rule in cast(list[dict[str, object]], snapshot["planned"]["rules"])
    }
    actual = {
        stable_hash(
            {
                "source_type": rule.source_type,
                "source_id": rule.source_id,
                "target_type": rule.target_type,
                "target_id": rule.target_id,
                "satisfaction_type": rule.satisfaction_type,
                "checkpoint_issue_id": rule.checkpoint_issue_id,
                "convergence_targets": sorted(
                    rule.convergence_targets or [],
                    key=lambda target: (str(target["type"]), int(target["id"])),
                ),
            }
        )
        for rule in rules
    }
    if expected != actual:
        raise MigrationInvariantError(
            "compiled rule semantics diverge from reviewed snapshot"
        )
    if plan_fingerprint(plan) != plan_fingerprint_from_payload(payload):
        raise MigrationInvariantError(
            "persisted Reading Plan diverges from reviewed snapshot"
        )

    # Stamp durable membership/edge contract after fingerprint equality so
    # group-less already-migrated checks have an independent proof even when
    # Dependency Groups were never part of the manifest.
    selected_rows = cast(
        list[dict[str, object]],
        snapshot["selected_reader_order_dependencies"],
    )
    stamped_lanes = [dict(lane) for lane in (plan.lanes_json or [])]
    if stamped_lanes:
        stamped_lanes[0] = {
            **stamped_lanes[0],
            "migration_contract": _migration_contract(spec, selected_rows),
        }
        plan.lanes_json = stamped_lanes
        await db.flush()

    ordered_membership = await db.scalar(
        select(DependencyGroupMembership.id)
        .where(
            DependencyGroupMembership.group_id.in_(spec.dependency_group_ids),
            DependencyGroupMembership.sequence_order.is_not(None),
        )
        .limit(1)
    )
    if ordered_membership is not None:
        raise MigrationInvariantError("sequence_order changed during migration")

    for row in snapshot["preserved_standalone_dependencies"]:
        dependency = await db.get(Dependency, coerce_int(row["id"]))
        if dependency is None or dep_snapshot(dependency) != row:
            raise MigrationInvariantError(
                f"standalone prerequisite {row['id']} changed"
            )

    issue_ids = [coerce_int(node["ref_id"]) for node in payload["nodes"]]
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
            "affected Roll eligibility changed after migration"
        )

    return {
        "plan_id": plan.id,
        "plan_marker": marker,
        "plan_fingerprint": plan_fingerprint(plan),
        "plan_rule_count": len(rules),
        "plan_rule_fingerprint": rules_fingerprint(rules),
        "removed_reader_order_dependency_count": len(removed_rows),
        "removed_dependencies": removed_rows,
        "removed_linked_continuity_rules": snapshot["removed_linked_continuity_rules"],
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
