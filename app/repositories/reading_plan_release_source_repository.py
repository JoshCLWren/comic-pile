"""Repository access for release sources used by the sync run.

Query construction lives here; the sync service owns orchestration and
transaction boundaries.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.reading_plan_release_source import ReadingPlanReleaseSource


def _base_statement() -> Select[ReadingPlanReleaseSource]:
    """Return the shared select statement with every relationship eagerly loaded.

    ``ReadingPlanReleaseSource.reading_plan``, ``.thread``, and
    ``.external_identity`` use ``lazy="raise"``, so the sync service cannot
    lazy-load them outside the owning session's identity map. Every loader in
    this module must therefore eagerly load them.

    Returns:
        A select statement over release sources joined to their plan.
    """
    return (
        select(ReadingPlanReleaseSource)
        .join(ContinuityPlan, ReadingPlanReleaseSource.plan_id == ContinuityPlan.id)
        .options(
            joinedload(ReadingPlanReleaseSource.reading_plan),
            joinedload(ReadingPlanReleaseSource.thread),
            joinedload(ReadingPlanReleaseSource.external_identity),
        )
    )


async def create(
    db: AsyncSession, *, source: ReadingPlanReleaseSource
) -> ReadingPlanReleaseSource:
    """Persist a new release source.

    Args:
        db: Database session.
        source: Unsaved release source.

    Returns:
        The flushed source.
    """
    db.add(source)
    await db.flush()
    return source


async def delete_by_id(db: AsyncSession, *, source_id: int) -> None:
    """Delete one release source by id.

    Args:
        db: Database session.
        source_id: Release source to remove.
    """
    await db.execute(
        delete(ReadingPlanReleaseSource).where(
            ReadingPlanReleaseSource.id == source_id
        )
    )
    await db.flush()


async def get_by_id(
    db: AsyncSession, *, source_id: int, user_id: int
) -> ReadingPlanReleaseSource | None:
    """Fetch one release source by id, scoped to the user's plans."""
    stmt = (
        _base_statement()
        .where(
            ReadingPlanReleaseSource.id == source_id,
            ContinuityPlan.user_id == user_id,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_for_plan(
    db: AsyncSession, *, plan_id: int, user_id: int
) -> list[ReadingPlanReleaseSource]:
    """List all release sources for one plan, scoped to the owner."""
    stmt = (
        _base_statement()
        .where(
            ReadingPlanReleaseSource.plan_id == plan_id,
            ContinuityPlan.user_id == user_id,
        )
        .order_by(ReadingPlanReleaseSource.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_for_user(db: AsyncSession, *, user_id: int) -> list[ReadingPlanReleaseSource]:
    """List every release source owned by one user, enabled or disabled.

    Args:
        db: Database session.
        user_id: Owner of the reading plans.

    Returns:
        All release sources for the user, ordered by creation.
    """
    stmt = _base_statement().where(ContinuityPlan.user_id == user_id).order_by(
        ReadingPlanReleaseSource.created_at
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_enabled_for_user(
    db: AsyncSession, *, user_id: int
) -> list[ReadingPlanReleaseSource]:
    """List the user's enabled release sources with eager relationships.

    Args:
        db: Database session.
        user_id: Owner of the reading plans.

    Returns:
        Enabled release sources for the user, ordered by creation.
    """
    stmt = (
        _base_statement()
        .where(
            ReadingPlanReleaseSource.enabled.is_(True),
            ContinuityPlan.user_id == user_id,
        )
        .order_by(ReadingPlanReleaseSource.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def has_confirmed_thread_volume(
    db: AsyncSession, *, thread_id: int, external_identity_id: int
) -> bool:
    """Report whether a volume identity is still a confirmed mapping for a thread.

    The mapping may have been demoted after the release source was created, so
    the sync service revalidates it instead of trusting the stored row.

    Args:
        db: Database session.
        thread_id: Thread the volume feeds.
        external_identity_id: Confirmed volume identity.

    Returns:
        True when a confirmed mapping row exists.
    """
    confirmed_id = await db.scalar(
        select(ThreadExternalSeriesMapping.id)
        .where(
            ThreadExternalSeriesMapping.thread_id == thread_id,
            ThreadExternalSeriesMapping.external_identity_id == external_identity_id,
            ThreadExternalSeriesMapping.status == "confirmed",
        )
        .limit(1)
    )
    if confirmed_id is None:
        return False
    identity = await db.scalar(
        select(ExternalIdentity.id)
        .where(
            ExternalIdentity.id == external_identity_id,
            ExternalIdentity.provider == "comicvine",
            ExternalIdentity.entity_type == "series",
        )
        .limit(1)
    )
    return identity is not None


async def mark_synced(db: AsyncSession, *, source_id: int, synced_at: datetime) -> None:
    """Record that a source's roster was evaluated successfully.

    Callers must only invoke this for sources whose provider roster was
    actually retrieved and evaluated, so a failed source never appears current.

    Args:
        db: Database session.
        source_id: Release source that was evaluated.
        synced_at: Timestamp to persist.
    """
    await db.execute(
        update(ReadingPlanReleaseSource)
        .where(ReadingPlanReleaseSource.id == source_id)
        .values(last_synced_at=synced_at)
    )
