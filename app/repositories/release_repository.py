"""Query construction and persistence for the durable What's New release ledger.

All SQLAlchemy access for the ``Release`` model family lives here. Functions
return ORM models or plain mappings; the ledger service
(:mod:`app.services.release_ledger`) owns business rules and transaction
boundaries.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.release import Release

#: Columns projected by the token-gated source reconciliation lookup. The
#: potentially large ``body`` column stays unfetched so the reconciliation
#: endpoint keeps its performance budget even for releases with very large
#: bodies.
MINIMAL_SOURCE_COLUMNS = (
    Release.id,
    Release.source_repository,
    Release.source_pr_number,
    Release.source_merge_sha,
    Release.merged_at,
    Release.released_at,
    Release.category,
    Release.title,
    Release.summary,
    Release.visibility,
    Release.status,
    Release.sort_order,
    Release.provenance_json,
    Release.created_at,
    Release.updated_at,
)


def _source_identity_predicates(
    source_pr_number: int | None,
    source_merge_sha: str | None,
) -> list[ColumnElement[bool]]:
    """Build the source-identity predicates for one release repository.

    Args:
        source_pr_number: Source pull request number when known.
        source_merge_sha: Source merge commit SHA when known.

    Returns:
        Predicates matching either supplied source identity.
    """
    predicates: list[ColumnElement[bool]] = []
    if source_pr_number is not None:
        predicates.append(Release.source_pr_number == source_pr_number)
    if source_merge_sha is not None:
        predicates.append(Release.source_merge_sha == source_merge_sha)
    return predicates


async def list_published_releases(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Release], int]:
    """List public published releases in deterministic newest-first order.

    Releases whose title repeats their summary are excluded: those malformed
    backfill rows never belong in the public ledger.

    Args:
        db: Async database session.
        limit: Maximum releases to return.
        offset: Number of releases to skip.

    Returns:
        The page of releases and total matching release count.
    """
    filters = (
        Release.status == "published",
        Release.visibility == "public",
        Release.title != Release.summary,
    )
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

    Releases whose title repeats their summary are excluded, matching the
    public list filter.

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
            Release.title != Release.summary,
        )
    )
    return result.scalar_one_or_none()


async def get_release_for_retraction(db: AsyncSession, release_id: int) -> Release | None:
    """Fetch one published release by id for writer-only retraction.

    Unlike the public read filter, this lookup does not exclude releases whose
    title equals their summary, so malformed backfill records can still be
    retracted even though they never appear in What's New. It also does not
    restrict visibility: retraction is a writer-authorized ledger operation, so
    every published row must stay reachable no matter how it is hidden.

    Args:
        db: Async database session.
        release_id: Release primary key.

    Returns:
        The published release, or None when unavailable.
    """
    result = await db.execute(
        select(Release).where(
            Release.id == release_id,
            Release.status == "published",
        )
    )
    return result.scalar_one_or_none()


async def find_releases_by_source(
    db: AsyncSession,
    *,
    source_repository: str,
    source_pr_number: int | None,
    source_merge_sha: str | None,
) -> list[Release]:
    """Find every release matching a stable GitHub source identity.

    Args:
        db: Async database session.
        source_repository: Repository containing the source pull request.
        source_pr_number: Source pull request number when known.
        source_merge_sha: Source merge commit SHA when known.

    Returns:
        Every matching release, empty when no source identity was supplied.
    """
    predicates = _source_identity_predicates(source_pr_number, source_merge_sha)
    if not predicates:
        return []

    result = await db.execute(
        select(Release).where(
            Release.source_repository == source_repository,
            or_(*predicates),
        )
    )
    return list(result.scalars().all())


async def find_release_rows_by_source(
    db: AsyncSession,
    *,
    source_repository: str,
    source_pr_number: int | None,
    source_merge_sha: str | None,
) -> list[RowMapping]:
    """Find minimal release rows matching a stable GitHub source identity.

    Only the reconciliation fields are retrieved and the potentially large
    ``body`` column is skipped, so the token-gated source endpoint stays inside
    its performance budget even for releases with very large bodies.

    Args:
        db: Async database session.
        source_repository: Repository containing the source pull request.
        source_pr_number: Source pull request number when known.
        source_merge_sha: Source merge commit SHA when known.

    Returns:
        Every matching minimal row, empty when no source identity was supplied.
    """
    predicates = _source_identity_predicates(source_pr_number, source_merge_sha)
    if not predicates:
        return []

    result = await db.execute(
        select(*MINIMAL_SOURCE_COLUMNS).where(
            Release.source_repository == source_repository,
            or_(*predicates),
        )
    )
    return list(result.mappings().all())


async def find_historical_release_candidates(
    db: AsyncSession,
    *,
    source_repository: str,
) -> list[Release]:
    """Find PR-less historical releases for one source repository.

    Historical changelog entries often predate pull-request provenance, so
    their stable identity is the source path plus original entry order.

    Args:
        db: Async database session.
        source_repository: Repository containing the historical source.

    Returns:
        Every PR-less release recorded for the repository.
    """
    result = await db.execute(
        select(Release).where(
            Release.source_repository == source_repository,
            Release.source_pr_number.is_(None),
            Release.source_merge_sha.is_(None),
        )
    )
    return list(result.scalars().all())


async def add_release(db: AsyncSession, release: Release) -> None:
    """Stage one new release row for persistence.

    Args:
        db: Async database session.
        release: Unsaved release row.
    """
    db.add(release)
