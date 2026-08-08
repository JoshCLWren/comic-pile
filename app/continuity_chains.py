"""Bounded transitive traversal for continuity prerequisite chains."""

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_readiness import (
    _GraphSnapshot,
    _crossover_readiness,
    _issue_readiness,
    _load_snapshot,
)
from app.schemas.continuity_readiness import ContinuityBlocker, ContinuityReadinessNodeType

ContinuityTraversalNodeType = Literal["issue", "crossover"]
ContinuityTraversalDiagnosticCode = Literal[
    "cycle_detected",
    "depth_limit_exceeded",
    "node_limit_exceeded",
]

MAX_TRAVERSAL_DEPTH = 32
MAX_TRAVERSAL_NODES = 500


@dataclass(frozen=True)
class ContinuityTraversalNode:
    """One structured node in a prerequisite chain."""

    node_type: ContinuityTraversalNodeType
    node_id: int
    label: str
    is_readable: bool


@dataclass(frozen=True)
class ContinuityTraversalDiagnostic:
    """One structured traversal failure that does not require text parsing."""

    code: ContinuityTraversalDiagnosticCode
    node_type: ContinuityTraversalNodeType
    node_id: int
    limit: int | None = None


@dataclass(frozen=True)
class ContinuityTraversalResult:
    """Direct blockers plus every bounded path to currently readable prerequisites."""

    node_type: ContinuityReadinessNodeType
    node_id: int
    evaluated_issue_id: int | None
    direct_blockers: tuple[ContinuityBlocker, ...]
    chains: tuple[tuple[ContinuityTraversalNode, ...], ...]
    readable_prerequisites: tuple[ContinuityTraversalNode, ...]
    diagnostics: tuple[ContinuityTraversalDiagnostic, ...]


@dataclass
class _TraversalState:
    """Mutable counters and diagnostics shared by one traversal."""

    visited_nodes: int
    diagnostics: list[ContinuityTraversalDiagnostic]


def _node_label(
    node_type: ContinuityTraversalNodeType,
    node_id: int,
    snapshot: _GraphSnapshot,
) -> str:
    """Return a stable label for a traversable continuity node."""
    if node_type == "crossover":
        group = snapshot.groups.get(node_id)
        return group.name if group is not None else f"Crossover {node_id}"
    issue = snapshot.issues.get(node_id)
    if issue is None:
        return f"Issue {node_id}"
    thread = snapshot.threads.get(issue.thread_id)
    if thread is None:
        return f"Issue {issue.issue_number}"
    return f"{thread.title} #{issue.issue_number}"


def _node_blockers(
    node_type: ContinuityTraversalNodeType,
    node_id: int,
    snapshot: _GraphSnapshot,
) -> list[ContinuityBlocker]:
    """Return direct blockers for a traversable issue or crossover."""
    if node_type == "crossover":
        return _crossover_readiness(node_id, snapshot)
    return _issue_readiness(node_id, snapshot)


def _make_node(
    node_type: ContinuityTraversalNodeType,
    node_id: int,
    snapshot: _GraphSnapshot,
    *,
    is_readable: bool,
) -> ContinuityTraversalNode:
    """Build one immutable traversal node."""
    return ContinuityTraversalNode(
        node_type=node_type,
        node_id=node_id,
        label=_node_label(node_type, node_id, snapshot),
        is_readable=is_readable,
    )


def _append_diagnostic(
    state: _TraversalState,
    *,
    code: ContinuityTraversalDiagnosticCode,
    node_type: ContinuityTraversalNodeType,
    node_id: int,
    limit: int | None = None,
) -> None:
    """Record one diagnostic per code/node pair."""
    if any(
        diagnostic.code == code
        and diagnostic.node_type == node_type
        and diagnostic.node_id == node_id
        for diagnostic in state.diagnostics
    ):
        return
    state.diagnostics.append(
        ContinuityTraversalDiagnostic(
            code=code,
            node_type=node_type,
            node_id=node_id,
            limit=limit,
        )
    )


def _blocker_issue_ids(blocker: ContinuityBlocker) -> tuple[int, ...]:
    """Return concrete unread issue IDs responsible for one blocker."""
    return tuple(sorted(set(blocker.causing_issue_ids + blocker.causing_member_issue_ids)))


def _traverse_node(
    node_type: ContinuityTraversalNodeType,
    node_id: int,
    snapshot: _GraphSnapshot,
    state: _TraversalState,
    *,
    path: tuple[tuple[ContinuityTraversalNodeType, int], ...],
    depth: int,
) -> list[tuple[ContinuityTraversalNode, ...]]:
    """Return every bounded path from one prerequisite node to readable leaves."""
    key = (node_type, node_id)
    if key in path:
        _append_diagnostic(
            state,
            code="cycle_detected",
            node_type=node_type,
            node_id=node_id,
        )
        return []
    if depth > MAX_TRAVERSAL_DEPTH:
        _append_diagnostic(
            state,
            code="depth_limit_exceeded",
            node_type=node_type,
            node_id=node_id,
            limit=MAX_TRAVERSAL_DEPTH,
        )
        return []
    if state.visited_nodes >= MAX_TRAVERSAL_NODES:
        _append_diagnostic(
            state,
            code="node_limit_exceeded",
            node_type=node_type,
            node_id=node_id,
            limit=MAX_TRAVERSAL_NODES,
        )
        return []

    state.visited_nodes += 1
    blockers = _node_blockers(node_type, node_id, snapshot)
    current = _make_node(node_type, node_id, snapshot, is_readable=not blockers)
    if not blockers:
        return [(current,)]

    results: list[tuple[ContinuityTraversalNode, ...]] = []
    next_path = (*path, key)
    for blocker in blockers:
        concrete_issue_ids = _blocker_issue_ids(blocker)
        if blocker.source_type == "crossover" and concrete_issue_ids:
            crossover = _make_node(
                "crossover",
                blocker.source_id,
                snapshot,
                is_readable=False,
            )
            for issue_id in concrete_issue_ids:
                for child_path in _traverse_node(
                    "issue",
                    issue_id,
                    snapshot,
                    state,
                    path=(*next_path, ("crossover", blocker.source_id)),
                    depth=depth + 1,
                ):
                    results.append((current, crossover, *child_path))
            continue

        if blocker.source_type == "crossover":
            child_type: ContinuityTraversalNodeType = "crossover"
            child_ids = (blocker.source_id,)
        else:
            child_type = "issue"
            child_ids = concrete_issue_ids or (blocker.source_id,)

        for child_id in child_ids:
            for child_path in _traverse_node(
                child_type,
                child_id,
                snapshot,
                state,
                path=next_path,
                depth=depth + 1,
            ):
                results.append((current, *child_path))
    return results


def _root_paths(
    blockers: list[ContinuityBlocker],
    snapshot: _GraphSnapshot,
    state: _TraversalState,
) -> list[tuple[ContinuityTraversalNode, ...]]:
    """Resolve direct blockers into deterministic transitive prerequisite paths."""
    paths: list[tuple[ContinuityTraversalNode, ...]] = []
    for blocker in blockers:
        concrete_issue_ids = _blocker_issue_ids(blocker)
        if blocker.source_type == "crossover" and concrete_issue_ids:
            crossover = _make_node(
                "crossover",
                blocker.source_id,
                snapshot,
                is_readable=False,
            )
            for issue_id in concrete_issue_ids:
                for child_path in _traverse_node(
                    "issue",
                    issue_id,
                    snapshot,
                    state,
                    path=(("crossover", blocker.source_id),),
                    depth=1,
                ):
                    paths.append((crossover, *child_path))
            continue

        if blocker.source_type == "crossover":
            root_type: ContinuityTraversalNodeType = "crossover"
            root_ids = (blocker.source_id,)
        else:
            root_type = "issue"
            root_ids = concrete_issue_ids or (blocker.source_id,)
        for root_id in root_ids:
            paths.extend(
                _traverse_node(
                    root_type,
                    root_id,
                    snapshot,
                    state,
                    path=(),
                    depth=0,
                )
            )
    return paths


def _requested_blockers(
    node_type: ContinuityReadinessNodeType,
    node_id: int,
    snapshot: _GraphSnapshot,
) -> tuple[int | None, list[ContinuityBlocker]]:
    """Validate one requested node and return its evaluated issue plus direct blockers."""
    if node_type == "issue":
        if node_id not in snapshot.issues:
            raise HTTPException(status_code=404, detail=f"Issue {node_id} not found")
        return None, _issue_readiness(node_id, snapshot)
    if node_type == "thread":
        thread = snapshot.threads.get(node_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Thread {node_id} not found")
        evaluated_issue_id = thread.next_unread_issue_id
        blockers = (
            _issue_readiness(evaluated_issue_id, snapshot)
            if evaluated_issue_id is not None
            else []
        )
        return evaluated_issue_id, blockers
    if node_id not in snapshot.groups:
        raise HTTPException(status_code=404, detail=f"Crossover {node_id} not found")
    return None, _crossover_readiness(node_id, snapshot)


async def resolve_continuity_chains(
    db: AsyncSession,
    *,
    user_id: int,
    node_type: ContinuityReadinessNodeType,
    node_id: int,
) -> ContinuityTraversalResult:
    """Resolve every bounded prerequisite chain to currently readable leaves.

    Args:
        db: Database session used to load the authenticated user's graph.
        user_id: Authenticated owner whose continuity graph should be traversed.
        node_type: Requested issue, thread, or crossover type.
        node_id: Identifier of the requested owned node.

    Returns:
        Direct blockers, deterministic full chains, readable leaves, and diagnostics.
    """
    snapshot = await _load_snapshot(db, user_id)
    evaluated_issue_id, blockers = _requested_blockers(node_type, node_id, snapshot)
    state = _TraversalState(visited_nodes=0, diagnostics=[])
    paths = _root_paths(blockers, snapshot, state)
    paths.sort(
        key=lambda path: tuple((node.node_type, node.node_id) for node in path)
    )

    leaves: dict[tuple[ContinuityTraversalNodeType, int], ContinuityTraversalNode] = {}
    for path in paths:
        if path and path[-1].is_readable:
            leaf = path[-1]
            leaves[(leaf.node_type, leaf.node_id)] = leaf

    readable_prerequisites = tuple(
        leaves[key] for key in sorted(leaves, key=lambda item: (item[0], item[1]))
    )
    diagnostics = tuple(
        sorted(
            state.diagnostics,
            key=lambda item: (item.code, item.node_type, item.node_id),
        )
    )
    return ContinuityTraversalResult(
        node_type=node_type,
        node_id=node_id,
        evaluated_issue_id=evaluated_issue_id,
        direct_blockers=tuple(blockers),
        chains=tuple(paths),
        readable_prerequisites=readable_prerequisites,
        diagnostics=diagnostics,
    )
