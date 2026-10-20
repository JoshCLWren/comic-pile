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
from app.repositories import reading_plan_repository
from app.schemas.reading_plan_reader import ReadingPlanReleaseSourceStatus
from app.schemas.reading_plan_release_source import (
    ReadingPlanReleaseCandidate,
    ReleaseSourceCreate,
    ReleaseSourceResponse,
    ReleaseSourceUpdate,
)


def _provider_display_from_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Extract reader-safe display metadata from provider identity metadata.

    Args:
        metadata: Provider identity metadata payload.

    Returns:
        A mapping with title, publisher, start_year, and issue_count when the
        provider metadata carries them. Internal confidence and identity
        evidence fields are never surfaced.
    """
    display: dict[str, object] = {}
    title = metadata.get("name") or metadata.get("title")
    if isinstance(title, str) and title.strip():
        display["title"] = title.strip()
    publisher = metadata.get("publisher")
    if isinstance(publisher, str) and publisher.strip():
        display["publisher"] = publisher.strip()
    elif isinstance(publisher, dict):
        publisher_name = publisher.get("name")
        if isinstance(publisher_name, str) and publisher_name.strip():
            display["publisher"] = publisher_name.strip()
    start_year = metadata.get("start_year")
    if isinstance(start_year, int) and not isinstance(start_year, bool):
        display["start_year"] = start_year
    elif isinstance(start_year, str) and start_year.strip().isdigit():
        display["start_year"] = int(start_year.strip())
    issue_count = metadata.get("count_of_issues") or metadata.get("issue_count")
    if isinstance(issue_count, int) and not isinstance(issue_count, bool):
        display["issue_count"] = issue_count
    elif isinstance(issue_count, str) and issue_count.strip().isdigit():
        display["issue_count"] = int(issue_count.strip())
    return display


def _provider_display_metadata(identity: ExternalIdentity) -> dict[str, object]:
    """Extract reader-safe display metadata from a provider identity.

    Args:
        identity: Confirmed ComicVine series identity.

    Returns:
        A mapping with title, publisher, start_year, and issue_count when the
        provider metadata carries them. Internal confidence and identity
        evidence fields are never surfaced.
    """
    return _provider_display_from_metadata(identity.metadata_json or {})


def _to_release_source_status(
    source: ReadingPlanReleaseSource, identity: ExternalIdentity
) -> ReadingPlanReleaseSourceStatus:
    """Project a release source onto its reader-facing status schema.

    Args:
        source: Persisted release source with an eagerly loaded identity.
        identity: Provider identity for the source.

    Returns:
        Reader-safe release source status with display metadata.
    """
    display = _provider_display_metadata(identity)
    return ReadingPlanReleaseSourceStatus(
        source_id=source.id,
        thread_id=source.thread_id,
        external_identity_id=source.external_identity_id,
        provider_volume_id=identity.external_id,
        provider_title=display.get("title") if isinstance(display.get("title"), str) else None,
        provider_publisher=display.get("publisher") if isinstance(display.get("publisher"), str) else None,
        provider_start_year=display.get("start_year") if isinstance(display.get("start_year"), int) else None,
        provider_issue_count=display.get("issue_count") if isinstance(display.get("issue_count"), int) else None,
        enabled=source.enabled,
        last_synced_at=source.last_synced_at,
    )


async def list_release_sources_for_reader(
    db: AsyncSession, *, plan_id: int, user_id: int
) -> list[ReadingPlanReleaseSourceStatus]:
    """List reader-facing release source status for one plan.

    Args:
        db: Database session.
        plan_id: Plan to inspect.
        user_id: Authenticated plan owner.

    Returns:
        Release source status rows ordered by creation, including disabled
        sources so the reader can re-enable them.
    """
    await _get_plan(db, plan_id=plan_id, user_id=user_id)
    sources = await repo.list_for_plan(db, plan_id=plan_id, user_id=user_id)
    if not sources:
        return []
    identity_ids = {s.external_identity_id for s in sources}
    stmt = select(ExternalIdentity).where(ExternalIdentity.id.in_(identity_ids))
    identities = list((await db.execute(stmt)).scalars().all())
    by_id = {i.id: i for i in identities}
    responses: list[ReadingPlanReleaseSourceStatus] = []
    for source in sources:
        identity = by_id.get(source.external_identity_id)
        if identity is None:  # pragma: no cover - FK guarantees existence
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider identity not found")
        responses.append(_to_release_source_status(source, identity))
    return responses


def _thread_node_ids(nodes_json: list[dict[str, object]]) -> list[int]:
    """Collect the Thread ids a plan references as whole-series nodes.

    Args:
        nodes_json: Plan node payload.

    Returns:
        Thread ids referenced by ``thread``-type nodes, in first-seen order.
    """
    thread_ids: list[int] = []
    for node in nodes_json:
        if not isinstance(node, dict):
            continue
        if node.get("node_type") != "thread":
            continue
        ref_id = node.get("ref_id")
        if isinstance(ref_id, int) and not isinstance(ref_id, bool):
            thread_ids.append(ref_id)
    return thread_ids


def _candidate_volume_fields(
    mapping: repo.ThreadSeriesMappingRow,
) -> dict[str, object]:
    """Project provider display metadata onto candidate volume fields.

    Args:
        mapping: Series mapping row with its provider identity metadata.

    Returns:
        Reader-safe provider fields for the candidate volume.
    """
    display = _provider_display_from_metadata(mapping.metadata_json)
    title = display.get("title")
    publisher = display.get("publisher")
    start_year = display.get("start_year")
    issue_count = display.get("issue_count")
    return {
        "external_identity_id": mapping.external_identity_id,
        "provider_volume_id": mapping.provider_volume_id,
        "provider_title": title if isinstance(title, str) else None,
        "provider_publisher": publisher if isinstance(publisher, str) else None,
        "provider_start_year": start_year if isinstance(start_year, int) else None,
        "provider_issue_count": issue_count if isinstance(issue_count, int) else None,
        "mapping_status": mapping.status,
    }


async def list_release_candidates_for_reader(
    db: AsyncSession, *, plan_id: int, user_id: int
) -> list[ReadingPlanReleaseCandidate]:
    """List the ComicVine volumes a plan's threads could follow.

    A candidate is a confirmed ComicVine series mapping for one of the plan's
    threads that is not already followed. Threads whose ComicVine series
    mapping is still undecided are reported as ambiguous, and threads with no
    ComicVine series mapping at all are reported as unmapped, so the reader
    can be routed to mapping repair instead of being offered a volume whose
    identity is not settled.

    Args:
        db: Database session.
        plan_id: Plan to inspect.
        user_id: Authenticated plan owner.

    Returns:
        Candidate volumes in plan thread order.
    """
    plan = await _get_plan(db, plan_id=plan_id, user_id=user_id)
    threads = await reading_plan_repository.list_plan_threads(
        db,
        plan_id=plan_id,
        extra_thread_ids=_thread_node_ids(plan.nodes_json),
    )
    if not threads:
        return []
    mappings = await repo.list_series_mappings_for_threads(
        db, thread_ids=[thread.thread_id for thread in threads]
    )
    followed = await repo.list_followed_volume_keys(db, plan_id=plan_id)

    by_thread: dict[int, list[repo.ThreadSeriesMappingRow]] = {}
    for mapping in mappings:
        if mapping.provider != "comicvine" or mapping.entity_type != "series":
            continue
        if mapping.status == "rejected":
            continue
        by_thread.setdefault(mapping.thread_id, []).append(mapping)

    candidates: list[ReadingPlanReleaseCandidate] = []
    for thread in threads:
        thread_mappings = by_thread.get(thread.thread_id, [])
        confirmed = [m for m in thread_mappings if m.status == "confirmed"]
        if confirmed:
            for mapping in confirmed:
                if (thread.thread_id, mapping.external_identity_id) in followed:
                    continue
                candidates.append(
                    ReadingPlanReleaseCandidate(
                        thread_id=thread.thread_id,
                        thread_title=thread.thread_title,
                        mapping_state="confirmed",
                        **_candidate_volume_fields(mapping),
                        enableable=True,
                        followed=False,
                    )
                )
            continue
        if not thread_mappings:
            candidates.append(
                ReadingPlanReleaseCandidate(
                    thread_id=thread.thread_id,
                    thread_title=thread.thread_title,
                    mapping_state="unmapped",
                    enableable=False,
                    followed=False,
                )
            )
            continue
        for mapping in thread_mappings:
            candidates.append(
                ReadingPlanReleaseCandidate(
                    thread_id=thread.thread_id,
                    thread_title=thread.thread_title,
                    mapping_state="ambiguous",
                    **_candidate_volume_fields(mapping),
                    enableable=False,
                    followed=False,
                )
            )
    return candidates


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
