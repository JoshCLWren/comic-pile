"""Owner-scoped persistence used when legacy Plan creation adopts Option E."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource


async def linked_list_ids(db: AsyncSession, *, plan_id: int) -> set[int]:
    """Read only explicit, stored Plan-to-List source references."""
    sources = (await db.scalars(
        select(ReadingPlanSource).where(ReadingPlanSource.plan_id == plan_id)
    )).all()
    return {source.custom_cbl_list_id for source in sources
            if source.custom_cbl_list_id is not None}


async def plan_member_rows(
    db: AsyncSession, *, plan_id: int,
) -> list[ReadingPlanIssue]:
    """Read legacy Plan membership once, before the new List becomes authority."""
    return list((await db.scalars(
        select(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan_id)
        .order_by(ReadingPlanIssue.display_position, ReadingPlanIssue.occurrence_id)
    )).all())


async def create_owned_plan_list(
    db: AsyncSession, *, plan: ContinuityPlan, user_id: int,
    rows: list[ReadingPlanIssue],
) -> int:
    """Write List, issue entries and source atomically in the caller transaction."""
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
        for index, row in enumerate(rows)
    ])
    db.add(ReadingPlanSource(
        plan_id=plan.id,
        raw_source_path=f"custom-cbl:{reading_list.id}",
        custom_cbl_list_id=reading_list.id,
    ))
    await db.flush()
    return reading_list.id
