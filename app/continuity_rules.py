"""Ownership validation helpers for generalized continuity rules."""

from fastapi import HTTPException
from sqlalchemy import Select, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_rule import ContinuityNodeType


async def _would_create_cycle(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: ContinuityNodeType,
    source_id: int,
    target_type: ContinuityNodeType,
    target_id: int,
    exclude_rule_id: int | None = None,
) -> bool:
    """Return whether adding source→target would close a path back to source.

    Convergence targets add implicit edges: a converged rule's target waits for
    every convergence target, so each convergence target points into the rule's
    target beyond the stored source→target edge.

    Args:
        db: Asynchronous database session.
        user_id: Authenticated user whose owned graph is being validated.
        source_type: Continuity node kind of the new edge source.
        source_id: Continuity node identifier of the new edge source.
        target_type: Continuity node kind of the new edge target.
        target_id: Continuity node identifier of the new edge target.
        exclude_rule_id: Rule identifier to skip during graph traversal.

    Returns:
        True when the new edge would close a dependency cycle.
    """
    if source_type == target_type and source_id == target_id:
        return True

    def _owned_conditions(row) -> list:
        conditions = [row.c.user_id == user_id]
        if exclude_rule_id is not None:
            conditions.append(row.c.id != exclude_rule_id)
        return conditions

    def _targets_of(rules, seed) -> Select:
        return select(
            rules.c.target_type.label("node_type"),
            rules.c.target_id.label("node_id"),
        ).join(seed, or_(
            and_(
                rules.c.source_type == seed.c.node_type,
                rules.c.source_id == seed.c.node_id,
            ),
            func.cast(rules.c.convergence_targets, JSONB).contains(
                func.jsonb_build_array(
                    func.jsonb_build_object(
                        "type",
                        seed.c.node_type,
                        "id",
                        seed.c.node_id,
                    )
                )
            ),
        ))

    edge = ContinuityRule.__table__.alias("continuity_edge")
    target_seed = (
        select(
            literal(target_type).label("node_type"),
            literal(target_id).label("node_id"),
        ).cte("target_seed_node", recursive=False)
    )
    initial_targets = _targets_of(edge, target_seed).where(*_owned_conditions(edge))

    reachable = initial_targets.cte("reachable_continuity_nodes", recursive=True)
    recursive_edge = ContinuityRule.__table__.alias("recursive_continuity_edge")
    reachable = reachable.union(
        _targets_of(recursive_edge, reachable).where(*_owned_conditions(recursive_edge))
    )

    result = await db.execute(
        select(reachable.c.node_id)
        .where(
            reachable.c.node_type == source_type,
            reachable.c.node_id == source_id,
        )
        .limit(1)
    )
    return result.first() is not None


async def ensure_owned_continuity_node(
    db: AsyncSession,
    *,
    user_id: int,
    node_type: ContinuityNodeType,
    node_id: int,
) -> None:
    """Ensure a continuity node belongs to the authenticated user.

    Args:
        db: The asynchronous database session.
        user_id: Authenticated user identifier.
        node_type: Continuity node kind.
        node_id: Node identifier.

    Raises:
        HTTPException: If the node does not exist for the authenticated user.
    """
    if node_type == "crossover":
        statement = select(DependencyGroup.id).where(
            DependencyGroup.id == node_id,
            DependencyGroup.user_id == user_id,
        )
    else:
        statement = (
            select(Issue.id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Issue.id == node_id, Thread.user_id == user_id)
        )

    if (await db.execute(statement)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"{node_type.title()} {node_id} not found")
