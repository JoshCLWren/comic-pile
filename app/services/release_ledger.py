"""Service layer for the durable What's New release ledger."""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.release import Release
from app.schemas.release import ReleaseUpsertRequest


class ReleaseSourceConflictError(ValueError):
    """Raised when PR and merge-SHA provenance identify different releases."""


async def list_published_releases(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Release], int]:
    """List public published releases in deterministic newest-first order.

    Args:
        db: Async database session.
        limit: Maximum releases to return.
        offset: Number of releases to skip.

    Returns:
        The page of releases and total matching release count.
    """
    filters = (Release.status == "published", Release.visibility == "public")
    total = await db.scalar(select(func.count(Release.id)).where(*filters))
    result = await db.execute(
        select(Release)
        .where(*filters)
        .order_by(
            Release.released_at.desc(),
            Release.sort_order.desc(),
            Release.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_published_release(db: AsyncSession, release_id: int) -> Release | None:
    """Fetch one public published release by id.

    Args:
        db: Async database session.
        release_id: Release primary key.

    Returns:
        The published public release, or None when unavailable.
    """
    result = await db.execute(
        select(Release).where(
            Release.id == release_id,
            Release.status == "published",
            Release.visibility == "public",
        )
    )
    return result.scalar_one_or_none()


async def find_release_by_source(
    db: AsyncSession,
    *,
    source_repository: str,
    source_pr_number: int | None,
    source_merge_sha: str | None,
) -> Release | None:
    """Resolve a release by stable GitHub source identity.

    Args:
        db: Async database session.
        source_repository: Repository containing the source pull request.
        source_pr_number: Source pull request number when known.
        source_merge_sha: Source merge commit SHA when known.

    Returns:
        The matching release, or None when no source identity matches.

    Raises:
        ReleaseSourceConflictError: If the PR and merge SHA point to different rows.
    """
    predicates = []
    if source_pr_number is not None:
        predicates.append(Release.source_pr_number == source_pr_number)
    if source_merge_sha is not None:
        predicates.append(Release.source_merge_sha == source_merge_sha)
    if not predicates:
        return None

    result = await db.execute(
        select(Release).where(
            Release.source_repository == source_repository,
            or_(*predicates),
        )
    )
    matches = list(result.scalars().all())
    if len(matches) > 1:
        raise ReleaseSourceConflictError(
            "source PR and merge SHA already identify different release records"
        )
    return matches[0] if matches else None


def _apply_payload(release: Release, payload: ReleaseUpsertRequest) -> None:
    """Apply a validated publication payload while protecting established source identity."""
    if (
        payload.source_pr_number is not None
        and release.source_pr_number is not None
        and payload.source_pr_number != release.source_pr_number
    ):
        raise ReleaseSourceConflictError("merge SHA is already attached to another source PR")
    if (
        payload.source_merge_sha is not None
        and release.source_merge_sha is not None
        and payload.source_merge_sha != release.source_merge_sha
    ):
        raise ReleaseSourceConflictError("source PR is already attached to another merge SHA")
    for field, value in payload.model_dump().items():
        if field in {"source_pr_number", "source_merge_sha"} and value is None:
            continue
        setattr(release, field, value)


async def upsert_release(db: AsyncSession, payload: ReleaseUpsertRequest) -> Release:
    """Create or update one GitHub-backed release idempotently, including concurrent retries.

    Args:
        db: Async database session.
        payload: Validated release publication payload.

    Returns:
        The created or updated durable release.

    Raises:
        ReleaseSourceConflictError: If source identities conflict with established provenance.
        IntegrityError: If persistence fails for a reason other than a concurrent duplicate retry.
    """
    existing = await find_release_by_source(
        db,
        source_repository=payload.source_repository,
        source_pr_number=payload.source_pr_number,
        source_merge_sha=payload.source_merge_sha,
    )

    if existing is None:
        release = Release(**payload.model_dump())
        db.add(release)
    else:
        release = existing
        _apply_payload(release, payload)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        release = await find_release_by_source(
            db,
            source_repository=payload.source_repository,
            source_pr_number=payload.source_pr_number,
            source_merge_sha=payload.source_merge_sha,
        )
        if release is None:
            raise
        _apply_payload(release, payload)
        await db.commit()

    await db.refresh(release)
    return release
