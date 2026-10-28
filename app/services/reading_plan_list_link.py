"""Create a durable, owner-scoped Reading List for newly authored legacy Plans.

Option E reads list membership only. This adapter is solely for the older
Plan-creation route; it is not a second ongoing order synchronization system.
Once linked, users edit the List and the Plan's old nodes are historical.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource


async def link_new_plan_to_owned_list(
    db: AsyncSession, *, plan: ContinuityPlan, user_id: int,
) -> int:
    """Create a canonical List and source in the same Plan-creation transaction."""
    sources = (await db.scalars(
        select(ReadingPlanSource).where(ReadingPlanSource.plan_id == plan.id)
    )).all()
    existing = {source.custom_cbl_list_id for source in sources
                if source.custom_cbl_list_id is not None}
    if existing:
        if len(existing) != 1:
            raise HTTPException(status_code=409, detail="Ambiguous Plan Reading List")
        return next(iter(existing))
    occurrences = (await db.scalars(
        select(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan.id)
        .order_by(ReadingPlanIssue.display_position, ReadingPlanIssue.occurrence_id)
    )).all()
    if len({row.lane_id for row in occurrences}) > 1:
        raise HTTPException(
            status_code=409,
            detail="Create an owned Reading List before adopting a multi-lane Plan",
        )
    reading_list = CustomCBLList(
        user_id=user_id,
        name=plan.name,
        mode="strict" if plan.ordering_mode == "strict_sequential" else "loose",
    )
    db.add(reading_list)
    await db.flush()
    db.add_all([
        CustomCBLEntry(
            list_id=reading_list.id,
            issue_id=row.issue_id,
            position=index,
            gate="none",
            skipped=False,
            is_checkpoint=row.is_checkpoint,
        )
        for index, row in enumerate(occurrences)
    ])
    db.add(ReadingPlanSource(
        plan_id=plan.id,
        raw_source_path=f"custom-cbl:{reading_list.id}",
        custom_cbl_list_id=reading_list.id,
    ))
    await db.flush()
    return reading_list.id
