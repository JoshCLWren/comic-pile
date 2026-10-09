"""Query construction and persistence for ReadingPlanReleaseSource.

All SQLAlchemy access for the release-source model lives here. Functions
return ORM models or plain values; callers (services) own transactions.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_plan_release_source import ReadingPlanReleaseSource


async def get_by_id(
    db: AsyncSession, *, source_id: int, user_id: int
) -> ReadingPlanReleaseSource | None:
    """Fetch one release source by id, scoped to the user's plans."""
    from app.models.continuity_plan import ContinuityPlan

    stmt = (
        select(ReadingPlanReleaseSource)
        .join(ContinuityPlan, ReadingPlanReleaseSource.plan_id == ContinuityPlan.id)
        .where(
            ReadingPlanReleaseSource.id == source_id,
            ContinuityPlan.user_id == user_id,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_for_plan(
    db: AsyncSession, *, plan_id: int, user_id: int
) -> list[ReadingPlanReleaseSource]:
    """List all release sources for one plan, scoped to the owner."""
    from app.models.continuity_plan import ContinuityPlan

    stmt = (
        select(ReadingPlanReleaseSource)
        .join(ContinuityPlan, ReadingPlanReleaseSource.plan_id == ContinuityPlan.id)
        .where(
            ReadingPlanReleaseSource.plan_id == plan_id,
            ContinuityPlan.user_id == user_id,
        )
        .order_by(ReadingPlanReleaseSource.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create(
    db: AsyncSession, *, source: ReadingPlanReleaseSource
) -> ReadingPlanReleaseSource:
    """Persist a new release source."""
    db.add(source)
    await db.flush()
    return source


async def delete_by_id(db: AsyncSession, *, source_id: int) -> None:
    """Delete one release source by id."""
    await db.execute(
        delete(ReadingPlanReleaseSource).where(ReadingPlanReleaseSource.id == source_id)
    )
    await db.flush()
