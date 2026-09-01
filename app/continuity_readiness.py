"""Bounded direct readiness evaluation for generalized continuity rules."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.continuity_readiness import (
    ContinuityReadinessNodeType,
    ContinuityReadinessResponse,
)
from app.services.continuity_graph import (
    MAX_GRAPH_GROUPS,
    MAX_GRAPH_ISSUES,
    MAX_GRAPH_MEMBERSHIPS,
    MAX_GRAPH_RULES,
    MAX_GRAPH_SELECTED_MEMBERS,
    MAX_GRAPH_THREADS,
    SNAPSHOT_SESSION_KEY,
    GraphSnapshot,
    crossover_readiness,
    group_issue_ids,
    is_read,
    issue_readiness,
    load_snapshot,
)

# Backwards-compatible private aliases for legacy imports.
_GraphSnapshot = GraphSnapshot
_load_snapshot = load_snapshot
_group_issue_ids = group_issue_ids
_is_read = is_read
_issue_readiness = issue_readiness
_crossover_readiness = crossover_readiness


async def evaluate_continuity_readiness(
    db: AsyncSession,
    *,
    user_id: int,
    node_type: ContinuityReadinessNodeType,
    node_id: int,
    expose_result: bool = False,
) -> ContinuityReadinessResponse | None:
    """Evaluate legacy direct readiness only for an explicit API compatibility caller.

    Standalone readiness is no longer part of normal product rendering. Internal
    callers such as crossover detail therefore receive ``None`` without loading
    the account-wide continuity snapshot. The temporary public compatibility
    endpoint opts in with ``expose_result=True`` until dead API cleanup lands.
    """
    if not expose_result:
        return None

    snapshot = await load_snapshot(db, user_id)
    evaluated_issue_id: int | None = None

    if node_type == "issue":
        issue = snapshot.issues.get(node_id)
        if issue is None:
            raise HTTPException(status_code=404, detail=f"Issue {node_id} not found")
        blockers = issue_readiness(node_id, snapshot)
    elif node_type == "thread":
        thread = snapshot.threads.get(node_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Thread {node_id} not found")
        evaluated_issue_id = thread.next_unread_issue_id
        blockers = (
            issue_readiness(evaluated_issue_id, snapshot)
            if evaluated_issue_id is not None
            else []
        )
    else:
        if node_id not in snapshot.groups:
            raise HTTPException(status_code=404, detail=f"Crossover {node_id} not found")
        blockers = crossover_readiness(node_id, snapshot)

    return ContinuityReadinessResponse(
        node_type=node_type,
        node_id=node_id,
        is_readable=not blockers,
        evaluated_issue_id=evaluated_issue_id,
        blockers=blockers,
    )


__all__ = [
    "MAX_GRAPH_GROUPS",
    "MAX_GRAPH_ISSUES",
    "MAX_GRAPH_MEMBERSHIPS",
    "MAX_GRAPH_RULES",
    "MAX_GRAPH_SELECTED_MEMBERS",
    "MAX_GRAPH_THREADS",
    "SNAPSHOT_SESSION_KEY",
    "evaluate_continuity_readiness",
]
