"""Shared canonical Reading Plan writer and strict-rule compiler.

Continuity-plan create/update and CBL adoption must persist Reading Plans
through one validated write path: node ownership is checked up front and the
plan-owned rules are compiled and replaced from the same node semantics. This
module owns that canonical path so a future CBL adoption slice can call it
instead of inventing a second strict compiler.

The compiler preserves the historical router semantics exactly:
  1. ``strict_sequential`` plans compile adjacent ``item_read`` edges;
  2. checkpoint nodes block the next node in the same lane;
  3. convergence gates compile ``converged`` self-loop rules;
  4. plan-level cycles and persisted-rule conflicts keep their stable codes.
"""

from __future__ import annotations

from typing import cast

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_rules import _would_create_cycle, ensure_owned_continuity_node
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode, PlanOrderingMode
from app.schemas.continuity_rule import ContinuityNodeType


PLAN_RULE_MARKER_PREFIX = "continuity-plan"


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
    """Return whether an existing standalone rule already satisfies a plan edge.

    Equivalent standalone ``item_read`` rules may satisfy the same hard edge
    without being re-owned by the Reading Plan. Rules owned by another Reading
    Plan remain conflicts so two plans cannot silently share execution ownership.
    """
    note = rule.note or ""
    return (
        requested_satisfaction_type == "item_read"
        and rule.satisfaction_type == "item_read"
        and not note.startswith("continuity-plan:")
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
) -> bool:
    """Replace only rules owned by this plan and compile plan semantics into rules.

    This compiles:
    1. Strict-sequential adjacent edges (existing behavior)
    2. Checkpoint rules from nodes with ``is_checkpoint=True``
    3. Converged rules from nodes with ``convergence_gate`` entries

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
            adjacent order rules.

    Returns:
        True when all rules compiled without cycle conflicts.
    """
    marker = plan_rule_marker(plan.id)
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )

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

    # 1. Strict-sequential adjacent edges
    if ordering_mode == "strict_sequential" and len(nodes) >= 2:
        ordered = sorted(nodes, key=lambda node: node.position)
        for source, target in zip(ordered, ordered[1:], strict=False):
            edges_to_add.append((
                source.node_type, source.ref_id,
                target.node_type, target.ref_id,
                "item_read", None,
            ))

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
        db.add(ContinuityRule(**rule_kwargs))
        await db.flush()
    return True
