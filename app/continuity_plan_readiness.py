"""Plan-scoped live readiness evaluation for continuity-plan visualization."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_chains import resolve_continuity_chains
from app.continuity_readiness import (
    _GraphSnapshot,
    _crossover_readiness,
    _group_issue_ids,
    _is_read,
    _issue_readiness,
    _load_snapshot,
)
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.schemas.continuity_plan import (
    ContinuityPlanChainNode,
    ContinuityPlanLane,
    ContinuityPlanNodeReadiness,
    ContinuityPlanReadinessDiagnostic,
    ContinuityPlanReadinessResponse,
    ContinuityPlanReadinessSummary,
    PlanNodeType,
)
from app.schemas.continuity_readiness import ContinuityBlocker

PLAN_RULE_MARKER_PREFIX = "continuity-plan"


@dataclass(frozen=True)
class _PlanNodeRow:
    """One normalized visible plan node derived from persisted JSON."""

    id: str
    node_type: str
    raw_node_type: str
    ref_id: int
    lane_id: str
    position: int


def plan_rule_marker(plan_id: int) -> str:
    """Return the durable ownership marker for rules compiled from one plan."""
    return f"{PLAN_RULE_MARKER_PREFIX}:{plan_id}"


def _node_label(
    node_type: PlanNodeType,
    ref_id: int,
    snapshot: _GraphSnapshot,
) -> str:
    """Return a stable human label for a visible plan node."""
    if node_type == "crossover":
        group = snapshot.groups.get(ref_id)
        return group.name if group is not None else f"Crossover {ref_id}"
    if node_type == "thread":
        thread = snapshot.threads.get(ref_id)
        if thread is not None:
            return thread.title
        return f"Thread {ref_id}"
    issue = snapshot.issues.get(ref_id)
    if issue is None:
        return f"Issue {ref_id}"
    thread = snapshot.threads.get(issue.thread_id)
    if thread is None:
        return f"Issue {issue.issue_number}"
    return f"{thread.title} #{issue.issue_number}"


def _thread_complete(thread_id: int, snapshot: _GraphSnapshot) -> bool:
    """Return whether every issue of one owned thread is read."""
    thread = snapshot.threads.get(thread_id)
    return thread is not None and thread.next_unread_issue_id is None


def _is_complete(node_type: PlanNodeType, ref_id: int, snapshot: _GraphSnapshot) -> bool:
    """Return whether the referenced node is fully read."""
    if node_type == "issue":
        return _is_read(ref_id, snapshot)
    if node_type == "thread":
        return _thread_complete(ref_id, snapshot)
    member_ids = _group_issue_ids(ref_id, snapshot)
    return bool(member_ids) and all(_is_read(issue_id, snapshot) for issue_id in member_ids)


def _readiness_blockers(
    node_type: PlanNodeType,
    ref_id: int,
    snapshot: _GraphSnapshot,
) -> tuple[list[ContinuityBlocker], int | None]:
    """Return direct readiness blockers mirroring the continuity readiness API."""
    if node_type == "issue":
        return _issue_readiness(ref_id, snapshot), None
    if node_type == "thread":
        thread = snapshot.threads.get(ref_id)
        if thread is None:
            return [], None
        evaluated_issue_id = thread.next_unread_issue_id
        blockers = (
            _issue_readiness(evaluated_issue_id, snapshot)
            if evaluated_issue_id is not None
            else []
        )
        return blockers, evaluated_issue_id
    return _crossover_readiness(ref_id, snapshot), None


def _dangling_diagnostic(
    node_type: PlanNodeType,
    ref_id: int,
) -> ContinuityPlanReadinessDiagnostic:
    """Build the shared dangling-reference diagnostic for one plan node."""
    return ContinuityPlanReadinessDiagnostic(
        code="dangling_plan_reference",
        node_type=node_type,
        node_id=ref_id,
    )


async def _plan_edges(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
) -> list[tuple[tuple[str, int], tuple[str, int]]]:
    """Return compiled plan-owned edges whose endpoints stay inside the plan.

    Args:
        db: Database session used to load plan-owned compiled rules.
        user_id: Authenticated owner of the plan.
        plan: Persisted plan document being visualized.

    Returns:
        Directed edges between plan node keys derived from plan-owned rules.
    """
    marker = plan_rule_marker(plan.id)
    rule_result = await db.execute(
        select(ContinuityRule)
        .where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
        .order_by(ContinuityRule.id)
    )
    plan_keys: set[tuple[str, int]] = set()
    for node in plan.nodes_json:
        try:
            plan_keys.add((str(node.get("node_type", "")), int(node["ref_id"])))
        except (KeyError, TypeError, ValueError):
            continue
    edges: list[tuple[tuple[str, int], tuple[str, int]]] = []
    for rule in rule_result.scalars():
        source = (rule.source_type, rule.source_id)
        target = (rule.target_type, rule.target_id)
        if source in plan_keys and target in plan_keys:
            edges.append((source, target))
    return edges


def _detect_plan_cycles(
    nodes: list[tuple[str, int]],
    edges: list[tuple[tuple[str, int], tuple[str, int]]],
) -> set[tuple[str, int]]:
    """Return every node participating in a directed cycle among plan-owned rules.

    Args:
        nodes: Deterministically ordered plan node keys.
        edges: Directed plan-owned rule edges between plan node keys.

    Returns:
        The set of node keys that appear on at least one cycle.
    """
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
                if color[node] == 2:
                    continue
                if color[node] == 1:
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


async def _node_chains(
    db: AsyncSession,
    *,
    user_id: int,
    node_type: PlanNodeType,
    ref_id: int,
    snapshot: _GraphSnapshot,
) -> tuple[
    list[list[ContinuityPlanChainNode]],
    list[ContinuityPlanReadinessDiagnostic],
    list[ContinuityPlanChainNode],
]:
    """Resolve bounded prerequisite chains for one blocked plan node.

    Args:
        db: Database session used for any lazy traversal lookups.
        user_id: Authenticated owner of the plan.
        node_type: Visible plan node type.
        ref_id: Referenced issue, thread, or crossover identifier.
        snapshot: Preloaded readiness graph reused by the traversal.

    Returns:
        Deterministic prerequisite chains, traversal diagnostics, and readable leaves.
    """
    traversal = await resolve_continuity_chains(
        db,
        user_id=user_id,
        node_type=node_type,
        node_id=ref_id,
        snapshot=snapshot,
    )
    chains = [
        [
            ContinuityPlanChainNode(
                node_type=node.node_type,
                node_id=node.node_id,
                label=node.label,
                is_readable=node.is_readable,
            )
            for node in chain
        ]
        for chain in traversal.chains
    ]
    diagnostics = [
        ContinuityPlanReadinessDiagnostic(
            code=diagnostic.code,
            node_type=diagnostic.node_type,
            node_id=diagnostic.node_id,
            limit=diagnostic.limit,
        )
        for diagnostic in traversal.diagnostics
    ]
    readable_prerequisites = [
        ContinuityPlanChainNode(
            node_type=node.node_type,
            node_id=node.node_id,
            label=node.label,
            is_readable=node.is_readable,
        )
        for node in traversal.readable_prerequisites
    ]
    return chains, diagnostics, readable_prerequisites


async def evaluate_plan_readiness(
    db: AsyncSession,
    *,
    user_id: int,
    plan: ContinuityPlan,
    include_chains: bool = False,
) -> ContinuityPlanReadinessResponse:
    """Evaluate live readiness for every visible node of one owned plan.

    Per-node readability and blockers reuse the canonical continuity readiness
    evaluation so the plan visualization always agrees with the readiness API.
    Dangling legacy references and cyclic plan-owned rules are reported as
    structured diagnostics instead of crashing the render.

    Args:
        db: Database session used to load the owned readiness graph.
        user_id: Authenticated owner of the plan.
        plan: Persisted plan document being visualized.
        include_chains: Whether to resolve bounded prerequisite chains for every
            blocked node (heavier but enables inline chain explanation).

    Returns:
        Deterministic per-node readiness, aggregate diagnostics, and summary.
    """
    snapshot = await _load_snapshot(db, user_id)
    lanes = [ContinuityPlanLane(**lane) for lane in plan.lanes_json]
    lane_order = {lane.id: lane.order for lane in lanes}

    valid_types = {"issue", "crossover", "thread"}
    node_rows: list[_PlanNodeRow] = []
    for node in plan.nodes_json:
        node_type = str(node.get("node_type", ""))
        try:
            ref_id = int(node["ref_id"])
        except (KeyError, TypeError, ValueError):
            ref_id = 0
        node_rows.append(
            _PlanNodeRow(
                id=str(node.get("id", "")),
                node_type=node_type if node_type in valid_types else "issue",
                raw_node_type=node_type,
                ref_id=ref_id,
                lane_id=str(node.get("lane_id", "")),
                position=int(node.get("position", 0)),
            )
        )
    node_keys = [
        (row.node_type, row.ref_id)
        for row in node_rows
        if row.node_type in {"issue", "crossover"}
    ]
    edges = await _plan_edges(db, user_id=user_id, plan=plan)
    cycle_nodes = _detect_plan_cycles(node_keys, edges)

    readiness_nodes: list[ContinuityPlanNodeReadiness] = []
    plan_diagnostics: list[ContinuityPlanReadinessDiagnostic] = []

    for row in sorted(
        node_rows,
        key=lambda item: (
            lane_order.get(item.lane_id, 0),
            item.position,
            str(item.id),
        ),
    ):
        node_type = row.node_type
        ref_id = row.ref_id
        malformed = row.raw_node_type not in valid_types or ref_id <= 0
        exists = any(
            (
                node_type == "issue" and ref_id in snapshot.issues,
                node_type == "thread" and ref_id in snapshot.threads,
                node_type == "crossover" and ref_id in snapshot.groups,
            )
        )
        if malformed or not exists:
            readiness_nodes.append(
                ContinuityPlanNodeReadiness(
                    node_id=row.id,
                    node_type=node_type,
                    ref_id=ref_id,
                    lane_id=row.lane_id,
                    position=row.position,
                    label=_node_label(node_type, ref_id, snapshot),
                    is_readable=False,
                    is_complete=False,
                    blockers=[],
                    diagnostics=[_dangling_diagnostic(node_type, ref_id)],
                )
            )
            continue

        key = (node_type, ref_id)
        node_diagnostics: list[ContinuityPlanReadinessDiagnostic] = []
        if node_type in {"issue", "crossover"} and key in cycle_nodes:
            node_diagnostics.append(
                ContinuityPlanReadinessDiagnostic(
                    code="plan_cycle_detected",
                    node_type=node_type,
                    node_id=ref_id,
                )
            )

        blockers, evaluated_issue_id = _readiness_blockers(node_type, ref_id, snapshot)
        is_readable = not blockers
        is_complete = _is_complete(node_type, ref_id, snapshot)

        chains: list[list[ContinuityPlanChainNode]] = []
        readable_prerequisites: list[ContinuityPlanChainNode] = []
        if include_chains and not is_readable:
            chains, traversal_diagnostics, readable_prerequisites = await _node_chains(
                db,
                user_id=user_id,
                node_type=node_type,
                ref_id=ref_id,
                snapshot=snapshot,
            )
            node_diagnostics.extend(traversal_diagnostics)

        readiness_nodes.append(
            ContinuityPlanNodeReadiness(
                node_id=row.id,
                node_type=node_type,
                ref_id=ref_id,
                lane_id=row.lane_id,
                position=row.position,
                label=_node_label(node_type, ref_id, snapshot),
                is_readable=is_readable,
                is_complete=is_complete,
                evaluated_issue_id=evaluated_issue_id,
                blockers=blockers,
                diagnostics=node_diagnostics,
                chains=chains,
                readable_prerequisites=readable_prerequisites,
            )
        )

    for node_type, node_id in sorted(cycle_nodes):
        if not any(
            diagnostic.code == "plan_cycle_detected"
            and diagnostic.node_type == node_type
            and diagnostic.node_id == node_id
            for diagnostic in plan_diagnostics
        ):
            plan_diagnostics.append(
                ContinuityPlanReadinessDiagnostic(
                    code="plan_cycle_detected",
                    node_type=node_type,
                    node_id=node_id,
                )
            )

    summary = ContinuityPlanReadinessSummary(total=len(readiness_nodes))
    for node in readiness_nodes:
        if node.diagnostics and any(
            diagnostic.code in {"dangling_plan_reference", "plan_cycle_detected"}
            for diagnostic in node.diagnostics
        ):
            summary.unavailable += 1
        elif node.is_complete:
            summary.complete += 1
        elif not node.is_readable:
            summary.blocked += 1
        else:
            summary.readable += 1

    return ContinuityPlanReadinessResponse(
        plan_id=plan.id,
        plan_name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=lanes,
        nodes=readiness_nodes,
        plan_diagnostics=plan_diagnostics,
        summary=summary,
        generated_at=datetime.now(UTC),
    )
