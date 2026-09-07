"""Repository queries for the bounded personal creator summary API (issue #2028).

All data access here stays bounded: a handful of queries that scale with the
reader's library, never with the number of requested creator keys. Rows are
returned as plain tuples/dicts so the service owns all aggregation.
"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

COMICVINE_PROVIDER = "comicvine"


async def list_user_thread_ids(
    db: AsyncSession, *, user_id: int
) -> list[int]:
    """Return the ids of every thread owned by the reader.

    Args:
        db: Async database session.
        user_id: Authenticated reader id.

    Returns:
        Thread ids owned by the reader, ordered deterministically.
    """
    result = await db.scalars(
        select(Thread.id).where(Thread.user_id == user_id).order_by(Thread.id)
    )
    return list(result.all())


async def list_issues_with_creator_metadata(
    db: AsyncSession, *, thread_ids: list[int]
) -> list[tuple[int, str, dict[str, object] | None]]:
    """Return owned issues together with confirmed ComicVine issue metadata.

    Only issue-type external identities contribute metadata, matching the
    confirmed-identity contract in ``app/services/comicvine_intelligence.py``
    so series-level credits never leak into per-issue creator aggregates.

    One row is produced per (Issue, confirmed ComicVine issue identity); issues
    with no confirmed ComicVine identity appear once with ``None`` metadata so
    the service can compute honest coverage. An issue with several confirmed
    ComicVine identities yields several rows and the service merges them.

    Args:
        db: Async database session.
        thread_ids: Owned thread ids bounding the issue universe.

    Returns:
        Rows of ``(issue_id, status, metadata_json)`` ordered by issue id.
    """
    if not thread_ids:
        return []
    result = await db.execute(
        select(Issue.id, Issue.status, ExternalIdentity.metadata_json)
        .outerjoin(
            IssueExternalIdentityMapping,
            and_(
                IssueExternalIdentityMapping.issue_id == Issue.id,
                IssueExternalIdentityMapping.status == "confirmed",
            ),
        )
        .outerjoin(
            ExternalIdentity,
            and_(
                ExternalIdentity.id
                == IssueExternalIdentityMapping.external_identity_id,
                ExternalIdentity.provider == COMICVINE_PROVIDER,
                ExternalIdentity.entity_type == "issue",
            ),
        )
        .where(Issue.thread_id.in_(thread_ids))
        .order_by(Issue.id)
    )
    return [
        (int(issue_id), str(status), metadata)
        for issue_id, status, metadata in result.all()
    ]


async def load_effective_ratings(
    db: AsyncSession, *, issue_ids: set[int]
) -> dict[int, float]:
    """Map each issue to its latest effective rating.

    Multiple rate events for one issue count once with the newest event
    winning, matching the reader-context effective-rating semantics in
    ``app/services/reader_context.py``.

    Args:
        db: Async database session.
        issue_ids: Issues whose effective ratings are needed.

    Returns:
        Issue id to its latest effective rating.
    """
    if not issue_ids:
        return {}
    result = await db.execute(
        select(Event.issue_id, Event.rating)
        .where(
            Event.type == "rate",
            Event.issue_id.in_(issue_ids),
            Event.rating.isnot(None),
        )
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
    )
    effective: dict[int, float] = {}
    for issue_id, rating in result.all():
        if issue_id is not None and issue_id not in effective:
            effective[int(issue_id)] = float(rating)
    return effective