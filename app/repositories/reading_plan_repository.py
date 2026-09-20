"""Reading Plan normalized persistence repository.

All SQLAlchemy access for the Reading Plan relational model family lives here.
Functions return ORM models or row counts; callers (services) own transactions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_plan import (
    ReadingPlanDependency,
    ReadingPlanIssue,
    ReadingPlanLane,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)

if TYPE_CHECKING:
    from app.models.continuity_plan import ContinuityPlan


async def get_plan_with_relations(
    db: AsyncSession, user_id: int, plan_id: int
) -> ContinuityPlan | None:
    """Load a plan with all normalized relations for response serialization.

    Args:
        db: Database session.
        user_id: Owner of the plan.
        plan_id: Plan primary key.

    Returns:
        The plan with lanes, issues, dependencies, sources, and placements loaded,
        or None if not found or not owned by user.
    """
    from sqlalchemy.orm import selectinload

    from app.models.continuity_plan import ContinuityPlan

    result = await db.execute(
        select(ContinuityPlan)
        .where(ContinuityPlan.id == plan_id, ContinuityPlan.user_id == user_id)
        .options(
            selectinload(ContinuityPlan.lanes),
            selectinload(ContinuityPlan.issues).selectinload(ReadingPlanIssue.source_placements),
            selectinload(ContinuityPlan.dependencies).selectinload(ReadingPlanDependency.dependency),
            selectinload(ContinuityPlan.sources).selectinload(ReadingPlanSource.placements),
        )
    )
    return result.unique().scalar_one_or_none()


async def get_plan_lanes(db: AsyncSession, plan_id: int) -> Sequence[ReadingPlanLane]:
    """Get all lanes for a plan, ordered by display_order."""
    result = await db.execute(
        select(ReadingPlanLane)
        .where(ReadingPlanLane.plan_id == plan_id)
        .order_by(ReadingPlanLane.display_order)
    )
    return result.scalars().all()


async def get_plan_issues(db: AsyncSession, plan_id: int) -> Sequence[ReadingPlanIssue]:
    """Get all issue occurrences for a plan, ordered by lane and position."""
    result = await db.execute(
        select(ReadingPlanIssue)
        .where(ReadingPlanIssue.plan_id == plan_id)
        .order_by(ReadingPlanIssue.lane_id, ReadingPlanIssue.display_position)
    )
    return result.scalars().all()


async def get_plan_issues_by_issue(db: AsyncSession, plan_id: int, issue_id: int) -> Sequence[ReadingPlanIssue]:
    """Get all occurrences of a specific issue in a plan."""
    result = await db.execute(
        select(ReadingPlanIssue)
        .where(ReadingPlanIssue.plan_id == plan_id, ReadingPlanIssue.issue_id == issue_id)
        .order_by(ReadingPlanIssue.lane_id, ReadingPlanIssue.display_position)
    )
    return result.scalars().all()


async def get_plan_dependencies(db: AsyncSession, plan_id: int) -> Sequence[ReadingPlanDependency]:
    """Get all dependency references for a plan."""
    result = await db.execute(
        select(ReadingPlanDependency)
        .where(ReadingPlanDependency.plan_id == plan_id)
        .order_by(ReadingPlanDependency.dependency_id)
    )
    return result.scalars().all()


async def get_plan_sources(db: AsyncSession, plan_id: int) -> Sequence[ReadingPlanSource]:
    """Get all source snapshots for a plan."""
    result = await db.execute(
        select(ReadingPlanSource)
        .where(ReadingPlanSource.plan_id == plan_id)
        .order_by(ReadingPlanSource.recorded_at)
    )
    return result.scalars().all()


async def get_plan_source_placements(db: AsyncSession, plan_id: int) -> Sequence[ReadingPlanSourcePlacement]:
    """Get all source placements for a plan."""
    result = await db.execute(
        select(ReadingPlanSourcePlacement)
        .where(ReadingPlanSourcePlacement.plan_id == plan_id)
        .order_by(ReadingPlanSourcePlacement.occurrence_id, ReadingPlanSourcePlacement.source_id)
    )
    return result.scalars().all()


async def get_dependency_plan_links(db: AsyncSession, dependency_id: int) -> Sequence[ReadingPlanDependency]:
    """Get all plans referencing a specific dependency."""
    result = await db.execute(
        select(ReadingPlanDependency).where(ReadingPlanDependency.dependency_id == dependency_id)
    )
    return result.scalars().all()


async def get_issue_plan_occurrences(db: AsyncSession, user_id: int, issue_id: int) -> Sequence[ReadingPlanIssue]:
    """Get all plan occurrences of a specific issue across all user's plans.

    Used to verify global read state reflection across overlapping plans.
    """
    from app.models.continuity_plan import ContinuityPlan

    result = await db.execute(
        select(ReadingPlanIssue)
        .join(ContinuityPlan, ReadingPlanIssue.plan_id == ContinuityPlan.id)
        .where(ContinuityPlan.user_id == user_id, ReadingPlanIssue.issue_id == issue_id)
        .order_by(ReadingPlanIssue.plan_id, ReadingPlanIssue.lane_id, ReadingPlanIssue.display_position)
    )
    return result.scalars().all()


async def delete_plan_lanes(db: AsyncSession, plan_id: int) -> None:
    """Delete all lanes for a plan (cascades to issues and placements)."""
    await db.execute(delete(ReadingPlanLane).where(ReadingPlanLane.plan_id == plan_id))


async def delete_plan_issues(db: AsyncSession, plan_id: int) -> None:
    """Delete all issue occurrences for a plan (cascades to placements)."""
    await db.execute(delete(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan_id))


async def delete_plan_dependencies(db: AsyncSession, plan_id: int) -> None:
    """Delete all dependency references for a plan."""
    await db.execute(delete(ReadingPlanDependency).where(ReadingPlanDependency.plan_id == plan_id))


async def delete_plan_sources(db: AsyncSession, plan_id: int) -> None:
    """Delete all source snapshots for a plan (cascades to placements)."""
    await db.execute(delete(ReadingPlanSource).where(ReadingPlanSource.plan_id == plan_id))


async def delete_plan_source_placements(db: AsyncSession, plan_id: int) -> None:
    """Delete all source placements for a plan."""
    await db.execute(delete(ReadingPlanSourcePlacement).where(ReadingPlanSourcePlacement.plan_id == plan_id))


async def upsert_plan_lanes(
    db: AsyncSession, plan_id: int, lanes: list[ReadingPlanLane]
) -> list[ReadingPlanLane]:
    """Replace all lanes for a plan with the provided list."""
    await delete_plan_lanes(db, plan_id)
    for lane in lanes:
        lane.plan_id = plan_id
        db.add(lane)
    await db.flush()
    return lanes


async def upsert_plan_issues(
    db: AsyncSession, plan_id: int, issues: list[ReadingPlanIssue]
) -> list[ReadingPlanIssue]:
    """Replace all issue occurrences for a plan with the provided list."""
    await delete_plan_issues(db, plan_id)
    for issue in issues:
        issue.plan_id = plan_id
        db.add(issue)
    await db.flush()
    return issues


async def upsert_plan_dependencies(
    db: AsyncSession, plan_id: int, dependencies: list[ReadingPlanDependency]
) -> list[ReadingPlanDependency]:
    """Replace all dependency references for a plan with the provided list."""
    await delete_plan_dependencies(db, plan_id)
    for dep in dependencies:
        dep.plan_id = plan_id
        db.add(dep)
    await db.flush()
    return dependencies


async def upsert_plan_sources(
    db: AsyncSession, plan_id: int, sources: list[ReadingPlanSource]
) -> list[ReadingPlanSource]:
    """Replace all source snapshots for a plan with the provided list."""
    await delete_plan_sources(db, plan_id)
    for source in sources:
        source.plan_id = plan_id
        db.add(source)
    await db.flush()
    return sources


async def upsert_plan_source_placements(
    db: AsyncSession, plan_id: int, placements: list[ReadingPlanSourcePlacement]
) -> list[ReadingPlanSourcePlacement]:
    """Replace all source placements for a plan with the provided list."""
    await delete_plan_source_placements(db, plan_id)
    for placement in placements:
        placement.plan_id = plan_id
        db.add(placement)
    await db.flush()
    return placements


async def link_dependency_to_plan(
    db: AsyncSession, plan_id: int, dependency_id: int, explanation: str | None = None
) -> ReadingPlanDependency:
    """Link a dependency to a plan (idempotent - does nothing if link exists)."""
    existing = await db.execute(
        select(ReadingPlanDependency).where(
            ReadingPlanDependency.plan_id == plan_id,
            ReadingPlanDependency.dependency_id == dependency_id,
        )
    )
    existing_link = existing.scalar_one_or_none()
    if existing_link is not None:
        return existing_link

    link = ReadingPlanDependency(plan_id=plan_id, dependency_id=dependency_id, explanation=explanation)
    db.add(link)
    await db.flush()
    return link


async def unlink_dependency_from_plan(db: AsyncSession, plan_id: int, dependency_id: int) -> bool:
    """Remove a dependency link from a plan. Returns True if a link was removed."""
    result = await db.execute(
        delete(ReadingPlanDependency).where(
            ReadingPlanDependency.plan_id == plan_id,
            ReadingPlanDependency.dependency_id == dependency_id,
        )
    )
    rowcount = getattr(result, "rowcount", None)
    return isinstance(rowcount, int) and rowcount > 0