"""Shared canonical Reading Plan writer and strict-rule compiler.

Continuity-plan create/update and CBL adoption must persist Reading Plans
through one validated write path: node ownership is checked up front and the
plan-owned rules are compiled and replaced from the same node semantics. This
module owns that canonical path so a future CBL adoption slice can call it
instead of inventing a second strict compiler.

The compiler's hard-edge semantics (#2553 Phase B):
  1. ``strict_sequential`` plans compile inferred ``item_read`` gates
     selected by the plan's durable ``inferred_gate_kind`` (thread-entry
     by default; reading-order for stamped CBL reading lists), never
     same-thread adjacency;
  2. checkpoint nodes block the next node in the same lane;
  3. convergence gates compile ``converged`` self-loop rules;
  4. plan-level cycles and persisted-rule conflicts keep their stable codes;
  5. informational plans add no inferred blockers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from fastapi import HTTPException
from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_rules import _would_create_cycle, ensure_owned_continuity_node
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.thread import Thread
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanListItem,
    ContinuityPlanNode,
    PlanInferredGateKind,
    PlanOrderingMode,
)
from app.schemas.continuity_rule import ContinuityNodeType
from app.repositories.continuity_repository import plans_for_user
from app.services.canonical_constraint_compiler import (
    compile_rule_edges,
    retire_rule_edges,
    rule_edge_pairs,
)
from app.services.reading_plan_normalization import rebuild_plan_membership
from app.services.strict_plan_constraints import (
    load_issue_thread_index,
    strict_plan_item_read_pairs,
    strict_plan_reading_order_pairs,
)


PLAN_RULE_MARKER_PREFIX = "continuity-plan"


def serialize_new_plan_lanes(
    lanes: list[ContinuityPlanLane],
) -> list[dict[str, object]]:
    """Serialize lanes without accepting client-authored migration proof."""
    return [lane.model_dump(exclude={"migration_contract"}) for lane in lanes]


def preserve_server_lane_metadata(
    existing_lanes: list[dict[str, object]],
    lanes: list[ContinuityPlanLane],
) -> list[dict[str, object]]:
    """Preserve server-owned migration proof across ordinary lane replacement."""
    contracts = {
        str(lane.get("id")): lane["migration_contract"]
        for lane in existing_lanes
        if lane.get("migration_contract") is not None
    }
    gate_kinds = {
        str(lane.get("id")): lane["inferred_gate_kind"]
        for lane in existing_lanes
        if lane.get("inferred_gate_kind") is not None
    }
    serialized: list[dict[str, object]] = []
    for lane in lanes:
        row = lane.model_dump(exclude={"migration_contract"})
        contract = contracts.get(lane.id)
        if contract is not None:
            row["migration_contract"] = contract
        if row.get("inferred_gate_kind") is None:
            existing_kind = gate_kinds.get(lane.id)
            if existing_kind is not None:
                row["inferred_gate_kind"] = existing_kind
        serialized.append(row)
    return serialized


def inferred_gate_kind_from_lanes(
    lanes: Sequence[ContinuityPlanLane] | Sequence[dict[str, object]] | None,
) -> PlanInferredGateKind:
    """Return the durable inferred-gate kind stamped on a plan's lanes.

    Args:
        lanes: Persisted ``lanes_json`` rows or validated lane models.

    Returns:
        ``reading_order`` when any lane carries that stamp; otherwise
        ``thread_entry``, the default for live planner creates.
    """
    for lane in lanes or ():
        kind = (
            lane.inferred_gate_kind
            if isinstance(lane, ContinuityPlanLane)
            else lane.get("inferred_gate_kind")
        )
        if kind == "reading_order":
            return "reading_order"
    return "thread_entry"


def plan_rule_marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return f"{PLAN_RULE_MARKER_PREFIX}:{plan_id}"


def _detect_plan_cycles(
    nodes: list[tuple[str, int]],
    edges: list[tuple[tuple[str, int], tuple[str, int]]],
) -> set[tuple[str, int]]:
    """Return every plan node participating in a directed cycle."""
    adjacency: dict[tuple[str, int], list[tuple[str, int]]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    for target_list in adjacency.values():
        target_list.sort()

    color: dict[tuple[str, int], int] = dict.fromkeys(nodes, 0)
    in_cycle: set[tuple[str, int]] = set()

    for start_node in sorted(nodes):
        if color[start_node] != 0:
            continue

        stack: list[tuple[tuple[str, int], int]] = [(start_node, 0)]
        path: list[tuple[str, int]] = []

        while stack:
            node, state = stack.pop()
            if state == 0:
                if color[node] in {1, 2}:
                    continue
                color[node] = 1
                path.append(node)
                stack.append((node, 1))
                for nxt in reversed(adjacency.get(node, ())):
                    if color[nxt] == 0:
                        stack.append((nxt, 0))
                    elif color[nxt] == 1:
                        try:
                            idx = path.index(nxt)
                            in_cycle.update(path[idx:])
                        except ValueError:
                            pass
            else:
                if path and path[-1] == node:
                    path.pop()
                color[node] = 2

    return in_cycle


async def validate_node_ownership(
    db: AsyncSession,
    *,
    user_id: int,
    nodes: list[ContinuityPlanNode],
) -> None:
    """Validate every referenced issue, crossover, or thread before any plan write.

    Args:
        db: Async database session.
        user_id: Authenticated owner of every referenced node.
        nodes: Plan nodes to own-check before persistence.

    Raises:
        HTTPException: 422 ``dangling_plan_reference`` when any referenced node
            is not owned by ``user_id``.
    """
    for node in nodes:
        if node.node_type == "thread":
            owned = (
                await db.execute(
                    select(Thread.id).where(Thread.id == node.ref_id, Thread.user_id == user_id)
                )
            ).scalar_one_or_none()
            if owned is None:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "dangling_plan_reference", "node_id": node.id},
                )
            continue
        try:
            await ensure_owned_continuity_node(
                db,
                user_id=user_id,
                node_type=node.node_type,
                node_id=node.ref_id,
            )
        except HTTPException as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "dangling_plan_reference", "node_id": node.id},
            ) from exc


def _is_equivalent_reusable_item_read_rule(
    rule: ContinuityRule,
    *,
    requested_satisfaction_type: str,
) -> bool:
    """Return whether an existing ``item_read`` rule already satisfies a plan edge.

    Equivalent ``item_read`` rules — standalone or owned by another Reading
    Plan — may satisfy the same hard edge without duplicating the unique
    ContinuityRule identity. Provenance is the ``reading_plan_dependencies``
    join, not exclusive note ownership.
    """
    return (
        requested_satisfaction_type == "item_read"
        and rule.satisfaction_type == "item_read"
        and rule.checkpoint_issue_id is None
        and not rule.convergence_targets
    )


async def replace_compiled_rules(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
    nodes: list[ContinuityPlanNode],
    ordering_mode: PlanOrderingMode,
    sync_canonical_edges: bool = True,
    extra_item_read_pairs: Sequence[tuple[int, int]] | None = None,
) -> bool:
    """Replace only rules owned by this plan and compile plan semantics into rules.

    This compiles:
    1. Strict-sequential thread-entry gates (Phase B of #2553)
    2. Checkpoint rules from nodes with ``is_checkpoint=True``
    3. Converged rules from nodes with ``convergence_gate`` entries
    4. Caller-supplied selected ``item_read`` pairs that are still in the plan

    Checkpoint semantics: a node marked as checkpoint blocks the next node in
    the same lane until the checkpoint node is read.

    Convergence semantics: a node with convergence targets is blocked until all
    referenced upstream nodes are read.

    An equivalent non-plan-owned ``item_read`` rule may satisfy a strict edge
    without changing that standalone rule's ownership or provenance.

    Args:
        db: Async database session.
        user_id: Authenticated plan owner.
        plan: The persisted (or to-be-persisted) plan owning the compiled rules.
        nodes: Canonical node set to compile from.
        ordering_mode: Plan ordering mode; only ``strict_sequential`` creates
            inferred gates. Thread-entry is the default; ``reading_order``
            stamped on ``lanes_json`` compiles mid-run cross-thread hops.
        sync_canonical_edges: When True (default), retire this plan's stale
            compiled edges and compile the new rules into canonical
            Dependencies (#2553). Only pairs that actually changed are
            retired/compiled, so re-saving an unchanged plan is a no-op
            for the Dependency table.
        extra_item_read_pairs: Explicit selected hard restrictions to compile
            in addition to inferred gates. Same-thread pairs are ignored.
            Live plan create/update omit this; migrations pass classified
            genuine prerequisites that are not series starts.

    Returns:
        True when all rules compiled without cycle conflicts.
    """
    # Normalized membership/provenance always reflects the latest nodes in the
    # same transaction: informational plans with no compiled edges still own
    # relational membership, and a later rule-compilation failure rolls the
    # membership rebuild back with the rest of the write.
    await rebuild_plan_membership(db, plan_id=plan.id, nodes=nodes)

    marker = plan_rule_marker(plan.id)
    # Collect the compiled pairs of the outgoing rules before replacing them,
    # so their canonical edges can be retired unless still intended (#2553).
    old_pairs: set[tuple[int, int]] = set()
    if sync_canonical_edges:
        old_plan_rules = (
            (
                await db.execute(
                    select(ContinuityRule).where(
                        ContinuityRule.user_id == user_id,
                        ContinuityRule.note == marker,
                    )
                )
            )
            .scalars()
            .all()
        )
        for old_rule in old_plan_rules:
            old_pairs.update(rule_edge_pairs(old_rule))
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )
    await db.flush()

    # Build node lookup for convergence gate resolution
    node_map: dict[str, ContinuityPlanNode] = {node.id: node for node in nodes}

    # Build per-lane ordered node lists for checkpoint next-node lookup
    nodes_by_lane: dict[str, list[ContinuityPlanNode]] = {}
    for node in nodes:
        nodes_by_lane.setdefault(node.lane_id, []).append(node)
    for lane_nodes in nodes_by_lane.values():
        lane_nodes.sort(key=lambda n: n.position)

    # Collect all edges to compile (for cycle detection)
    convergence_target = dict[str, int | str]
    edges_to_add: list[
        tuple[str, int, str, int, str, int | list[convergence_target] | None]
    ] = []

    # 1. Strict-sequential inferred gates, plus selected extra pairs.
    if ordering_mode == "strict_sequential":
        issue_ids = [node.ref_id for node in nodes if node.node_type == "issue"]
        issue_index = await load_issue_thread_index(db, issue_ids)
        compiled_item_read: set[tuple[int, int]] = set()
        inferred_pairs = (
            strict_plan_reading_order_pairs(nodes, issue_index)
            if inferred_gate_kind_from_lanes(plan.lanes_json) == "reading_order"
            else strict_plan_item_read_pairs(nodes, issue_index)
        )
        for source_id, target_id in inferred_pairs:
            edges_to_add.append((
                "issue", source_id,
                "issue", target_id,
                "item_read", None,
            ))
            compiled_item_read.add((source_id, target_id))
        issue_id_set = set(issue_ids)
        for source_id, target_id in extra_item_read_pairs or ():
            pair = (source_id, target_id)
            if pair in compiled_item_read or source_id == target_id:
                continue
            if source_id not in issue_id_set or target_id not in issue_id_set:
                continue
            source_meta = issue_index.get(source_id)
            target_meta = issue_index.get(target_id)
            if source_meta is None or target_meta is None:
                continue
            if source_meta.thread_id == target_meta.thread_id:
                continue
            edges_to_add.append((
                "issue", source_id,
                "issue", target_id,
                "item_read", None,
            ))
            compiled_item_read.add(pair)

    # 2. Checkpoint rules: checkpoint node blocks the next node in the same lane
    for node in nodes:
        if not node.is_checkpoint:
            continue
        lane_nodes = nodes_by_lane.get(node.lane_id, [])
        node_index = next(
            (i for i, n in enumerate(lane_nodes) if n.id == node.id), None
        )
        if node_index is None or node_index >= len(lane_nodes) - 1:
            continue
        next_node = lane_nodes[node_index + 1]
        # Skip self-referencing checkpoint edges (same issue/type in same lane)
        if next_node.node_type == node.node_type and next_node.ref_id == node.ref_id:
            continue
        checkpoint_issue_id = node.ref_id if node.node_type == "issue" else None
        edges_to_add.append((
            node.node_type, node.ref_id,
            next_node.node_type, next_node.ref_id,
            "checkpoint", checkpoint_issue_id,
        ))

    # 3. Converged rules: node waits for all convergence gate targets
    for node in nodes:
        if not node.convergence_gate:
            continue
        gate_targets: list[convergence_target] = []
        for target in node.convergence_gate:
            resolved = node_map.get(target.node_id)
            if resolved is None:
                continue
            gate_targets.append({
                "type": resolved.node_type,
                "id": resolved.ref_id,
            })
        if not gate_targets:
            continue
        edges_to_add.append((
            node.node_type, node.ref_id,
            node.node_type, node.ref_id,
            "converged", gate_targets,
        ))

    if not edges_to_add:
        if sync_canonical_edges:
            # The new rule set is empty: retire all previously compiled
            # pairs so orphaned edges don't keep blocking Roll (#2553).
            await retire_rule_edges(
                db, user_id=user_id, pairs=list(old_pairs), exclude_rule_id=-1
            )
        return True

    # Check for plan-level cycles using in-memory graph
    all_plan_keys: set[tuple[str, int]] = set()
    for node in nodes:
        if node.node_type in {"issue", "crossover"}:
            all_plan_keys.add((node.node_type, node.ref_id))
    graph_edges: list[tuple[tuple[str, int], tuple[str, int]]] = []
    for source_type, source_id, target_type, target_id, sat, extra in edges_to_add:
        source_key = (source_type, source_id)
        if sat == "converged" and isinstance(extra, list):
            # A converged node waits for every gate target, so each target points
            # into the convergence node. Model those as dependency edges so cycle
            # detection sees the real blocking dependency (the stored rule is a
            # self-loop, which would never register as a cycle).
            for target in extra:
                target_key = (str(target["type"]), int(target["id"]))
                if target_key in all_plan_keys and target_key != source_key:
                    graph_edges.append((target_key, source_key))
            continue
        target_key = (target_type, target_id)
        if (
            source_key in all_plan_keys
            and target_key in all_plan_keys
            and source_key != target_key
        ):
            graph_edges.append((source_key, target_key))

    cycle_nodes = _detect_plan_cycles(sorted(all_plan_keys), graph_edges)
    if cycle_nodes:
        cycle_node = next(iter(cycle_nodes))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "plan_convergence_cycle",
                "node_type": cycle_node[0],
                "node_id": cycle_node[1],
            },
        )

    # Persist the compiled rules
    created_rules: list[ContinuityRule] = []
    new_pairs: set[tuple[int, int]] = set()
    for (
        source_type, source_id,
        target_type, target_id,
        satisfaction_type, extra,
    ) in edges_to_add:
        source_type_cast = cast(ContinuityNodeType, source_type)
        target_type_cast = cast(ContinuityNodeType, target_type)
        existing = (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.source_type == source_type_cast,
                    ContinuityRule.source_id == source_id,
                    ContinuityRule.target_type == target_type_cast,
                    ContinuityRule.target_id == target_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.note == marker:
                continue
            if _is_equivalent_reusable_item_read_rule(
                existing,
                requested_satisfaction_type=satisfaction_type,
            ):
                if sync_canonical_edges:
                    for pair in rule_edge_pairs(existing):
                        new_pairs.add(pair)
                    await compile_rule_edges(
                        db,
                        existing,
                        plan_id=plan.id,
                        promote_cbl_occupants=True,
                    )
                continue
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_rule_conflict",
                    "source_node_id": f"{source_type}-{source_id}",
                    "target_node_id": f"{target_type}-{target_id}",
                },
            )
        if satisfaction_type != "converged" and await _would_create_cycle(
            db,
            user_id=user_id,
            source_type=source_type_cast,
            source_id=source_id,
            target_type=target_type_cast,
            target_id=target_id,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "continuity_cycle",
                    "source_node_id": f"{source_type}-{source_id}",
                    "target_node_id": f"{target_type}-{target_id}",
                },
            )
        rule_kwargs: dict[str, object] = {
            "user_id": user_id,
            "source_type": source_type_cast,
            "source_id": source_id,
            "target_type": target_type_cast,
            "target_id": target_id,
            "satisfaction_type": satisfaction_type,
            "note": marker,
        }
        if satisfaction_type == "checkpoint" and extra is not None:
            rule_kwargs["checkpoint_issue_id"] = extra
        if satisfaction_type == "converged" and extra is not None:
            rule_kwargs["convergence_targets"] = extra
        created_rule = ContinuityRule(**rule_kwargs)
        db.add(created_rule)
        created_rules.append(created_rule)
        await db.flush()
        if sync_canonical_edges:
            for pair in rule_edge_pairs(created_rule):
                new_pairs.add(pair)
    if sync_canonical_edges:
        # Retire compiled edges the new rule set no longer intends, then
        # (re)compile all intended pairs. The ON CONFLICT DO UPDATE in
        # compile_rule_edges refreshes notes on unchanged pairs so they
        # reference the new rule IDs (not the deleted ones).
        await retire_rule_edges(
            db, user_id=user_id, pairs=list(old_pairs - new_pairs), exclude_rule_id=-1
        )
        for created_rule in created_rules:
            if rule_edge_pairs(created_rule):
                await compile_rule_edges(
                    db,
                    created_rule,
                    plan_id=plan.id,
                    promote_cbl_occupants=True,
                )
    return True


def plan_source_paths(plan: ContinuityPlan) -> list[str]:
    """Return unique CBL source paths retained by plan nodes in source order."""
    paths: list[str] = []
    for node in plan.nodes_json or []:
        placements = node.get("source_cbl_placements")
        if isinstance(placements, list):
            for placement in placements:
                if not isinstance(placement, dict):
                    continue
                path = placement.get("source_path")
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
        source_paths = node.get("source_paths")
        if isinstance(source_paths, list | tuple):
            for path in source_paths:
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
    return paths


async def list_continuity_plan_items(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[ContinuityPlanListItem]:
    """Return typed Reading Plan list items for one user, newest first."""
    rows = await plans_for_user(db, user_id=user_id)
    ordered = sorted(rows, key=lambda plan: plan.updated_at, reverse=True)
    return [
        ContinuityPlanListItem(
            id=plan.id,
            name=plan.name,
            ordering_mode=plan.ordering_mode,
            lane_count=len(plan.lanes_json),
            step_count=len(plan.nodes_json),
            source_paths=plan_source_paths(plan),
            updated_at=plan.updated_at,
        )
        for plan in ordered
    ]


async def retire_plan_edges_for_deletion(
    db: AsyncSession, *, user_id: int, plan_id: int
) -> None:
    """Retire canonical edges compiled by one plan before its rules are deleted.

    After the Roll cutover (#2553) those Dependency rows are the only Roll
    authority, so plan deletion must clean them up or orphaned rows keep
    blocking. A pair is kept when another surviving rule still compiles to
    it, or another plan still links it through ``reading_plan_dependencies``.
    Standalone reader-created edges are never deleted here.
    """
    from app.services.canonical_constraint_compiler import (
        rule_compiled_note_filter,
        rule_edge_pairs,
    )

    marker = plan_rule_marker(plan_id)
    plan_rules = list(
        (
            await db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.note == marker,
                )
            )
        )
        .scalars()
        .all()
    )
    deleted_ids = {r.id for r in plan_rules}
    pairs = {p for rule in plan_rules for p in rule_edge_pairs(rule)}
    linked_pairs = {
        (source_id, target_id)
        for source_id, target_id in (
            await db.execute(
                select(Dependency.source_issue_id, Dependency.target_issue_id)
                .join(
                    ReadingPlanDependency,
                    ReadingPlanDependency.dependency_id == Dependency.id,
                )
                .where(ReadingPlanDependency.plan_id == plan_id)
            )
        ).all()
    }
    pairs.update(linked_pairs)
    if not pairs:
        return
    survivor_query = select(ContinuityRule).where(
        ContinuityRule.user_id == user_id,
        ContinuityRule.satisfaction_type.in_(("item_read", "checkpoint", "converged")),
    )
    if deleted_ids:
        survivor_query = survivor_query.where(ContinuityRule.id.not_in(list(deleted_ids)))
    survivors = list((await db.execute(survivor_query)).scalars().all())
    survivor_pairs = {p for r in survivors for p in rule_edge_pairs(r)}
    other_plan_pairs = {
        (source_id, target_id)
        for source_id, target_id in (
            await db.execute(
                select(Dependency.source_issue_id, Dependency.target_issue_id)
                .join(
                    ReadingPlanDependency,
                    ReadingPlanDependency.dependency_id == Dependency.id,
                )
                .where(
                    ReadingPlanDependency.plan_id != plan_id,
                    tuple_(Dependency.source_issue_id, Dependency.target_issue_id).in_(
                        list(pairs)
                    ),
                )
            )
        ).all()
    }
    keep = survivor_pairs | other_plan_pairs
    for source_id, target_id in pairs - keep:
        await db.execute(
            delete(Dependency).where(
                Dependency.source_issue_id == source_id,
                Dependency.target_issue_id == target_id,
                rule_compiled_note_filter(),
            )
        )
