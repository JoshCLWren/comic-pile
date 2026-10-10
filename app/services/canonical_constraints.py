"""Compile hard authoring intent into Dependencies at write/backfill boundaries.

This adapter does not inspect read state or determine readiness. Roll and its
explanations consume only persisted canonical Dependencies after compilation.
Historical CBL mirrors and natural Thread progression never create hard edges.
"""

import re

from fastapi import HTTPException

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import canonical_constraint_repository as repository
from app.schemas.continuity_plan import ContinuityPlanNode


async def synchronize_canonical_constraints(db: AsyncSession, user_id: int) -> int:
    """Persist proven issue-level hard constraints in the caller's transaction.

    Compatibility rules remain authoring/provenance records during retirement.
    Shared plan constraints converge to one executable pair with many plan links.
    Unsupported generalized legacy rules are retained as compatibility records;
    they are never guessed into issue-level constraints.
    """
    from app.repositories.continuity_repository import lock_continuity_graph

    await lock_continuity_graph(db, user_id)
    await db.flush()
    rules, plans = await repository.authoring_constraints(db, user_id)
    pairs: set[tuple[int, int]] = set()
    plan_pairs: dict[int, set[tuple[int, int]]] = {plan.id: set() for plan in plans}
    for rule in rules:
        if (rule.note or "").startswith("cbl-order:") or rule.note == repository.COMPILED_NOTE:
            continue
        if rule.target_type != "issue":
            continue
        edges: set[tuple[int, int]] = set()
        if rule.satisfaction_type == "item_read" and rule.source_type == "issue":
            edges.add((rule.source_id, rule.target_id))
        elif rule.satisfaction_type == "checkpoint" and rule.checkpoint_issue_id is not None:
            edges.add((rule.checkpoint_issue_id, rule.target_id))
        elif rule.satisfaction_type == "converged":
            for target in rule.convergence_targets or []:
                if target.get("type") == "issue":
                    edges.add((int(target["id"]), rule.target_id))
        pairs.update(edges)
        match = re.fullmatch(r"continuity-plan:(\d+)", rule.note or "")
        if match and int(match.group(1)) in plan_pairs:
            plan_pairs[int(match.group(1))].update(edges)

    # Plan ownership of a shared edge cannot be recovered solely from one
    # legacy rule note. Compile each plan's hard intent into its own link set.
    for plan in plans:
        nodes = [ContinuityPlanNode.model_validate(node) for node in plan.nodes_json or []]
        node_map = {node.id: node for node in nodes}
        edges = plan_pairs[plan.id]
        ordered = sorted(nodes, key=lambda node: node.position)
        if plan.ordering_mode == "strict_sequential":
            for source, target in zip(ordered, ordered[1:], strict=False):
                if source.node_type == target.node_type == "issue":
                    edges.add((source.ref_id, target.ref_id))
        lanes: dict[str, list[ContinuityPlanNode]] = {}
        for node in ordered:
            lanes.setdefault(node.lane_id, []).append(node)
            if node.node_type == "issue":
                for gate in node.convergence_gate or []:
                    source = node_map.get(gate.node_id)
                    if source and source.node_type == "issue":
                        edges.add((source.ref_id, node.ref_id))
        for lane in lanes.values():
            for source, target in zip(lane, lane[1:], strict=False):
                if source.is_checkpoint and source.node_type == target.node_type == "issue":
                    edges.add((source.ref_id, target.ref_id))
        pairs.update(edges)

    positions = await repository.owned_issue_positions(
        db, user_id, {issue for pair in pairs for issue in pair}
    )
    filtered: set[tuple[int, int]] = set()
    for source, target in pairs:
        if source not in positions or target not in positions:
            raise ValueError("canonical hard constraint references an unowned or missing Issue")
        if source == target:
            raise ValueError("canonical hard constraint cannot be self-referential")
        source_thread, source_position = positions[source]
        target_thread, target_position = positions[target]
        if source_thread == target_thread and source_position < target_position:
            continue  # Thread progression already owns this order.
        filtered.add((source, target))
    # Validate against standalone canonical edges too: the retired reverse
    # trigger no longer mirrors those edges into compatibility rules.
    existing = await repository.canonical_dependencies(db, user_id)
    combined = filtered | {
        (dep.source_issue_id, dep.target_issue_id)
        for dep in existing
        if dep.note != repository.COMPILED_NOTE
    }
    adjacency: dict[int, set[int]] = {}
    indegree: dict[int, int] = {}
    for source, target in combined:
        adjacency.setdefault(source, set()).add(target)
        indegree.setdefault(source, 0)
        indegree[target] = indegree.get(target, 0) + 1
    ready = [issue for issue, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        issue = ready.pop()
        visited += 1
        for target in adjacency.get(issue, set()):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(indegree):
        raise HTTPException(status_code=409, detail={"code": "continuity_cycle"})
    for edges in plan_pairs.values():
        edges.intersection_update(filtered)
    return await repository.persist_compiled_constraints(db, user_id, filtered, plan_pairs, rules)
