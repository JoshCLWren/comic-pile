"""Shared persistence and hard-rule compilation for canonical Reading Plans."""

from __future__ import annotations

from typing import cast

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_plan_readiness import _detect_plan_cycles, plan_rule_marker
from app.continuity_rules import ensure_owned_continuity_node
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode, ContinuityPlanWrite
from app.schemas.continuity_rule import ContinuityNodeType
from app.services.continuity_cycle import would_create_continuity_cycle


def plan_marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return plan_rule_marker(plan_id)


async def validate_plan_node_ownership(
    db: AsyncSession, *, user_id: int, nodes: list[ContinuityPlanNode]
) -> None:
    """Validate every referenced issue, crossover, or thread before plan mutation."""
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


async def replace_compiled_plan_rules(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
    payload: ContinuityPlanWrite,
) -> None:
    """Replace the hard rules owned by one Reading Plan from its explicit semantics."""
    marker = plan_marker(plan.id)
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )

    node_map = {node.id: node for node in payload.nodes}
    nodes_by_lane: dict[str, list[ContinuityPlanNode]] = {}
    for node in payload.nodes:
        nodes_by_lane.setdefault(node.lane_id, []).append(node)
    for lane_nodes in nodes_by_lane.values():
        lane_nodes.sort(key=lambda item: item.position)

    convergence_target = dict[str, int | str]
    edges: list[tuple[str, int, str, int, str, int | list[convergence_target] | None]] = []

    if payload.ordering_mode == "strict_sequential" and len(payload.nodes) >= 2:
        ordered = sorted(payload.nodes, key=lambda item: item.position)
        for source, target in zip(ordered, ordered[1:], strict=False):
            edges.append(
                (
                    source.node_type,
                    source.ref_id,
                    target.node_type,
                    target.ref_id,
                    "item_read",
                    None,
                )
            )

    for node in payload.nodes:
        if not node.is_checkpoint:
            continue
        lane_nodes = nodes_by_lane.get(node.lane_id, [])
        node_index = next((i for i, item in enumerate(lane_nodes) if item.id == node.id), None)
        if node_index is None or node_index >= len(lane_nodes) - 1:
            continue
        next_node = lane_nodes[node_index + 1]
        checkpoint_issue_id = node.ref_id if node.node_type == "issue" else None
        edges.append(
            (
                node.node_type,
                node.ref_id,
                next_node.node_type,
                next_node.ref_id,
                "checkpoint",
                checkpoint_issue_id,
            )
        )

    for node in payload.nodes:
        if not node.convergence_gate:
            continue
        gate_targets: list[convergence_target] = []
        for target in node.convergence_gate:
            resolved = node_map.get(target.node_id)
            if resolved is not None:
                gate_targets.append({"type": resolved.node_type, "id": resolved.ref_id})
        if gate_targets:
            edges.append(
                (
                    node.node_type,
                    node.ref_id,
                    node.node_type,
                    node.ref_id,
                    "converged",
                    gate_targets,
                )
            )

    if not edges:
        return

    all_plan_keys = {
        (node.node_type, node.ref_id)
        for node in payload.nodes
        if node.node_type in {"issue", "crossover"}
    }
    graph_edges: list[tuple[tuple[str, int], tuple[str, int]]] = []
    for source_type, source_id, target_type, target_id, satisfaction, extra in edges:
        source_key = (source_type, source_id)
        if satisfaction == "converged" and isinstance(extra, list):
            for target in extra:
                target_key = (str(target["type"]), int(target["id"]))
                if target_key in all_plan_keys and target_key != source_key:
                    graph_edges.append((target_key, source_key))
            continue
        target_key = (target_type, target_id)
        if source_key in all_plan_keys and target_key in all_plan_keys and source_key != target_key:
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

    for source_type, source_id, target_type, target_id, satisfaction, extra in edges:
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
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_rule_conflict",
                    "source_node_id": f"{source_type}-{source_id}",
                    "target_node_id": f"{target_type}-{target_id}",
                },
            )
        if satisfaction != "converged" and await would_create_continuity_cycle(
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
            "satisfaction_type": satisfaction,
            "note": marker,
        }
        if satisfaction == "checkpoint" and extra is not None:
            rule_kwargs["checkpoint_issue_id"] = extra
        if satisfaction == "converged" and extra is not None:
            rule_kwargs["convergence_targets"] = extra
        db.add(ContinuityRule(**rule_kwargs))
        await db.flush()


async def apply_continuity_plan_write(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
    payload: ContinuityPlanWrite,
) -> None:
    """Apply one validated canonical Reading Plan write without committing the transaction."""
    await validate_plan_node_ownership(db, user_id=user_id, nodes=payload.nodes)
    plan.name = payload.name
    plan.ordering_mode = payload.ordering_mode
    plan.lanes_json = [lane.model_dump() for lane in payload.lanes]
    plan.nodes_json = [node.model_dump() for node in payload.nodes]
    await replace_compiled_plan_rules(db, user_id=user_id, plan=plan, payload=payload)
