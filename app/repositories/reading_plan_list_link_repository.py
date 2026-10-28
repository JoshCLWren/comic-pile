"""Owner-scoped persistence used when legacy Plan creation adopts Option E."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource
from app.models.reading_order import ReadingOrderItem
from app.models.issue import Issue
from app.models.thread import Thread


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


async def adopted_order_issue_ids(
    db: AsyncSession, *, user_id: int, reading_order_id: int,
) -> list[int]:
    """Expand owned ordered Threads into their complete physical Issue order."""
    rows = await db.scalars(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(ReadingOrderItem, ReadingOrderItem.thread_id == Thread.id)
        .where(ReadingOrderItem.reading_order_id == reading_order_id, Thread.user_id == user_id)
        .order_by(ReadingOrderItem.position, ReadingOrderItem.id, Issue.position, Issue.id)
    )
    return list(rows.all())


async def create_owned_plan_list(
    db: AsyncSession, *, plan: ContinuityPlan, user_id: int,
    rows: list[ReadingPlanIssue],
    adopted_issue_ids: list[int] | None = None,
) -> int:
    """Write List, issue entries and source atomically in the caller transaction."""
    reading_list = CustomCBLList(
        user_id=user_id,
        name=plan.name,
        mode="strict" if plan.ordering_mode == "strict_sequential" else "loose",
    )
    db.add(reading_list)
    await db.flush()
    membership = (
        [(issue_id, False) for issue_id in adopted_issue_ids]
        if adopted_issue_ids is not None
        else [(row.issue_id, row.is_checkpoint) for row in rows]
    )
    db.add_all([
        CustomCBLEntry(
            list_id=reading_list.id,
            issue_id=issue_id,
            position=index,
            gate="none",
            skipped=False,
            is_checkpoint=checkpoint,
        )
        for index, (issue_id, checkpoint) in enumerate(membership)
    ])
    db.add(ReadingPlanSource(
        plan_id=plan.id,
        raw_source_path=f"custom-cbl:{reading_list.id}",
        custom_cbl_list_id=reading_list.id,
    ))
    await db.flush()
    return reading_list.id
