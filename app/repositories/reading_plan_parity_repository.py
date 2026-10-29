"""Owner-scoped persistence for the Plan/List parity repair (#4254).

Reading Plan membership and the owned List it must match live in separate
tables. This repository reads one consistent, owner-scoped snapshot of both
sides plus the provenance rows the repair must preserve, and owns the small,
auditable membership mutations the repair is allowed to make. It never writes
``custom_cbl_lists`` or ``custom_cbl_entries``: the owner's List is the
authority and must remain untouched.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)


async def load_plan_parity_rows(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
) -> tuple[ContinuityPlan | None, list[ReadingPlanSource], list[ReadingPlanIssue]]:
    """Load one Plan row with its sources and membership in display order.

    Args:
        db: Database session.
        user_id: Authenticated owner whose plan must be read.
        plan_id: Plan to load.

    Returns:
        ``(plan, sources, memberships)`` where ``memberships`` are ordered by
        ``(lane_id, display_position, occurrence_id)``. ``plan`` is ``None``
        when the plan does not exist or is not owned.
    """
    plan = (
        await db.scalars(
            select(ContinuityPlan).where(
                ContinuityPlan.id == plan_id,
                ContinuityPlan.user_id == user_id,
            )
        )
    ).first()
    if plan is None:
        return None, [], []
    sources = list(
        (
            await db.scalars(
                select(ReadingPlanSource)
                .where(ReadingPlanSource.plan_id == plan_id)
                .order_by(ReadingPlanSource.id)
            )
        ).all()
    )
    memberships = list(
        (
            await db.scalars(
                select(ReadingPlanIssue)
                .where(ReadingPlanIssue.plan_id == plan_id)
                .order_by(
                    ReadingPlanIssue.lane_id,
                    ReadingPlanIssue.display_position,
                    ReadingPlanIssue.occurrence_id,
                )
            )
        ).all()
    )
    return plan, sources, memberships


async def load_entries_for_lists(
    db: AsyncSession,
    *,
    user_id: int,
    list_ids: list[int],
) -> dict[int, list[CustomCBLEntry]]:
    """Load List entries for owner-scoped Lists, grouped per List in position order.

    Args:
        db: Database session.
        user_id: Owner the Lists must belong to.
        list_ids: Lists to expand; unowned IDs are silently ignored.

    Returns:
        Mapping of owned List ID to its entries in ``(position, id)`` order.
    """
    if not list_ids:
        return {}
    rows = (
        await db.scalars(
            select(CustomCBLEntry)
            .join(CustomCBLList, CustomCBLEntry.list_id == CustomCBLList.id)
            .where(
                CustomCBLEntry.list_id.in_(list_ids),
                CustomCBLList.user_id == user_id,
            )
            .order_by(CustomCBLEntry.list_id, CustomCBLEntry.position, CustomCBLEntry.id)
        )
    ).all()
    entries: dict[int, list[CustomCBLEntry]] = {}
    for row in rows:
        entries.setdefault(row.list_id, []).append(row)
    return entries


async def load_lists(db: AsyncSession, *, user_id: int, list_ids: list[int]) -> dict[int, CustomCBLList]:
    """Resolve candidate List IDs to owner-owned rows.

    Args:
        db: Database session.
        user_id: Owner the Lists must belong to.
        list_ids: Candidate IDs; unowned or unknown IDs are ignored.

    Returns:
        Mapping of owned List ID to its ``CustomCBLList`` row.
    """
    if not list_ids:
        return {}
    rows = (
        await db.scalars(
            select(CustomCBLList).where(
                CustomCBLList.id.in_(list_ids),
                CustomCBLList.user_id == user_id,
            )
        )
    ).all()
    return {row.id: row for row in rows}


async def load_issue_statuses(
    db: AsyncSession, *, issue_ids: list[int]
) -> dict[int, str]:
    """Load the read/unread status for the involved Issues only.

    Args:
        db: Database session.
        issue_ids: Issue IDs whose status is needed.

    Returns:
        Mapping of Issue ID to its stored ``status`` value.
    """
    if not issue_ids:
        return {}
    rows = (await db.execute(select(Issue.id, Issue.status).where(Issue.id.in_(issue_ids)))).all()
    return dict(rows)


async def load_plan_source_rows(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanSource]:
    """Load every source snapshot of one plan, oldest first.

    Args:
        db: Database session.
        plan_id: Plan whose source snapshots are loaded.

    Returns:
        Source snapshots in primary-key order.
    """
    return list(
        (
            await db.scalars(
                select(ReadingPlanSource)
                .where(ReadingPlanSource.plan_id == plan_id)
                .order_by(ReadingPlanSource.id)
            )
        ).all()
    )


async def load_plan_issue_rows(
    db: AsyncSession, *, plan_id: int
) -> list[ReadingPlanIssue]:
    """Load every membership occurrence of one plan in display order.

    Args:
        db: Database session.
        plan_id: Plan whose occurrences are loaded.

    Returns:
        Membership rows ordered by ``(lane_id, display_position,
        occurrence_id)``.
    """
    return list(
        (
            await db.scalars(
                select(ReadingPlanIssue)
                .where(ReadingPlanIssue.plan_id == plan_id)
                .order_by(
                    ReadingPlanIssue.lane_id,
                    ReadingPlanIssue.display_position,
                    ReadingPlanIssue.occurrence_id,
                )
            )
        ).all()
    )


async def insert_plan_source(db: AsyncSession, source: ReadingPlanSource) -> ReadingPlanSource:
    """Persist one immutable Plan-source snapshot and return it with its ID.

    Args:
        db: Database session.
        source: Source snapshot to insert; existing rows are never modified.

    Returns:
        The same row, refreshed with its database-assigned primary key.
    """
    db.add(source)
    await db.flush()
    return source


async def add_plan_issue_occurrences(
    db: AsyncSession, *, plan_id: int, rows: list[ReadingPlanIssue]
) -> None:
    """Append membership occurrences for one plan.

    Args:
        db: Database session.
        plan_id: Plan the occurrences belong to.
        rows: Prepared occurrence rows; every row must target ``plan_id``.
    """
    for row in rows:
        row.plan_id = plan_id
    db.add_all(rows)
    await db.flush()


async def renumber_plan_issue_positions(
    db: AsyncSession,
    *,
    plan_id: int,
    updates: list[tuple[str, int]],
) -> None:
    """Move ``(occurrence_id, display_position)`` pairs into their final slots.

    Only occurrence IDs already present on the plan are updated; the two-pass
    sentinel keeps ``uq_reading_plan_issue_lane_position`` satisfied while
    positions swap.

    Args:
        db: Database session.
        plan_id: Plan whose occurrences are renumbered.
        updates: ``(occurrence_id, final_display_position)`` pairs.
    """
    if not updates:
        return
    sentinel = [
        (occurrence_id, -1000000 + index)
        for index, (occurrence_id, _) in enumerate(updates)
    ]
    for step_index, pairs in enumerate((sentinel, updates)):
        if step_index == 1:
            await db.flush()
        for occurrence_id, position in pairs:
            await db.execute(
                update(ReadingPlanIssue)
                .where(
                    ReadingPlanIssue.plan_id == plan_id,
                    ReadingPlanIssue.occurrence_id == occurrence_id,
                )
                .values(display_position=position)
            )
    await db.flush()


async def insert_plan_source_placements(
    db: AsyncSession, *, plan_id: int, rows: list[ReadingPlanSourcePlacement]
) -> None:
    """Append source-position observations for one plan.

    Args:
        db: Database session.
        plan_id: Plan the placements belong to.
        rows: Placement rows; each must reference a source snapshot of the
            same plan.
    """
    for row in rows:
        row.plan_id = plan_id
    db.add_all(rows)
    await db.flush()
