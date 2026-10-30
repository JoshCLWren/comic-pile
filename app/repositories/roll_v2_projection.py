"""Bounded Roll v2 bootstrap projection queries.

Purpose-built DB-first read model for ``GET /api/v2/roll/bootstrap`` (issue
#2717). Every fetcher below performs a constant number of database round trips
regardless of pool size: the candidate fetch, the series aggregate fetch, and
the last-read fetch are each exactly one ``execute``. No per-row identity,
cover, rating, progress, or route queries exist; callers assemble the frozen
v2 DTOs from these bulk rows in Python.

Only stored data is read. ComicVine is never called synchronously here:
missing stored metadata yields nulls, never bootstrap failure.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TypedDict

from sqlalchemy import Text, and_, any_, bindparam, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

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

from app.repositories.reading_eligibility_queries import candidate_predicate, frontier_expression
from app.services.reading_eligibility_service import ReadingEligibilitySnapshot

SeriesIdentity = aliased(ExternalIdentity)


class RollableCandidateRow(TypedDict):
    """One flat row of the bulk candidate fetch (one per mapping combination)."""

    thread_id: int
    thread_title: str
    thread_format: str
    last_activity_at: datetime | None
    issue_id: int | None
    issue_number: str | None
    issue_status: str | None
    route_labels: list[str]
    mapping_status: str | None
    mapping_confidence: float | None
    mapping_external_id: str | None
    mapping_metadata: dict[str, object] | None
    series_mapping_status: str | None
    series_external_id: str | None
    series_metadata: dict[str, object] | None
    thread_read_count: int
    thread_total_count: int


class SeriesAggregateRow(TypedDict):
    """One per-(read-issue, rate-event) row used to derive canonical stats."""

    issue_id: int
    identity_metadata: dict[str, object] | None
    rating: float | None
    rated_at: datetime | None
    series_name: str | None
    series_issue_count: str | None


class LastReadRow(TypedDict):
    """The latest rate event in the active session with owned context."""

    issue_id: int | None
    issue_number: str | None
    thread_id: int | None
    thread_title: str | None
    read_at: datetime | None


def _sorted_route_labels(value: object) -> list[str]:
    """Normalize an aggregated route-label array into sorted string labels."""
    if value is None:
        return []
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        raise TypeError("Expected an iterable route-label array")
    return sorted(str(label) for label in value)


def _route_labels_subquery(
    user_id: int, eligibility: ReadingEligibilitySnapshot | None = None
) -> ColumnElement[Sequence[str]]:
    """Aggregate owned route names touching a thread or its next issue."""
    subq = (
        select(func.array_agg(func.distinct(DependencyGroup.name)))
        .select_from(DependencyGroupMembership)
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .where(
            or_(
                DependencyGroupMembership.thread_id == Thread.id,
                DependencyGroupMembership.issue_id == frontier_expression(eligibility),
            ),
            DependencyGroup.user_id == user_id,
        )
        .correlate(Thread)
        .scalar_subquery()
        .cast(ARRAY(Text))
    )
    return subq


async def fetch_rollable_candidates(
    db: AsyncSession,
    *,
    user_id: int,
    die_size: int,
    excluded_thread_ids: list[int],
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> list[RollableCandidateRow]:
    """Fetch rollable candidate threads with identity and route context.

    Exactly one database round trip. Returns one flat row per
    (candidate x issue-mapping x series-mapping) combination; callers group by
    thread in Python. Threads whose ``next_unread_issue_id`` pointer is null
    are still returned so the service can omit them and prove they hold no
    unread target.

    Args:
        db: Async database session.
        user_id: Owner of the threads.
        die_size: Current die size; caps the candidate pool.
        excluded_thread_ids: Snoozed/skipped thread ids to exclude.
        eligibility: Validated live result, or None for legacy execution.

    Returns:
        Flat candidate rows ordered by queue position.
    """
    thread_read_count = (
        select(func.count(Issue.id))
        .where(Issue.thread_id == Thread.id, Issue.status == "read")
        .correlate(Thread)
        .scalar_subquery()
    )
    thread_total_count = (
        select(func.count(Issue.id))
        .where(Issue.thread_id == Thread.id)
        .correlate(Thread)
        .scalar_subquery()
    )
    candidate_ids = (
        select(Thread.id)
        .where(Thread.user_id == user_id, Thread.status == "active", Thread.queue_position >= 1)
        .where(candidate_predicate(eligibility))
        .order_by(Thread.queue_position, Thread.id)
        .limit(die_size)
    )
    if excluded_thread_ids:
        candidate_ids = candidate_ids.where(Thread.id.not_in(excluded_thread_ids))
    bounded = candidate_ids.cte("bounded_roll_thread_ids")
    query = (
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.last_activity_at,
            Issue.id,
            Issue.issue_number,
            Issue.status,
            _route_labels_subquery(user_id, eligibility).label("route_labels"),
            IssueExternalIdentityMapping.status,
            IssueExternalIdentityMapping.confidence,
            ExternalIdentity.external_id,
            ExternalIdentity.metadata_json,
            ThreadExternalSeriesMapping.status,
            SeriesIdentity.external_id,
            SeriesIdentity.metadata_json,
            func.coalesce(thread_read_count, 0).label("thread_read_count"),
            func.coalesce(thread_total_count, 0).label("thread_total_count"),
        )
        .select_from(Thread)
        .outerjoin(Issue, Issue.id == frontier_expression(eligibility))
        .outerjoin(
            IssueExternalIdentityMapping,
            and_(
                IssueExternalIdentityMapping.issue_id == Issue.id,
                IssueExternalIdentityMapping.status != "rejected",
            ),
        )
        .outerjoin(
            ExternalIdentity,
            and_(
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
            ),
        )
        .outerjoin(
            ThreadExternalSeriesMapping,
            and_(
                ThreadExternalSeriesMapping.thread_id == Thread.id,
                ThreadExternalSeriesMapping.status != "rejected",
            ),
        )
        .outerjoin(
            SeriesIdentity,
            and_(
                SeriesIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
                SeriesIdentity.provider == "comicvine",
                SeriesIdentity.entity_type == "series",
            ),
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(candidate_predicate(eligibility))
        .order_by(Thread.queue_position, Thread.id)
    )
    if excluded_thread_ids:
        query = query.where(Thread.id.not_in(excluded_thread_ids))
    # Bound Threads before joining multiple identity rows, so identity fan-out
    # cannot consume a second Thread's place in the die pool.
    query = query.where(Thread.id.in_(select(bounded.c.id)))
    result = await db.execute(query)
    rows: list[RollableCandidateRow] = []
    for row in result.all():
        mapping_metadata = row[11]
        series_metadata = row[14]
        rows.append(
            RollableCandidateRow(
                thread_id=row[0],
                thread_title=row[1],
                thread_format=row[2],
                last_activity_at=row[3],
                issue_id=row[4],
                issue_number=row[5],
                issue_status=row[6],
                route_labels=_sorted_route_labels(row[7]),
                mapping_status=row[8],
                mapping_confidence=row[9],
                mapping_external_id=row[10],
                mapping_metadata=mapping_metadata if isinstance(mapping_metadata, dict) else None,
                series_mapping_status=row[12],
                series_external_id=row[13],
                series_metadata=series_metadata if isinstance(series_metadata, dict) else None,
                thread_read_count=int(row[15] or 0),
                thread_total_count=int(row[16] or 0),
            )
        )
    return rows


async def fetch_series_aggregates(
    db: AsyncSession,
    *,
    user_id: int,
    volume_ids: list[int],
) -> list[SeriesAggregateRow]:
    """Fetch per-issue rating rows for canonical volumes in one round trip.

    Covers every currently-read owned issue confirmed to any of the given
    ComicVine volumes, left-joined to all of its rated ``rate`` events, plus
    the stored catalog series name/volume size per row. Callers keep the
    latest event per distinct issue (effective rating, #1401) and aggregate
    per volume in Python. Empty input performs no query.

    The volume id is normalized once per identity row and matched against one
    array bind (issue #4315). The previous implementation OR'd four JSON
    containment predicates per volume, so a d100 bootstrap built roughly 400
    unindexable ``metadata_json::jsonb @>`` clauses and then ran two correlated
    scalar subqueries per returned row. This version is a single array
    predicate plus one hash join to the catalog series row.

    Args:
        db: Async database session.
        user_id: Owner of the issues.
        volume_ids: Canonical ComicVine volume ids to aggregate.

    Returns:
        Per-(issue, rate-event) rows; one row with null rating when unrated.
    """
    if not volume_ids:
        return []
    # JSON numeric IDs can stringify as "20764.0" while stored catalog IDs
    # use "20764". Normalize integral numeric text without unsafe numeric casts.
    catalog_volume_id = func.regexp_replace(
        func.coalesce(
            ExternalIdentity.metadata_json["volume"]["id"].as_string(),
            ExternalIdentity.metadata_json["volume_id"].as_string(),
        ),
        r"\.0+$",
        "",
    )
    requested_volume_ids = bindparam(
        "roll_projection_volume_ids",
        value=[str(volume_id) for volume_id in volume_ids],
        type_=ARRAY(Text),
    )
    query = (
        select(
            Issue.id,
            ExternalIdentity.metadata_json,
            Event.rating,
            Event.timestamp,
            SeriesIdentity.metadata_json["name"].as_string().label("series_name"),
            SeriesIdentity.metadata_json["count_of_issues"]
            .as_string()
            .label("series_issue_count"),
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
            SeriesIdentity,
            and_(
                SeriesIdentity.provider == "comicvine",
                SeriesIdentity.entity_type == "series",
                SeriesIdentity.external_id == catalog_volume_id,
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
        .where(catalog_volume_id == any_(requested_volume_ids))
        .order_by(Issue.id, Event.timestamp.desc().nullslast(), Event.id.desc().nullslast())
    )
    result = await db.execute(query)
    rows: list[SeriesAggregateRow] = []
    for row in result.all():
        metadata = row[1]
        rows.append(
            SeriesAggregateRow(
                issue_id=int(row[0]),
                identity_metadata=metadata if isinstance(metadata, dict) else None,
                rating=float(row[2]) if row[2] is not None else None,
                rated_at=row[3],
                series_name=row[4] if isinstance(row[4], str) else None,
                series_issue_count=row[5] if isinstance(row[5], str) else None,
            )
        )
    return rows


async def fetch_session_last_read(
    db: AsyncSession,
    *,
    session_id: int,
    user_id: int,
) -> LastReadRow | None:
    """Fetch the latest rate event in the active session in one round trip.

    Args:
        db: Async database session.
        session_id: Active reading session.
        user_id: Owner scoping the joined thread.

    Returns:
        The latest session rate event with owned context, or None.
    """
    query = (
        select(
            Event.issue_id,
            func.coalesce(Issue.issue_number, Event.issue_number).label("issue_number"),
            Event.thread_id,
            Thread.title,
            Event.timestamp,
        )
        .select_from(Event)
        .outerjoin(Issue, Issue.id == Event.issue_id)
        .outerjoin(
            Thread,
            and_(Thread.id == Event.thread_id, Thread.user_id == user_id),
        )
        .where(Event.session_id == session_id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    result = await db.execute(query)
    row = result.one_or_none()
    if row is None:
        return None
    return LastReadRow(
        issue_id=row[0],
        issue_number=row[1],
        thread_id=row[2],
        thread_title=row[3],
        read_at=row[4],
    )
