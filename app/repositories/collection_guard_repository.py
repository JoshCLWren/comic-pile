"""Bulk identity evidence for checking prospective collection adoption."""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread


async def identities(db: AsyncSession, ids: Collection[int]) -> list[ExternalIdentity]:
    """Read identities explicitly referenced by source material."""
    if not ids:
        return []
    return list(
        (await db.scalars(select(ExternalIdentity).where(ExternalIdentity.id.in_(ids)))).all()
    )


async def owned_issue_threads(
    db: AsyncSession,
    user_id: int,
    issue_ids: Collection[int],
) -> dict[int, int]:
    """Resolve local targets without disclosing another reader's collection."""
    if not issue_ids:
        return {}
    rows = await db.execute(
        select(Issue.id, Issue.thread_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            Issue.id.in_(issue_ids),
            Thread.user_id == user_id,
        )
    )
    return dict(rows.all())


async def thread_volumes(
    db: AsyncSession,
    user_id: int,
    thread_ids: Collection[int],
) -> list[tuple[int, str, str]]:
    """Read confirmed and catalog-backed series identities for owned Threads."""
    if not thread_ids:
        return []
    confirmed = await db.execute(
        select(
            Thread.id,
            ExternalIdentity.provider,
            ExternalIdentity.external_id,
        )
        .join(ThreadExternalSeriesMapping, ThreadExternalSeriesMapping.thread_id == Thread.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
            ThreadExternalSeriesMapping.status == "confirmed",
            ExternalIdentity.entity_type == "series",
        )
    )
    catalog = await db.execute(
        select(
            Thread.id,
            ExternalIdentity.provider,
            ExternalIdentity.external_id,
        )
        .join(CatalogSeries, CatalogSeries.id == Thread.catalog_series_id)
        .join(ExternalIdentity, ExternalIdentity.id == CatalogSeries.canonical_external_identity_id)
        .where(Thread.id.in_(thread_ids), Thread.user_id == user_id)
    )
    return [(tid, provider, external_id) for tid, provider, external_id in confirmed] + [
        (tid, provider, external_id) for tid, provider, external_id in catalog
    ]


async def issue_identities(
    db: AsyncSession,
    user_id: int,
    issue_ids: Collection[int],
) -> list[tuple[int, ExternalIdentity]]:
    """Read confirmed issue metadata, including provider volume evidence."""
    if not issue_ids:
        return []
    rows = await db.execute(
        select(Issue.id, ExternalIdentity)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(IssueExternalIdentityMapping, IssueExternalIdentityMapping.issue_id == Issue.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            Issue.id.in_(issue_ids),
            Thread.user_id == user_id,
            IssueExternalIdentityMapping.status == "confirmed",
        )
    )
    return [(issue_id, identity) for issue_id, identity in rows]


async def catalog_issue_volumes(
    db: AsyncSession,
    user_id: int,
    issue_ids: Collection[int],
) -> list[tuple[int, str, str]]:
    """Read each Issue's own catalog volume, including mixed-series Threads."""
    if not issue_ids:
        return []
    rows = await db.execute(
        select(Issue.id, ExternalIdentity.provider, ExternalIdentity.external_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(CatalogIssue, CatalogIssue.id == Issue.catalog_issue_id)
        .join(CatalogSeries, CatalogSeries.id == CatalogIssue.catalog_series_id)
        .join(ExternalIdentity, ExternalIdentity.id == CatalogSeries.canonical_external_identity_id)
        .where(Issue.id.in_(issue_ids), Thread.user_id == user_id)
    )
    return [(issue_id, provider, external_id) for issue_id, provider, external_id in rows]
