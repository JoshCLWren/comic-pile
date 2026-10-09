"""Business logic for Reading Plan release sources.

A release source records explicit user intent that a confirmed ComicVine
volume should feed newly released issues into a thread for a reading plan.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.repositories import reading_plan_release_source_repository as repo
from app.schemas.reading_plan_release_source import (
    ReleaseSourceCreate,
    ReleaseSourceResponse,
    ReleaseSourceUpdate,
)


async def _get_plan(db: AsyncSession, *, plan_id: int, user_id: int) -> ContinuityPlan:
    stmt = select(ContinuityPlan).where(
        ContinuityPlan.id == plan_id, ContinuityPlan.user_id == user_id
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Plan {plan_id} not found")
    return plan


async def _get_thread(db: AsyncSession, *, thread_id: int, user_id: int) -> Thread:
    stmt = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    thread = (await db.execute(stmt)).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Thread {thread_id} not found")
    return thread


async def _require_confirmed_mapping(
    db: AsyncSession, *, thread_id: int, external_identity_id: int
) -> ExternalIdentity:
    """Ensure the volume is a confirmed ComicVine series mapping for the thread."""
    stmt = select(ThreadExternalSeriesMapping).where(
        ThreadExternalSeriesMapping.thread_id == thread_id,
        ThreadExternalSeriesMapping.external_identity_id == external_identity_id,
        ThreadExternalSeriesMapping.status == "confirmed",
    )
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if mapping is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Provider volume must be a confirmed mapping for the thread",
        )
    stmt = select(ExternalIdentity).where(ExternalIdentity.id == external_identity_id)
    identity = (await db.execute(stmt)).scalar_one_or_none()
    if identity is None:  # pragma: no cover - FK guarantees existence
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider identity not found")
    if identity.provider != "comicvine" or identity.entity_type != "series":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Release source must reference a confirmed ComicVine series volume",
        )
    return identity


def _to_response(
    source: ReadingPlanReleaseSource, identity: ExternalIdentity
) -> ReleaseSourceResponse:
    metadata = identity.metadata_json or {}
    title = metadata.get("name") or metadata.get("title")
    return ReleaseSourceResponse(
        id=source.id,
        plan_id=source.plan_id,
        thread_id=source.thread_id,
        external_identity_id=source.external_identity_id,
        provider=identity.provider,
        provider_volume_id=identity.external_id,
        provider_title=str(title) if title else None,
        enabled=source.enabled,
        last_synced_at=source.last_synced_at,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


async def _load_identity(db: AsyncSession, *, identity_id: int) -> ExternalIdentity:
    stmt = select(ExternalIdentity).where(ExternalIdentity.id == identity_id)
    identity = (await db.execute(stmt)).scalar_one_or_none()
    if identity is None:  # pragma: no cover - FK guarantees existence
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider identity not found")
    return identity


async def create_source(
    db: AsyncSession, *, data: ReleaseSourceCreate, user_id: int
) -> ReleaseSourceResponse:
    """Create a release source subscription.

    Validates same-user ownership, confirmed mapping, and uniqueness.
    Retry-safe: duplicate creates return the existing row.
    """
    plan = await _get_plan(db, plan_id=data.plan_id, user_id=user_id)
    thread = await _get_thread(db, thread_id=data.thread_id, user_id=user_id)
    # Both scoped to user_id above; explicit check for clarity.
    if plan.user_id != thread.user_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Plan and thread must be owned by the same user",
        )
    identity = await _require_confirmed_mapping(
        db, thread_id=thread.id, external_identity_id=data.external_identity_id
    )

    # Retry-safe: return existing on duplicate.
    stmt = select(ReadingPlanReleaseSource).where(
        ReadingPlanReleaseSource.plan_id == plan.id,
        ReadingPlanReleaseSource.thread_id == thread.id,
        ReadingPlanReleaseSource.external_identity_id == identity.id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return _to_response(existing, identity)

    source = ReadingPlanReleaseSource(
        plan_id=plan.id,
        thread_id=thread.id,
        external_identity_id=identity.id,
        enabled=True,
    )
    try:
        await repo.create(db, source=source)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Rollback expires ORM state; re-fetch both rows fresh.
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:  # pragma: no cover - defensive
            raise
        await db.refresh(existing)
        fresh_identity = await _load_identity(db, identity_id=identity.id)
        return _to_response(existing, fresh_identity)

    # Extract before refresh to avoid MissingGreenlet.
    source_id = source.id
    await db.refresh(source)
    created = await repo.get_by_id(db, source_id=source_id, user_id=user_id)
    if created is None:  # pragma: no cover - defensive
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Create failed")
    return _to_response(created, identity)


async def list_sources(
    db: AsyncSession, *, plan_id: int, user_id: int
) -> list[ReleaseSourceResponse]:
    """List release sources for a plan with provider metadata."""
    await _get_plan(db, plan_id=plan_id, user_id=user_id)
    sources = await repo.list_for_plan(db, plan_id=plan_id, user_id=user_id)
    if not sources:
        return []
    # Batch-load identities to avoid N+1.
    identity_ids = {s.external_identity_id for s in sources}
    stmt = select(ExternalIdentity).where(ExternalIdentity.id.in_(identity_ids))
    identities = list((await db.execute(stmt)).scalars().all())
    by_id = {i.id: i for i in identities}
    responses = []
    for source in sources:
        identity = by_id.get(source.external_identity_id)
        if identity is None:  # pragma: no cover - FK guarantees existence
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider identity not found")
        responses.append(_to_response(source, identity))
    return responses


async def update_source(
    db: AsyncSession, *, source_id: int, data: ReleaseSourceUpdate, user_id: int
) -> ReleaseSourceResponse:
    """Enable/disable a release source. Non-destructive and idempotent."""
    source = await repo.get_by_id(db, source_id=source_id, user_id=user_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release source not found")
    if data.enabled:
        # Revalidate: the mapping may have been demoted since creation.
        await _require_confirmed_mapping(
            db,
            thread_id=source.thread_id,
            external_identity_id=source.external_identity_id,
        )
    source.enabled = data.enabled
    await db.commit()
    await db.refresh(source)
    identity = await _load_identity(db, identity_id=source.external_identity_id)
    return _to_response(source, identity)


async def delete_source(db: AsyncSession, *, source_id: int, user_id: int) -> None:
    """Delete a release source. Does not touch issues, membership, or state."""
    source = await repo.get_by_id(db, source_id=source_id, user_id=user_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release source not found")
    await repo.delete_by_id(db, source_id=source_id)
    await db.commit()
