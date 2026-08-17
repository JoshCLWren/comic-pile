"""Reader context analytics: canonical series and crossover stats for an issue."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DependencyGroup,
    DependencyGroupMembership,
    Event,
    ExternalIdentity,
    Issue,
    Thread,
    ThreadExternalSeriesMapping,
)
from app.schemas.issue import (
    CanonicalSeriesInfo,
    CrossoverAnalyticsInfo,
    CrossoverNodeInfo,
    PreviousIssueInfo,
    ReaderContextResponse,
    RecentRatingEntry,
)


async def build_reader_context(
    issue_id: int,
    user_id: int,
    db: AsyncSession,
) -> ReaderContextResponse:
    """Build reader-context analytics for a single issue.

    Computes canonical series statistics (from confirmed external series
    identity) and crossover analytics (from dependency group memberships
    that apply to the current issue).

    Args:
        issue_id: The ComicPile issue identifier.
        user_id: ID of the authenticated owner.
        db: Async database session.

    Returns:
        ReaderContextResponse with canonical series and crossover data.
        When canonical identity is unavailable, identity_source is set to
        "unavailable" and canonical_series is still returned with no stats.
    """
    issue = await _get_owned_issue(db, user_id, issue_id)
    if issue is None:
        return ReaderContextResponse()

    thread: Thread = issue.thread
    thread_id_val: int = thread.id
    issue_position_val: int = issue.position
    issue_number_val: str = issue.issue_number

    applicable_group_ids = await _resolve_applicable_crossover_groups(
        db, user_id, issue_id, thread_id_val
    )

    canonical_series = await _build_canonical_series(
        db, user_id, thread_id_val, issue_id, issue_position_val, issue_number_val
    )

    crossover_panel = await _build_crossover_panel(
        db, user_id, applicable_group_ids, thread_id_val, issue_id, issue_number_val
    )

    return ReaderContextResponse(
        canonical_series=canonical_series,
        crossover_panel=crossover_panel,
    )


async def _get_owned_issue(
    db: AsyncSession, user_id: int, issue_id: int
) -> Issue | None:
    result = await db.execute(
        select(Issue)
        .options(selectinload(Issue.thread))
        .join(Thread, Issue.thread_id == Thread.id)
        .where(Issue.id == issue_id, Thread.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _resolve_applicable_crossover_groups(
    db: AsyncSession,
    user_id: int,
    issue_id: int,
    thread_id: int,
) -> set[int]:
    result = await db.execute(
        select(DependencyGroupMembership.group_id)
        .join(DependencyGroup, DependencyGroupMembership.group_id == DependencyGroup.id)
        .where(
            DependencyGroup.user_id == user_id,
            (
                (DependencyGroupMembership.issue_id == issue_id)
                | (DependencyGroupMembership.thread_id == thread_id)
            ),
        )
    )
    return {row.group_id for row in result}


async def _build_canonical_series(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    current_issue_id: int,
    current_issue_position: int,
    current_issue_number: str,
) -> CanonicalSeriesInfo | None:
    identity = await _resolve_series_identity(db, user_id, thread_id)
    if identity is None:
        return CanonicalSeriesInfo(identity_source="unavailable")

    external_id: str = identity.external_id
    series_members = await _get_series_threads(db, user_id, external_id)
    member_ids = [t.id for t in series_members]

    ratings_rows: list[tuple[float, datetime, int, str]] = []
    if member_ids:
        ratings_result = await db.execute(
            select(Event.rating, Event.timestamp, Event.thread_id, Thread.title)
            .join(Thread, Event.thread_id == Thread.id)
            .where(
                Event.type == "rate",
                Event.rating.is_not(None),
                Event.thread_id.in_(member_ids),
                Thread.user_id == user_id,
            )
            .order_by(desc(Event.timestamp))
            .limit(5)
        )
        ratings_rows = list(ratings_result.all())

    effective_ratings: dict[int, float] = {}
    for rating_val, _ts, t_id, _title in ratings_rows:
        if t_id not in effective_ratings:
            effective_ratings[t_id] = rating_val

    all_ratings: list[float] = list(effective_ratings.values())
    avg_rating: float | None = None
    rated_count: int = len(all_ratings)
    if all_ratings:
        avg_rating = round(sum(all_ratings) / len(all_ratings), 2)

    recent_ratings = [
        RecentRatingEntry(
            rating=rating_val,
            rated_at=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            thread_id=t_id,
            thread_title=title,
        )
        for rating_val, ts, t_id, title in ratings_rows[:5]
    ]

    prev_issue = await _get_previous_issue(
        db, current_issue_id, thread_id, current_issue_position, effective_ratings
    )

    highest_rating: float | None = max(all_ratings) if all_ratings else None
    lowest_rating: float | None = min(all_ratings) if all_ratings else None

    return CanonicalSeriesInfo(
        identity_source="external_identity",
        average_rating=avg_rating,
        rated_count=rated_count,
        previous_issue=prev_issue,
        recent_ratings=recent_ratings,
        highest_rating=highest_rating,
        lowest_rating=lowest_rating,
    )


async def _resolve_series_identity(
    db: AsyncSession, user_id: int, thread_id: int
) -> ExternalIdentity | None:
    result = await db.execute(
        select(ExternalIdentity)
        .join(
            ThreadExternalSeriesMapping,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            ThreadExternalSeriesMapping.thread_id == thread_id,
            ThreadExternalSeriesMapping.status.in_(["confirmed", "candidate"]),
        )
        .order_by(
            ThreadExternalSeriesMapping.status.desc(),
            ThreadExternalSeriesMapping.id.asc(),
        )
        .limit(1)
    )
    identity = result.scalar_one_or_none()
    if identity is not None:
        return identity

    all_thread_result = await db.execute(
        select(Thread.id).where(Thread.user_id == user_id)
    )
    all_user_thread_ids = [row.id for row in all_thread_result]

    if not all_user_thread_ids:
        return None

    identity_result = await db.execute(
        select(ExternalIdentity)
        .join(
            ThreadExternalSeriesMapping,
            ExternalIdentity.id == ThreadExternalSeriesMapping.external_identity_id,
        )
        .where(
            ThreadExternalSeriesMapping.thread_id.in_(all_user_thread_ids),
            ThreadExternalSeriesMapping.status == "confirmed",
        )
        .limit(1)
    )
    return identity_result.scalar_one_or_none()


async def _get_series_threads(
    db: AsyncSession, user_id: int, external_id: str
) -> list[Thread]:
    result = await db.execute(
        select(Thread)
        .join(
            ThreadExternalSeriesMapping,
            Thread.id == ThreadExternalSeriesMapping.thread_id,
        )
        .join(
            ExternalIdentity,
            ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            Thread.user_id == user_id,
            ExternalIdentity.external_id == external_id,
        )
    )
    return list(result.scalars().unique().all())


async def _get_previous_issue(
    db: AsyncSession,
    current_issue_id: int,
    thread_id: int,
    current_position: int,
    effective_ratings: dict[int, float],
) -> PreviousIssueInfo | None:
    prev_result = await db.execute(
        select(Issue)
        .options(selectinload(Issue.thread))
        .where(
            Issue.thread_id == thread_id,
            Issue.id != current_issue_id,
            Issue.position < current_position,
        )
        .order_by(Issue.position.desc())
        .limit(1)
    )
    prev_issue: Issue | None = prev_result.scalar_one_or_none()
    if prev_issue is None:
        return None

    prev_effective_rating: float | None = effective_ratings.get(prev_issue.thread_id)
    return PreviousIssueInfo(
        issue_id=prev_issue.id,
        issue_number=prev_issue.issue_number,
        thread_id=prev_issue.thread_id,
        thread_title=prev_issue.thread.title,
        effective_rating=prev_effective_rating,
        is_read=prev_issue.status == "read",
    )


async def _build_crossover_panel(
    db: AsyncSession,
    user_id: int,
    applicable_group_ids: set[int],
    current_thread_id: int,
    current_issue_id: int,
    current_issue_number: str,
) -> list[CrossoverAnalyticsInfo]:
    if not applicable_group_ids:
        return []

    panel: list[CrossoverAnalyticsInfo] = []

    for group_id in sorted(applicable_group_ids):
        memberships_result = await db.execute(
            select(DependencyGroupMembership)
            .options(selectinload(DependencyGroupMembership.group))
            .where(
                DependencyGroupMembership.group_id == group_id,
                (
                    (DependencyGroupMembership.thread_id == current_thread_id)
                    | (DependencyGroupMembership.issue_id == current_issue_id)
                ),
            )
        )
        memberships = list(memberships_result.scalars().unique().all())
        if not memberships:
            continue

        group_name: str = memberships[0].group.name

        node_thread_ids: set[int] = set()
        node_issue_ids: set[int] = set()
        for ms in memberships:
            if ms.thread_id is not None:
                node_thread_ids.add(ms.thread_id)
            if ms.issue_id is not None:
                node_issue_ids.add(ms.issue_id)

        nodes: list[CrossoverNodeInfo] = []
        thread_rows: dict[int, str] = {}
        issue_rows: dict[int, tuple[str, int, str]] = {}

        if node_thread_ids:
            threads_result = await db.execute(
                select(Thread.id, Thread.title).where(
                    Thread.id.in_(list(node_thread_ids))
                )
            )
            thread_rows = {row.id: row.title for row in threads_result}

        if node_issue_ids:
            issues_result = await db.execute(
                select(Issue.id, Issue.issue_number, Issue.thread_id, Issue.status)
                .where(Issue.id.in_(list(node_issue_ids)))
            )
            issue_rows = {
                row.id: (row.issue_number, row.thread_id, row.status)
                for row in issues_result
            }

        for ms in memberships:
            if ms.thread_id is not None:
                thread_title_val = (
                    thread_rows.get(ms.thread_id) if node_thread_ids else None
                )
                nodes.append(
                    CrossoverNodeInfo(
                        node_type="thread",
                        node_id=ms.id,
                        thread_id=ms.thread_id,
                        thread_title=thread_title_val,
                        is_read=False,
                    )
                )
            elif ms.issue_id is not None and node_issue_ids:
                issue_data = issue_rows.get(ms.issue_id)
                if issue_data:
                    issue_number_val, parent_thread_id, issue_status = issue_data
                    parent_thread_title = (
                        thread_rows.get(parent_thread_id) if node_thread_ids else None
                    ) or ""
                    nodes.append(
                        CrossoverNodeInfo(
                            node_type="issue",
                            node_id=ms.id,
                            thread_id=parent_thread_id,
                            issue_id=ms.issue_id,
                            issue_number=issue_number_val,
                            thread_title=parent_thread_title,
                            is_read=issue_status == "read",
                        )
                    )

        all_node_thread_ids = {node.thread_id for node in nodes if node.thread_id is not None}

        rated_count = 0
        ratings_sum = 0.0
        if all_node_thread_ids:
            ratings_result = await db.execute(
                select(func.avg(func.nullif(Event.rating, None)))
                .select_from(Event)
                .join(Thread, Event.thread_id == Thread.id)
                .where(
                    Event.type == "rate",
                    Event.thread_id.in_(list(all_node_thread_ids)),
                    Thread.user_id == user_id,
                )
            )
            avg_val = ratings_result.scalar()
            if avg_val is not None:
                rated_count_result = await db.execute(
                    select(func.count(func.distinct(Event.thread_id)))
                    .select_from(Event)
                    .join(Thread, Event.thread_id == Thread.id)
                    .where(
                        Event.type == "rate",
                        Event.thread_id.in_(list(all_node_thread_ids)),
                        Thread.user_id == user_id,
                    )
                )
                rated_count = rated_count_result.scalar() or 0
                ratings_sum = avg_val

        avg_rating: float | None = None
        if rated_count > 0:
            avg_rating = round(float(ratings_sum), 2)

        read_count = sum(1 for node in nodes if node.is_read)

        panel.append(
            CrossoverAnalyticsInfo(
                group_id=group_id,
                group_name=group_name,
                average_rating=avg_rating,
                rated_count=rated_count,
                read_count=read_count,
                node_count=len(nodes),
                nodes=nodes,
            )
        )

    return panel
