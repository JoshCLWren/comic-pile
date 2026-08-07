"""Ownership validation helpers for generalized continuity rules."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency_group import DependencyGroup
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_rule import ContinuityNodeType, ContinuityRuleCreate


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


async def ensure_owned_continuity_rule_references(
    db: AsyncSession,
    *,
    user_id: int,
    payload: ContinuityRuleCreate,
) -> None:
    """Validate ownership of every entity referenced by a continuity rule request.

    Args:
        db: The asynchronous database session.
        user_id: Authenticated user identifier.
        payload: Validated continuity-rule request.

    Raises:
        HTTPException: If any referenced node or issue is not owned by the user.
    """
    await ensure_owned_continuity_node(
        db,
        user_id=user_id,
        node_type=payload.source_type,
        node_id=payload.source_id,
    )
    await ensure_owned_continuity_node(
        db,
        user_id=user_id,
        node_type=payload.target_type,
        node_id=payload.target_id,
    )

    referenced_issue_ids = set(payload.selected_member_issue_ids)
    if payload.checkpoint_issue_id is not None:
        referenced_issue_ids.add(payload.checkpoint_issue_id)
    if not referenced_issue_ids:
        return

    result = await db.execute(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(referenced_issue_ids), Thread.user_id == user_id)
    )
    owned_issue_ids = set(result.scalars())
    missing_issue_ids = sorted(referenced_issue_ids - owned_issue_ids)
    if missing_issue_ids:
        raise HTTPException(status_code=404, detail=f"Issue {missing_issue_ids[0]} not found")
