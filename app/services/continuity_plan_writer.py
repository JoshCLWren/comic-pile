"""Shared canonical Reading Plan writer and strict-rule compiler.

Continuity-plan create/update and CBL adoption must persist Reading Plans
through one validated write path: node ownership is checked up front and the
plan-owned rules are compiled and replaced from the same node semantics. This
module owns that canonical path so a future CBL adoption slice can call it
instead of inventing a second strict compiler.

The authoritative policy for what may become a hard Roll prerequisite is
``docs/roll-eligibility-contract.md`` (Josh, 2026-10-12): custom CBLs own
intended reading order, canonical issue-to-issue Dependencies own hard Roll
restrictions, and "strict" means enforcing the checkpoints Josh selected —
never chaining every adjacent list entry.

The compiler's hard-edge semantics (#2553 Phase B / Josh's CBL verdict):
  1. Strict plans never invent whole-list Dependency chains. Consecutive
     list positions in different series are not hard edges. Roll follows
     natural in-series order (``Thread.next_unread_issue_id``) plus
     explicit crossover checkpoints and recorded standalone prerequisites
     only (e.g. Starman #55 → All-Star Comics (1999) #1).
  2. ``strict_sequential`` retains existing in-plan ``item_read`` pairs
     whose both endpoints remain; it does not infer thread-entry or
     adjacent Dependencies. Complicated order is authored as a custom CBL.
  3. Checkpoint nodes (including flags copied from a custom CBL) block
     the next node in the same lane — or, when ``checkpoint_target_ref_id``
     is set, exactly that issue. Explicit targets are never silently
     redirected by edits or reorders; a removed target drops the
     checkpoint. This is the only plan-authored cross-series hard gate the
     live compiler emits.
  4. Convergence gates compile ``converged`` self-loop rules, except gate
     targets that only duplicate the node's natural series predecessor —
     stale ``nodes_json`` convergence flags cannot recreate retired
     list-chain edges (see ``app/services/list_chain_guard.py``).
  5. Plan-level cycles and persisted-rule conflicts keep their stable codes.
  6. Informational plans add no inferred blockers.
  7. An ordinary unchanged strict save is a no-op for ContinuityRules and
     Dependencies when the desired edge set already matches: eligibility
     does not change, and removed cross-series chain edges do not return.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException
from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_rules import _would_create_cycle, ensure_owned_continuity_node
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanDependency, ReadingPlanIssue
from app.models.thread import Thread
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanListItem,
    ContinuityPlanNode,
    ContinuityPlanWrite,
    PlanOrderingMode,
)
from app.schemas.continuity_rule import ContinuityNodeType
from app.repositories.continuity_repository import plans_for_user
from app.repositories.reading_plan_repository import distinct_plan_issue_ids
from app.services.canonical_constraint_compiler import (
    compile_rule_edges,
    retire_rule_edges,
    rule_edge_pairs,
)
from app.services.list_chain_guard import is_retired_list_chain_pair
from app.services.ownership_guard import require_plan_issue_refs_owned
from app.services.reading_plan_normalization import (
    issue_ids_from_plan_json,
    rebuild_plan_membership,
)
from app.services.strict_plan_constraints import (
    IssueThreadIndex,
    load_issue_thread_index,
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
    serialized: list[dict[str, object]] = []
    for lane in lanes:
        row = lane.model_dump(exclude={"migration_contract"})
        contract = contracts.get(lane.id)
        if contract is not None:
            row["migration_contract"] = contract
        serialized.append(row)
    return serialized


def plan_rule_marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return f"{PLAN_RULE_MARKER_PREFIX}:{plan_id}"


def payload_issue_ids(nodes: Sequence[ContinuityPlanNode]) -> set[int]:
    """Return canonical issue ids from one editor payload.

    Args:
        nodes: Plan nodes from a create/update payload.

    Returns:
        Distinct issue ids referenced by issue-typed nodes.
    """
    return {node.ref_id for node in nodes if node.node_type == "issue"}


def _aware_utc(value: datetime) -> datetime:
    """Normalize a timestamp to UTC for optimistic-concurrency comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def guard_plan_write(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    incoming_ids: set[int],
    expected_updated_at: datetime | None,
) -> set[int]:
    """Reject stale leftover JSON and conflicting versions before a plan write.

    Shared by ordinary PUT and custom-CBL apply so neither path can rebuild
    membership from leftover ``nodes_json`` or clobber a newer plan version.

    Args:
        db: Async database session.
        plan: Owned plan being replaced.
        incoming_ids: Issue ids the writer is about to persist.
        expected_updated_at: Optional optimistic-concurrency token.

    Returns:
        Current normalized membership issue ids, snapshotted before rebuild.

    Raises:
        HTTPException: 409 ``plan_version_conflict`` when ``expected_updated_at``
            does not match ``plan.updated_at``. 409 ``stale_plan_nodes`` when
            the incoming issue set equals leftover ``nodes_json`` and not
            membership.
    """
    if expected_updated_at is not None:
        if _aware_utc(expected_updated_at) != _aware_utc(plan.updated_at):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_version_conflict",
                    "expected_updated_at": plan.updated_at.isoformat(),
                },
            )
    membership_ids = set(await distinct_plan_issue_ids(db, plan_id=plan.id))
    json_ids = issue_ids_from_plan_json(plan.nodes_json)
    if membership_ids and incoming_ids == json_ids and incoming_ids != membership_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_plan_nodes",
                "membership_issue_count": len(membership_ids),
                "payload_issue_count": len(incoming_ids),
            },
        )
    return membership_ids


async def guard_plan_update(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    payload: ContinuityPlanWrite,
) -> set[int]:
    """Reject stale leftover JSON and conflicting versions before a PUT write.

    Args:
        db: Async database session.
        plan: Owned plan being replaced.
        payload: Incoming editor payload.

    Returns:
        Current normalized membership issue ids, snapshotted before rebuild.

    Raises:
        HTTPException: 409 ``plan_version_conflict`` or ``stale_plan_nodes``.
    """
    return await guard_plan_write(
        db,
        plan=plan,
        incoming_ids=payload_issue_ids(payload.nodes),
        expected_updated_at=payload.expected_updated_at,
    )


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
    # Issue references are bulk-checked through the central ownership guard
    # (issue #3225): ownership resolves join-through-thread, and shared
    # catalog links never authorize membership.
    await require_plan_issue_refs_owned(
        db,
        user_id=user_id,
        refs={node.ref_id: node.id for node in nodes if node.node_type == "issue"},
    )
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
        if node.node_type == "issue":
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


def _nodes_by_lane(
    nodes: Sequence[ContinuityPlanNode],
) -> dict[str, list[ContinuityPlanNode]]:
    """Group plan nodes by lane id, sorted by display position."""
    grouped: dict[str, list[ContinuityPlanNode]] = {}
    for node in nodes:
        grouped.setdefault(node.lane_id, []).append(node)
    for lane_nodes in grouped.values():
        lane_nodes.sort(key=lambda item: item.position)
    return grouped


def preserve_checkpoint_targets(
    current: Sequence[ContinuityPlanNode],
    incoming: Sequence[ContinuityPlanNode],
) -> list[ContinuityPlanNode]:
    """Keep durable targets when an older enabled-checkpoint payload omits them.

    Explicit target fields remain authoritative. Disabling a checkpoint clears
    its semantics rather than restoring stored targets.
    """
    by_issue = {(node.node_type, node.ref_id): node for node in current}
    result: list[ContinuityPlanNode] = []
    target_fields = {"checkpoint_target_ref_id", "checkpoint_target_ref_ids"}
    for node in incoming:
        old = by_issue.get((node.node_type, node.ref_id))
        if (
            old is not None
            and node.is_checkpoint
            and not target_fields.intersection(node.model_fields_set)
        ):
            node = node.model_copy(
                update={
                    "checkpoint_target_ref_id": old.checkpoint_target_ref_id,
                    "checkpoint_target_ref_ids": list(old.checkpoint_target_ref_ids),
                }
            )
        result.append(node)
    return result


def _checkpoint_edges_from_nodes(
    nodes: Sequence[ContinuityPlanNode],
) -> list[tuple[str, int, str, int, str, int | None]]:
    """Return checkpoint compile edges authored on plan nodes.

    A checkpoint with explicit ``checkpoint_target_ref_id`` blocks that issue
    and only that issue: editing or reordering the list never silently
    redirects it to a different comic, and a removed target drops the
    checkpoint instead of retargeting the neighbor (contract:
    docs/roll-eligibility-contract.md). Without an explicit target, the
    legacy flag blocks only the next node in the same lane. Cross-series
    consecutive list positions without ``is_checkpoint`` never appear here.
    """
    nodes_by_lane = _nodes_by_lane(nodes)
    by_issue_ref = {node.ref_id: node for node in nodes if node.node_type == "issue"}
    edges: list[tuple[str, int, str, int, str, int | None]] = []
    for node in nodes:
        if not node.is_checkpoint:
            continue
        explicit_targets = set(node.checkpoint_target_ref_ids)
        if node.checkpoint_target_ref_id is not None:
            explicit_targets.add(node.checkpoint_target_ref_id)
        if explicit_targets:
            for target_id in sorted(explicit_targets):
                target_node = by_issue_ref.get(target_id)
                if target_node is None or target_node.ref_id == node.ref_id:
                    continue
                checkpoint_issue_id = node.ref_id if node.node_type == "issue" else None
                edges.append(
                    (
                        node.node_type,
                        node.ref_id,
                        target_node.node_type,
                        target_node.ref_id,
                        "checkpoint",
                        checkpoint_issue_id,
                    )
                )
            continue
        lane_nodes = nodes_by_lane.get(node.lane_id, [])
        node_index = next(
            (index for index, candidate in enumerate(lane_nodes) if candidate.id == node.id),
            None,
        )
        if node_index is None or node_index >= len(lane_nodes) - 1:
            continue
        next_node = lane_nodes[node_index + 1]
        if next_node.node_type == node.node_type and next_node.ref_id == node.ref_id:
            continue
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
    return edges


def _edge_identity(
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    satisfaction_type: str,
    extra: int | list[dict[str, int | str]] | None,
) -> tuple[object, ...]:
    """Return a hashable identity for one compiled plan-owned edge."""
    if satisfaction_type == "converged" and isinstance(extra, list):
        targets = tuple(sorted((str(target["type"]), int(target["id"])) for target in extra))
        return (
            source_type,
            source_id,
            target_type,
            target_id,
            satisfaction_type,
            targets,
        )
    return (
        source_type,
        source_id,
        target_type,
        target_id,
        satisfaction_type,
        extra,
    )


def _rule_edge_identity(rule: ContinuityRule) -> tuple[object, ...]:
    """Return the compile identity of one persisted plan-owned rule."""
    extra: int | list[dict[str, int | str]] | None
    if rule.satisfaction_type == "checkpoint":
        extra = rule.checkpoint_issue_id
    elif rule.satisfaction_type == "converged":
        raw_targets = rule.convergence_targets or []
        extra = [
            {"type": str(target["type"]), "id": int(target["id"])}
            for target in raw_targets
            if isinstance(target, dict)
        ]
    else:
        extra = None
    return _edge_identity(
        rule.source_type,
        rule.source_id,
        rule.target_type,
        rule.target_id,
        rule.satisfaction_type,
        extra,
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
    prior_ordering_mode: str | None = None,
) -> bool:
    """Replace only rules owned by this plan and compile plan semantics into rules.

    This compiles:
    1. Existing in-plan ``item_read`` pairs that still have both endpoints
    2. Checkpoint rules from nodes with ``is_checkpoint=True``
    3. Converged rules from nodes with ``convergence_gate`` entries
    4. Caller-supplied selected ``item_read`` pairs that are still in the plan

    Checkpoint semantics: a node marked as checkpoint blocks the next node in
    the same lane until the checkpoint node is read. Custom CBL apply copies
    entry ``is_checkpoint`` onto those nodes.

    Convergence semantics: a node with convergence targets is blocked until all
    referenced upstream nodes are read.

    An equivalent non-plan-owned ``item_read`` rule may satisfy a strict edge
    without changing that standalone rule's ownership or provenance.

    Args:
        db: Async database session.
        user_id: Authenticated plan owner.
        plan: The persisted (or to-be-persisted) plan owning the compiled rules.
        nodes: Canonical node set to compile from.
        ordering_mode: Plan ordering mode; only ``strict_sequential`` retains
            or accepts explicit ``item_read`` pairs. Natural series order is
            ``Thread.next_unread_issue_id``, not inferred Dependencies.
        sync_canonical_edges: When True (default), retire this plan's stale
            compiled edges and compile the new rules into canonical
            Dependencies (#2553). An unchanged membership save restores
            the existing plan-owned ``item_read`` set, so Roll eligibility
            does not change.
        extra_item_read_pairs: Explicit selected hard restrictions to compile.
            Same-thread pairs are ignored when newly supplied. Existing
            plan-owned same-thread pairs are retained. Live plan create/update
            omit this; migrations pass classified genuine prerequisites.
            Ignored on an ordinary no-change strict save so extras cannot
            invent restrictions.
        prior_ordering_mode: Ordering mode before this write. An ordinary
            no-change save retains existing item_read only when this was
            already ``strict_sequential``. Create and mode changes omit it.

    Returns:
        True when all rules compiled without cycle conflicts.
    """
    # Snapshot membership and plan-owned item_read *before* rebuild so an
    # ordinary no-change save can restore those pairs identically (#3499).
    prior_membership_ids = set(await distinct_plan_issue_ids(db, plan_id=plan.id))
    marker = plan_rule_marker(plan.id)
    old_plan_rules = list(
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
    old_pairs: set[tuple[int, int]] = set()
    prior_item_read: set[tuple[int, int]] = set()
    for old_rule in old_plan_rules:
        if sync_canonical_edges:
            old_pairs.update(rule_edge_pairs(old_rule))
        if (
            old_rule.satisfaction_type == "item_read"
            and old_rule.source_type == "issue"
            and old_rule.target_type == "issue"
        ):
            prior_item_read.add((old_rule.source_id, old_rule.target_id))

    # Build node lookup for convergence gate resolution
    node_map: dict[str, ContinuityPlanNode] = {node.id: node for node in nodes}

    # Collect all edges to compile (for cycle detection / no-op compare)
    convergence_target = dict[str, int | str]
    edges_to_add: list[tuple[str, int, str, int, str, int | list[convergence_target] | None]] = []

    # 1. Strict-sequential item_read: retain existing in-plan pairs whose
    # both endpoints remain. Never infer thread-entry or list adjacency.
    incoming_ids = payload_issue_ids(nodes)
    unchanged_strict_save = (
        ordering_mode == "strict_sequential"
        and incoming_ids == prior_membership_ids
        and prior_ordering_mode == "strict_sequential"
    )
    if ordering_mode == "strict_sequential":
        compiled_item_read: set[tuple[int, int]] = {
            pair for pair in prior_item_read if pair[0] in incoming_ids and pair[1] in incoming_ids
        }
        if extra_item_read_pairs and not unchanged_strict_save:
            issue_index: dict[int, IssueThreadIndex] = await load_issue_thread_index(
                db, incoming_ids
            )
            for source_id, target_id in extra_item_read_pairs:
                pair = (source_id, target_id)
                if pair in compiled_item_read or source_id == target_id:
                    continue
                if source_id not in incoming_ids or target_id not in incoming_ids:
                    continue
                source_meta = issue_index.get(source_id)
                target_meta = issue_index.get(target_id)
                if source_meta is None or target_meta is None:
                    continue
                if source_meta.thread_id == target_meta.thread_id:
                    continue
                compiled_item_read.add(pair)
        for source_id, target_id in compiled_item_read:
            edges_to_add.append(
                (
                    "issue",
                    source_id,
                    "issue",
                    target_id,
                    "item_read",
                    None,
                )
            )

    # 2. Checkpoint rules: only explicit is_checkpoint nodes (custom CBL or
    # planner). Never treat ordinary consecutive list positions as checkpoints.
    edges_to_add.extend(_checkpoint_edges_from_nodes(nodes))

    # 3. Converged rules: node waits for all convergence gate targets
    convergence_index: dict[int, IssueThreadIndex] = {}
    if any(node.convergence_gate for node in nodes):
        convergence_index = await load_issue_thread_index(db, incoming_ids)
    for node in nodes:
        if not node.convergence_gate:
            continue
        node_meta = convergence_index.get(node.ref_id)
        gate_targets: list[convergence_target] = []
        for target in node.convergence_gate:
            resolved = node_map.get(target.node_id)
            if resolved is None:
                continue
            prereq_meta = convergence_index.get(resolved.ref_id)
            if (
                node_meta is not None
                and prereq_meta is not None
                and is_retired_list_chain_pair(prereq_meta, node_meta)
            ):
                # Stale nodes_json convergence flags cannot recreate retired
                # list-chain edges: a gate whose only meaning is "read my own
                # series predecessor first" is Issue.position geometry, not a
                # hard Dependency (docs/roll-eligibility-contract.md).
                continue
            gate_targets.append(
                {
                    "type": resolved.node_type,
                    "id": resolved.ref_id,
                }
            )
        if not gate_targets:
            continue
        edges_to_add.append(
            (
                node.node_type,
                node.ref_id,
                node.node_type,
                node.ref_id,
                "converged",
                gate_targets,
            )
        )

    desired_identities = {
        _edge_identity(
            source_type,
            source_id,
            target_type,
            target_id,
            satisfaction_type,
            extra,
        )
        for source_type, source_id, target_type, target_id, satisfaction_type, extra in edges_to_add
    }
    existing_identities = {_rule_edge_identity(rule) for rule in old_plan_rules}

    # Normalized membership/provenance always reflects the latest nodes in the
    # same transaction: informational plans with no compiled edges still own
    # relational membership, and a later rule-compilation failure rolls the
    # membership rebuild back with the rest of the write.
    await rebuild_plan_membership(db, plan_id=plan.id, nodes=nodes)

    # True no-op: unchanged strict membership whose desired edge set already
    # matches plan-owned rules. Skip delete/recreate so ContinuityRules and
    # Dependencies do not churn, and removed chain edges cannot return.
    if unchanged_strict_save and desired_identities == existing_identities:
        # Roll-eligibility contract: an unchanged strict save must still repair
        # a missing canonical Dependency for a surviving plan-owned rule,
        # instead of treating the unchanged payload as a complete no-op.
        if sync_canonical_edges and old_pairs:
            existing_pairs = {
                (int(source_id), int(target_id))
                for source_id, target_id in (
                    await db.execute(
                        select(
                            Dependency.source_issue_id,
                            Dependency.target_issue_id,
                        ).where(
                            tuple_(
                                Dependency.source_issue_id,
                                Dependency.target_issue_id,
                            ).in_(list(old_pairs))
                        )
                    )
                ).all()
            }
            missing = old_pairs - existing_pairs
            if missing:
                for rule in old_plan_rules:
                    if any(pair in missing for pair in rule_edge_pairs(rule)):
                        await compile_rule_edges(
                            db,
                            rule,
                            plan_id=plan.id,
                            promote_cbl_occupants=True,
                        )
        await db.flush()
        return True

    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )
    await db.flush()

    if not edges_to_add:
        if sync_canonical_edges:
            # The new rule set is empty: retire all previously compiled
            # pairs so orphaned edges don't keep blocking Roll (#2553).
            await retire_rule_edges(db, user_id=user_id, pairs=list(old_pairs), exclude_rule_id=-1)
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

    # Persist the compiled rules
    created_rules: list[ContinuityRule] = []
    new_pairs: set[tuple[int, int]] = set()
    for (
        source_type,
        source_id,
        target_type,
        target_id,
        satisfaction_type,
        extra,
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
    membership_counts: dict[int, int] = {}
    if ordered:
        membership_counts = dict(
            (
                await db.execute(
                    select(ReadingPlanIssue.plan_id, func.count())
                    .where(ReadingPlanIssue.plan_id.in_([plan.id for plan in ordered]))
                    .group_by(ReadingPlanIssue.plan_id)
                )
            ).all()
        )
    return [
        ContinuityPlanListItem(
            id=plan.id,
            name=plan.name,
            ordering_mode=plan.ordering_mode,
            lane_count=len(plan.lanes_json),
            step_count=membership_counts.get(plan.id, 0) or len(plan.nodes_json),
            source_paths=plan_source_paths(plan),
            updated_at=plan.updated_at,
        )
        for plan in ordered
    ]


async def retire_plan_edges_for_deletion(db: AsyncSession, *, user_id: int, plan_id: int) -> None:
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
                    tuple_(Dependency.source_issue_id, Dependency.target_issue_id).in_(list(pairs)),
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
