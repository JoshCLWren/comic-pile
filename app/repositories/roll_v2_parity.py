"""Independent source-of-truth reads for the Roll v2 parity harness (issue #2718).

These queries deliberately do NOT reuse the v2 projection SQL, and the tiny
metadata coercers below are local re-implementations rather than imports of
:mod:`app.services.roll_v2_projection`. The harness recomputes expected values
from simpler, independently formulated statements so a bug shared with the v2
projection cannot normalize itself away. Every fetcher is a single bulk
statement with an empty-input no-op, read-only, and owner-scoped.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    DependencyGroup,
    DependencyGroupMembership,
    Event,
    ExternalIdentity,
    Issue,
    IssueExternalIdentityMapping,
    Thread,
    ThreadExternalSeriesMapping,
)

SeriesIdentity = aliased(ExternalIdentity)


def _local_text(value: object) -> str | None:
    """Coerce a stored provider value to a trimmed non-empty string.

    Args:
        value: Raw provider value.

    Returns:
        The trimmed string, or None when empty or not a string.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _local_int(value: object) -> int | None:
    """Coerce a stored provider value to an integer.

    Args:
        value: Raw provider value.

    Returns:
        The integer value, or None when not numeric.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _local_volume(metadata: dict[str, object] | None) -> tuple[int | None, str | None]:
    """Extract the stored ComicVine volume id and name locally.

    Args:
        metadata: Confirmed ComicVine issue identity metadata.

    Returns:
        Tuple of (volume id, volume name), either of which may be None.
    """
    if not metadata:
        return None, None
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        return _local_int(volume.get("id")), _local_text(volume.get("name"))
    return _local_int(metadata.get("volume_id")), _local_text(metadata.get("volume_name"))


class ParityFrontierRow(TypedDict):
    """The harness's independent frontier for one thread.

    Derived as the first unread issue by ``(position, id)`` — deliberately a
    different formulation than the production ``Thread.next_unread_issue_id``
    pointer, so a stale pointer surfaces as a reported discrepancy instead of
    silently matching.
    """

    thread_id: int
    issue_id: int | None
    issue_number: str | None
    unread_count: int


class ParityMappingRow(TypedDict):
    """One stored identity mapping observation for a frontier issue."""

    issue_id: int
    mapping_status: str | None
    mapping_confidence: float | None
    mapping_external_id: str | None
    mapping_metadata: dict[str, object] | None


class ParitySeriesMappingRow(TypedDict):
    """One stored thread-level external series mapping observation."""

    thread_id: int
    status: str | None
    external_id: str | None
    metadata: dict[str, object] | None


class ParityRatingRow(TypedDict):
    """One (confirmed read issue, rate event) observation for rating math."""

    volume_id: int | None
    volume_name: str | None
    issue_id: int
    issue_number: str
    rating: float | None
    rated_at: datetime | None


class ParityMembershipRow(TypedDict):
    """One dependency-group membership observation (thread or issue edge)."""

    thread_id: int | None
    issue_id: int | None
    group_name: str


class ParitySeriesCatalogRow(TypedDict):
    """Stored catalog series identity for one explicit ComicVine volume id."""

    volume_id: int
    series_name: str | None
    issue_count: int | None


class ParityThreadFactRow(TypedDict):
    """Thread facts used for fallback-progress and summary validation."""

    thread_id: int
    title: str
    format: str
    last_activity_at: datetime | None
    read_count: int
    issue_count: int


class ParityLastReadRow(TypedDict):
    """The harness's independently chosen latest session rate event."""

    issue_id: int | None
    issue_number: str | None
    thread_id: int | None
    thread_title: str | None
    read_at: datetime | None


async def fetch_parity_frontiers(
    db: AsyncSession, user_id: int, thread_ids: list[int]
) -> dict[int, ParityFrontierRow]:
    """Independently derive each thread's next unread issue and unread count.

    The frontier is the first unread issue for the thread ordered by issue
    position then id; a thread with zero unread rows has ``None``. This is
    intentionally independent from the production stored pointer.

    Args:
        db: Async database session.
        user_id: Owner of the threads.
        thread_ids: Candidate thread ids to derive.

    Returns:
        Mapping of thread id to derived frontier; threads without unread
        issues map to ``issue_id`` ``None``.
    """
    if not thread_ids:
        return {}
    result = await db.execute(
        select(Issue.thread_id, Issue.id, Issue.issue_number)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Issue.status == "unread")
        .where(Issue.thread_id.in_(thread_ids))
        .order_by(Issue.thread_id, Issue.position, Issue.id)
    )
    frontiers: dict[int, ParityFrontierRow] = {
        thread_id: ParityFrontierRow(
            thread_id=thread_id, issue_id=None, issue_number=None, unread_count=0
        )
        for thread_id in thread_ids
    }
    for thread_id, issue_id, issue_number in result.all():
        row = frontiers.get(int(thread_id))
        if row is None:
            continue
        row["unread_count"] = int(row["unread_count"]) + 1
        if row["issue_id"] is None:
            row["issue_id"] = int(issue_id)
            row["issue_number"] = str(issue_number)
    return frontiers


async def fetch_parity_issue_mappings(
    db: AsyncSession, user_id: int, frontier_issue_ids: list[int]
) -> dict[int, list[ParityMappingRow]]:
    """Fetch every stored identity mapping observation for frontier issues.

    Args:
        db: Async database session.
        user_id: Owner scope protecting the join.
        frontier_issue_ids: Issue ids whose mappings to load.

    Returns:
        Mapping of issue id to its non-rejected ComicVine mapping rows.
    """
    if not frontier_issue_ids:
        return {}
    result = await db.execute(
        select(
            Issue.id,
            IssueExternalIdentityMapping.status,
            IssueExternalIdentityMapping.confidence,
            ExternalIdentity.external_id,
            ExternalIdentity.metadata_json,
        )
        .select_from(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            and_(
                IssueExternalIdentityMapping.issue_id == Issue.id,
                IssueExternalIdentityMapping.status != "rejected",
            ),
        )
        .join(
            ExternalIdentity,
            and_(
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
            ),
        )
        .where(Thread.user_id == user_id)
        .where(Issue.id.in_(frontier_issue_ids))
    )
    by_issue: dict[int, list[ParityMappingRow]] = {}
    for issue_id, status, confidence, external_id, metadata in result.all():
        by_issue.setdefault(int(issue_id), []).append(
            ParityMappingRow(
                issue_id=int(issue_id),
                mapping_status=status,
                mapping_confidence=float(confidence) if confidence is not None else None,
                mapping_external_id=_local_text(external_id),
                mapping_metadata=metadata if isinstance(metadata, dict) else None,
            )
        )
    return by_issue


async def fetch_parity_series_mappings(
    db: AsyncSession, user_id: int, thread_ids: list[int]
) -> dict[int, list[ParitySeriesMappingRow]]:
    """Fetch stored thread-level external series mappings.

    Args:
        db: Async database session.
        user_id: Owner of the threads.
        thread_ids: Threads whose series mappings to load.

    Returns:
        Mapping of thread id to its non-rejected series mapping rows.
    """
    if not thread_ids:
        return {}
    result = await db.execute(
        select(
            ThreadExternalSeriesMapping.thread_id,
            ThreadExternalSeriesMapping.status,
            SeriesIdentity.external_id,
            SeriesIdentity.metadata_json,
        )
        .join(
            SeriesIdentity,
            and_(
                SeriesIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
                SeriesIdentity.provider == "comicvine",
                SeriesIdentity.entity_type == "series",
            ),
        )
        .join(Thread, Thread.id == ThreadExternalSeriesMapping.thread_id)
        .where(Thread.id.in_(thread_ids))
        .where(Thread.user_id == user_id)
        .where(ThreadExternalSeriesMapping.status != "rejected")
    )
    by_thread: dict[int, list[ParitySeriesMappingRow]] = {}
    for thread_id, status, external_id, metadata in result.all():
        by_thread.setdefault(int(thread_id), []).append(
            ParitySeriesMappingRow(
                thread_id=int(thread_id),
                status=status,
                external_id=_local_text(external_id),
                metadata=metadata if isinstance(metadata, dict) else None,
            )
        )
    return by_thread


async def fetch_parity_series_analytics(
    db: AsyncSession, user_id: int
) -> list[ParityRatingRow]:
    """Load every owned read issue's confirmed identity plus its rate events.

    The harness derives per-volume effective-rating aggregates in Python from
    these rows using #1401 semantics, independently of the projection query.

    Args:
        db: Async database session.
        user_id: Owner of the issues.

    Returns:
        One row per (read confirmed issue, rate event); unrated issues appear
        with ``rating`` ``None``.
    """
    result = await db.execute(
        select(
            ExternalIdentity.metadata_json,
            Issue.id,
            Issue.issue_number,
            Event.rating,
            Event.timestamp,
        )
        .select_from(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            and_(
                IssueExternalIdentityMapping.issue_id == Issue.id,
                IssueExternalIdentityMapping.status == "confirmed",
            ),
        )
        .join(
            ExternalIdentity,
            and_(
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
            ),
        )
        .outerjoin(
            Event,
            and_(
                Event.issue_id == Issue.id,
                Event.type == "rate",
                Event.rating.isnot(None),
            ),
        )
        .where(Thread.user_id == user_id)
        .where(Issue.status == "read")
        .order_by(Issue.id, Event.timestamp.desc().nullslast(), Event.id.desc().nullslast())
    )
    rows: list[ParityRatingRow] = []
    for metadata, issue_id, issue_number, rating, rated_at in result.all():
        metadata_dict = metadata if isinstance(metadata, dict) else None
        volume_id, volume_name = _local_volume(metadata_dict)
        rows.append(
            ParityRatingRow(
                volume_id=volume_id,
                volume_name=volume_name,
                issue_id=int(issue_id),
                issue_number=str(issue_number),
                rating=float(rating) if rating is not None else None,
                rated_at=rated_at,
            )
        )
    return rows


async def fetch_parity_series_catalog(
    db: AsyncSession, volume_ids: list[int]
) -> dict[int, ParitySeriesCatalogRow]:
    """Fetch the stored catalog series identity for explicit volume ids.

    Args:
        db: Async database session.
        volume_ids: ComicVine volume ids to look up.

    Returns:
        Mapping of volume id to stored series name and provider run length.
    """
    if not volume_ids:
        return {}
    result = await db.execute(
        select(
            SeriesIdentity.external_id,
            SeriesIdentity.metadata_json,
        ).where(
            SeriesIdentity.provider == "comicvine",
            SeriesIdentity.entity_type == "series",
            SeriesIdentity.external_id.in_([str(volume_id) for volume_id in volume_ids]),
        )
    )
    catalog: dict[int, ParitySeriesCatalogRow] = {}
    for external_id, metadata in result.all():
        try:
            volume_id = int(external_id)
        except (TypeError, ValueError):
            continue
        metadata_dict = metadata if isinstance(metadata, dict) else None
        name = _local_text((metadata_dict or {}).get("name"))
        count = _local_int((metadata_dict or {}).get("count_of_issues"))
        catalog[volume_id] = ParitySeriesCatalogRow(
            volume_id=volume_id,
            series_name=name,
            issue_count=count,
        )
    return catalog


async def fetch_parity_thread_facts(
    db: AsyncSession, user_id: int, thread_ids: list[int]
) -> dict[int, ParityThreadFactRow]:
    """Fetch thread facts for fallback-progress and summary validation.

    Args:
        db: Async database session.
        user_id: Owner of the threads.
        thread_ids: Threads to load.

    Returns:
        Mapping of thread id to title/format/activity/read/total facts.
    """
    if not thread_ids:
        return {}
    result = await db.execute(
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.last_activity_at,
            func.count(Issue.id).filter(Issue.status == "read").label("read_count"),
            func.count(Issue.id).label("issue_count"),
        )
        .outerjoin(Issue, Issue.thread_id == Thread.id)
        .where(Thread.id.in_(thread_ids))
        .where(Thread.user_id == user_id)
        .group_by(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.last_activity_at,
        )
    )
    facts: dict[int, ParityThreadFactRow] = {}
    for thread_id, title, fmt, activity, read_count, issue_count in result.all():
        facts[int(thread_id)] = ParityThreadFactRow(
            thread_id=int(thread_id),
            title=str(title),
            format=str(fmt),
            last_activity_at=activity,
            read_count=int(read_count or 0),
            issue_count=int(issue_count or 0),
        )
    return facts


async def fetch_parity_route_memberships(
    db: AsyncSession,
    user_id: int,
    thread_ids: list[int],
    frontier_issue_ids: list[int],
) -> list[ParityMembershipRow]:
    """Load dependency-group membership rows on thread or frontier edges.

    The harness resolves issue membership edges to their thread by looking up
    the frontier owner map, preserving the product meaning of a route label:
    groups whose membership touches the thread itself or its frontier issue.

    Args:
        db: Async database session.
        user_id: Owner of the groups.
        thread_ids: Threads whose direct membership edges load.
        frontier_issue_ids: Frontier issue ids whose membership edges load.

    Returns:
        Membership observations with the raw thread/issue edges.
    """
    if not thread_ids and not frontier_issue_ids:
        return []
    result = await db.execute(
        select(
            DependencyGroupMembership.thread_id,
            DependencyGroupMembership.issue_id,
            DependencyGroup.name,
        )
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .where(DependencyGroup.user_id == user_id)
        .where(
            or_(
                DependencyGroupMembership.thread_id.in_(thread_ids),
                DependencyGroupMembership.issue_id.in_(frontier_issue_ids),
            )
        )
        .order_by(DependencyGroup.name)
    )
    return [
        ParityMembershipRow(
            thread_id=int(thread_id) if thread_id is not None else None,
            issue_id=int(issue_id) if issue_id is not None else None,
            group_name=str(name),
        )
        for thread_id, issue_id, name in result.all()
    ]


async def fetch_parity_last_read(
    db: AsyncSession, session_id: int, user_id: int
) -> ParityLastReadRow | None:
    """Fetch the latest rate event in one active session, independently.

    Args:
        db: Async database session.
        session_id: Active reading session id.
        user_id: Owner scoping the joined thread.

    Returns:
        The independently resolved last-read row, or ``None``.
    """
    result = await db.execute(
        select(
            Event.issue_id,
            Event.issue_number,
            Event.thread_id,
            Thread.title,
            Event.timestamp,
        )
        .join(Thread, Thread.id == Event.thread_id)
        .where(Event.session_id == session_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.rating.isnot(None))
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    issue_id = row[0]
    return ParityLastReadRow(
        issue_id=int(issue_id) if issue_id is not None else None,
        issue_number=_local_text(row[1]),
        thread_id=int(row[2]) if row[2] is not None else None,
        thread_title=str(row[3]) if row[3] is not None else None,
        read_at=row[4],
    )


async def fetch_parity_stale_candidate_ids(
    db: AsyncSession,
    user_id: int,
    *,
    cutoff: datetime,
    excluded_ids: list[int],
) -> list[int]:
    """Return the independently derived stale candidate thread ids.

    Mirrors the legacy production predicate: active, not blocked, in queue,
    effective activity older than the cutoff, and not in the effective
    snoozed/backoff exclusion scope. The harness validates random stale picks
    at the candidate-set level, never trusting a single random draw.

    Args:
        db: Async database session.
        user_id: Owner of the threads.
        cutoff: Activity strictly older than this instant is stale.
        excluded_ids: Snoozed/backoff thread ids excluded from staleness.

    Returns:
        Stale candidate thread ids ordered deterministically.
    """
    statement = (
        select(Thread.id)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where(Thread.queue_position >= 1)
        .where(func.coalesce(Thread.last_activity_at, Thread.created_at) < cutoff)
        .order_by(Thread.id)
    )
    if excluded_ids:
        statement = statement.where(Thread.id.not_in(excluded_ids))
    result = await db.execute(statement)
    return [int(row[0]) for row in result.all()]
