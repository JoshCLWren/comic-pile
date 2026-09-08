"""Shared continuity graph cycle detection for mutation services."""

from __future__ import annotations

from sqlalchemy import Select, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.schemas.continuity_rule import ContinuityNodeType


async def would_create_continuity_cycle(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: ContinuityNodeType,
    source_id: int,
    target_type: ContinuityNodeType,
    target_id: int,
    exclude_rule_id: int | None = None,
) -> bool:
    """Return whether adding source to target would close a path back to source."""
    if source_type == target_type and source_id == target_id:
        return True

    def owned_conditions(row) -> list:
        conditions = [row.c.user_id == user_id]
        if exclude_rule_id is not None:
            conditions.append(row.c.id != exclude_rule_id)
        return conditions

    def targets_of(rules, seed) -> Select:
        return select(
            rules.c.target_type.label("node_type"),
            rules.c.target_id.label("node_id"),
        ).join(
            seed,
            or_(
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
            ),
        )

    edge = ContinuityRule.__table__.alias("continuity_edge")
    target_seed = select(
        literal(target_type).label("node_type"),
        literal(target_id).label("node_id"),
    ).cte("target_seed_node", recursive=False)
    initial_targets = targets_of(edge, target_seed).where(*owned_conditions(edge))

    reachable = initial_targets.cte("reachable_continuity_nodes", recursive=True)
    recursive_edge = ContinuityRule.__table__.alias("recursive_continuity_edge")
    reachable = reachable.union(
        targets_of(recursive_edge, reachable).where(*owned_conditions(recursive_edge))
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
