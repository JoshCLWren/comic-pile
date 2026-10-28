"""Owner-scoped persistence used when legacy Plan creation adopts Option E."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource
from app.models.reading_order import ReadingOrderItem
from app.models.issue import Issue
from app.models.thread import Thread



async def owned_plan_list_authority_rows(
    db: AsyncSession, *, user_id: int, plan_ids: list[int],
) -> list[tuple[int, int, str, datetime]]:
    """Bulk-load the authoritative Lists for Plans, scoped to the same owner.

    Keep SQL construction in repositories; the service validates exact-one
    authority and decides whether missing or ambiguous links are fatal.
    """
    if not plan_ids:
        return []
    rows = (await db.execute(
        select(
            ReadingPlanSource.plan_id,
            CustomCBLList.id,
            CustomCBLList.mode,
            CustomCBLList.updated_at,
        )
        .join(CustomCBLList, ReadingPlanSource.custom_cbl_list_id == CustomCBLList.id)
        .where(
            ReadingPlanSource.plan_id.in_(plan_ids),
            CustomCBLList.user_id == user_id,
        )
    )).all()
    return [(plan_id, list_id, mode, updated_at)
            for plan_id, list_id, mode, updated_at in rows]


async def owned_list_entry_counts(
    db: AsyncSession, *, user_id: int, list_ids: list[int],
) -> dict[int, int]:
    """Bulk-count physical entries, excluding any unowned List IDs."""
    if not list_ids:
        return {}
    rows = (await db.execute(
        select(CustomCBLEntry.list_id, func.count())
        .join(CustomCBLList, CustomCBLEntry.list_id == CustomCBLList.id)
        .where(CustomCBLEntry.list_id.in_(list_ids), CustomCBLList.user_id == user_id)
        .group_by(CustomCBLEntry.list_id)
    )).all()
    return dict(rows)

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
