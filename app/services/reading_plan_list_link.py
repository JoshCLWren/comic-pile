"""Create a durable, owner-scoped Reading List for newly authored legacy Plans.

Option E reads list membership only. This adapter is solely for the older
Plan-creation route; it is not a second ongoing order synchronization system.
Once linked, users edit the List and the Plan's old nodes are historical.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.repositories import reading_plan_list_link_repository as link_repository


async def link_new_plan_to_owned_list(
    db: AsyncSession, *, plan: ContinuityPlan, user_id: int,
    adopted_order_id: int | None = None,
) -> int:
    """Create a canonical List and source in the same Plan-creation transaction."""
    existing = await link_repository.linked_list_ids(db, plan_id=plan.id)
    if existing:
        if len(existing) != 1:
            raise HTTPException(status_code=409, detail="Ambiguous Plan Reading List")
        return next(iter(existing))
    occurrences = await link_repository.plan_member_rows(db, plan_id=plan.id)
    if len({row.lane_id for row in occurrences}) > 1:
        raise HTTPException(
            status_code=409,
            detail="Create an owned Reading List before adopting a multi-lane Plan",
        )
    adopted_issue_ids = None
    if adopted_order_id is not None and not occurrences:
        adopted_issue_ids = await link_repository.adopted_order_issue_ids(
            db, user_id=user_id, reading_order_id=adopted_order_id,
        )
        if not adopted_issue_ids:
            raise HTTPException(
                status_code=422,
                detail="Reading Order has no physical issues to adopt",
            )
    return await link_repository.create_owned_plan_list(
        db, plan=plan, user_id=user_id, rows=occurrences,
        adopted_issue_ids=adopted_issue_ids,
    )
