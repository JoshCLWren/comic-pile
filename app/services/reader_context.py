"""Bounded reader-context aggregation for the active Roll issue.

The reader-context endpoint is decorative: it gives the Roll experience one
bounded, authenticated payload covering canonical-series analytics, exact
crossover membership, and the local reading neighborhood. Every query stays
scoped to owned rows and bounded collections so cost does not grow with the
user's full library.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.schemas.reader_context import (
    ReaderContextCrossover,
    ReaderContextCrossoverMembership,
    ReaderContextCrossoverNextMember,
    ReaderContextEdge,
    ReaderContextLocalChain,
    ReaderContextLocalIssue,
    ReaderContextPreviousIssue,
    ReaderContextRecentRating,
    ReaderContextResponse,
    ReaderContextSeries,
)
from app.services.ownership import get_owned_issue_or_404

COMICVINE_PROVIDER = "comicvine"
MAX_RECENT_RATINGS = 5
MAX_CHAIN_EDGES = 20


def _integer(value: object) -> int | None:
    """Coerce a numeric provider value to an int.

    Args:
        value: The raw provider value.

    Returns:
        The integer value, or ``None`` when not numeric.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _string(value: object) -> str | None:
    """Coerce a provider value to a trimmed non-empty string.

    Args:
        value: The raw provider value.

    Returns:
        The trimmed string, or ``None`` when empty or not a string.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _series(metadata: dict[str, object]) -> tuple[int | None, str | None]:
    """Extract the canonical ComicVine series/volume id and name.

    Args:
        metadata: Confirmed ComicVine issue identity metadata.

    Returns:
        The canonical series id and name, either may be ``None``.
    """
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        return _integer(volume.get("id")), _string(volume.get("name"))
    return _integer(metadata.get("volume_id")), _string(metadata.get("volume_name"))


async def _confirmed_identity(db: AsyncSession, issue_id: int) -> ExternalIdentity | None:
    """Return the confirmed ComicVine issue identity for an owned issue.

    Args:
        db: Async database session.
        issue_id: ComicPile issue identifier.

    Returns:
        The confirmed identity, or ``None`` when absent.
    """
    result = await db.execute(
        select(ExternalIdentity)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "issue",
        )
        .order_by(
            IssueExternalIdentityMapping.confidence.desc().nullslast(),
            ExternalIdentity.id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _same_series_read_issues(
    db: AsyncSession,
    user_id: int,
    series_id: int,
) -> list[Issue]:
    """Return the user's read issues confirmed to the same canonical series.

    Args:
        db: Async database session.
        user_id: Issue owner.
        series_id: Canonical ComicVine volume id.

    Returns:
        The user's currently-read issues confirmed to the given series.
    """
    result = await db.execute(
        text(
            """
            SELECT DISTINCT i.id, i.issue_number, i.position, i.status, i.thread_id
            FROM issues i
            JOIN threads t ON t.id = i.thread_id AND t.user_id = :user_id
            JOIN issue_external_identity_mappings iem
              ON iem.issue_id = i.id AND iem.status = 'confirmed'
            JOIN external_identities ei
              ON ei.id = iem.external_identity_id
             AND ei.provider = :provider
             AND ei.entity_type = 'issue'
            WHERE i.status = 'read'
              AND (
                  ei.metadata_json::jsonb @> CAST(:volume_shape AS jsonb)
                  OR ei.metadata_json::jsonb @> CAST(:volume_id_shape AS jsonb)
              )
            ORDER BY i.id
            """
        ),
        {
            "user_id": user_id,
            "provider": COMICVINE_PROVIDER,
            "volume_shape": json.dumps({"volume": {"id": series_id}}),
            "volume_id_shape": json.dumps({"volume_id": series_id}),
        },
    )
    return [
        Issue(
            id=int(row["id"]),
            issue_number=str(row["issue_number"]),
            position=int(row["position"]),
            status=str(row["status"]),
            thread_id=int(row["thread_id"]),
        )
        for row in result.mappings()
    ]


async def _effective_ratings(
    db: AsyncSession,
    issue_ids: set[int],
) -> dict[int, tuple[float, datetime]]:
    """Map each issue to its latest effective rating and event timestamp.

    Multiple rate events for one issue count once: the latest event wins.

    Args:
        db: Async database session.
        issue_ids: Issues whose effective ratings are needed.

    Returns:
        Mapping of issue id to ``(rating, timestamp)`` of its latest rate event.
    """
    if not issue_ids:
        return {}
    result = await db.execute(
        select(Event.issue_id, Event.rating, Event.timestamp)
        .where(
            Event.type == "rate",
            Event.issue_id.in_(issue_ids),
            Event.rating.isnot(None),
        )
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
    )
    effective: dict[int, tuple[float, datetime]] = {}
    for issue_id, rating, timestamp in result.all():
        if issue_id is not None and issue_id not in effective:
            effective[int(issue_id)] = (float(rating), timestamp)
    return effective


async def _relevant_crossover_groups(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
) -> list[DependencyGroup]:
    """Return owned crossover groups touching the requested issue's thread.

    Thread-level membership alone is never treated as current-issue
    membership; relevance here only determines which owned groups to present.

    Args:
        db: Async database session.
        user_id: Group owner.
        thread_id: Current thread used to bound relevance.

    Returns:
        Deterministically ordered relevant crossover groups.
    """
    result = await db.execute(
        select(DependencyGroup)
        .join(DependencyGroupMembership, DependencyGroupMembership.group_id == DependencyGroup.id)
        .where(
            DependencyGroup.user_id == user_id,
            or_(
                DependencyGroupMembership.thread_id == thread_id,
                and_(
                    DependencyGroupMembership.issue_id.isnot(None),
                    DependencyGroupMembership.issue_id.in_(
                        select(Issue.id).where(Issue.thread_id == thread_id)
                    ),
                ),
            ),
        )
        .distinct()
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    return list(result.scalars())


async def _group_exact_members(
    db: AsyncSession,
    user_id: int,
    group_ids: list[int],
) -> dict[int, list[Issue]]:
    """Load every owned exact issue member of the requested groups.

    Args:
        db: Async database session.
        user_id: Issue owner.
        group_ids: Relevant group identifiers.

    Returns:
        Mapping of group id to its owned exact member issues.
    """
    if not group_ids:
        return {}
    result = await db.execute(
        select(DependencyGroupMembership.group_id, Issue)
        .join(Issue, Issue.id == DependencyGroupMembership.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(
            DependencyGroupMembership.group_id.in_(group_ids),
            DependencyGroupMembership.issue_id.isnot(None),
            Thread.user_id == user_id,
        )
        .order_by(DependencyGroupMembership.group_id, Issue.id)
    )
    members: dict[int, list[Issue]] = {}
    for group_id, member in result.all():
        members.setdefault(int(group_id), []).append(member)
    return members


def _build_series(
    *,
    identity_source: str,
    series_id: int | None,
    series_name: str | None,
    series_issues: list[Issue],
    previous_issue: Issue | None,
    effective: dict[int, tuple[float, datetime]],
) -> ReaderContextSeries:
    """Assemble canonical-series analytics from the effective rating set.

    Args:
        identity_source: Whether canonical ComicVine identity is available.
        series_id: Canonical series id, when available.
        series_name: Canonical series name, when available.
        series_issues: Currently-read issues confirmed to the series.
        previous_issue: Immediately preceding issue in the thread.
        effective: Effective ratings for relevant owned issues.

    Returns:
        The canonical-series analytics block.
    """
    ratings = [
        (candidate, effective[candidate.id])
        for candidate in series_issues
        if candidate.id in effective
    ]
    if ratings:
        average_rating = round(
            sum(candidate_rating for _candidate, (candidate_rating, _timestamp) in ratings)
            / len(ratings),
            2,
        )
        recent = sorted(
            ratings,
            key=lambda item: (item[1][1], item[0].id),
            reverse=True,
        )[:MAX_RECENT_RATINGS]
        highest_rating = max(
            candidate_rating for _candidate, (candidate_rating, _timestamp) in ratings
        )
        lowest_rating = min(
            candidate_rating for _candidate, (candidate_rating, _timestamp) in ratings
        )
    else:
        average_rating = None
        recent = []
        highest_rating = None
        lowest_rating = None

    previous: ReaderContextPreviousIssue | None = None
    if previous_issue is not None:
        previous_rating = (
            effective[previous_issue.id][0] if previous_issue.id in effective else None
        )
        previous = ReaderContextPreviousIssue(
            issue_id=previous_issue.id,
            issue_number=previous_issue.issue_number,
            rating=previous_rating,
        )

    return ReaderContextSeries(
        identity_source=identity_source,
        canonical_series_id=str(series_id) if series_id is not None else None,
        series_name=series_name,
        average_rating=average_rating,
        ratings_count=len(ratings),
        previous_issue=previous,
        recent_ratings=[
            ReaderContextRecentRating(
                issue_id=candidate.id,
                issue_number=candidate.issue_number,
                rating=rating,
            )
            for candidate, (rating, _timestamp) in recent
        ],
        highest_rating=highest_rating,
        lowest_rating=lowest_rating,
    )


def _build_crossovers(
    *,
    groups: list[DependencyGroup],
    members_by_group: dict[int, list[Issue]],
    current_issue_id: int,
    current_position: int,
    thread_id: int,
    effective: dict[int, tuple[float, datetime]],
) -> list[ReaderContextCrossover]:
    """Assemble crossover blocks for relevant owned groups.

    Args:
        groups: Deterministically ordered relevant groups.
        members_by_group: Exact owned member issues per group.
        current_issue_id: Requested issue identifier.
        current_position: Requested issue position inside the thread.
        thread_id: Requested issue's thread.
        effective: Effective ratings for relevant owned issues.

    Returns:
        Bounded crossover analytics blocks.
    """
    crossovers: list[ReaderContextCrossover] = []
    for group in groups:
        members = members_by_group.get(group.id, [])
        member_ratings = [
            effective[member.id] for member in members if member.id in effective
        ]
        average_rating = (
            round(sum(rating for rating, _timestamp in member_ratings) / len(member_ratings), 2)
            if member_ratings
            else None
        )
        read_count = sum(1 for member in members if member.status == "read")
        same_thread_future = [
            member
            for member in members
            if member.thread_id == thread_id and member.position > current_position
        ]
        next_member: ReaderContextCrossoverNextMember | None = None
        if same_thread_future:
            nearest = min(same_thread_future, key=lambda member: (member.position, member.id))
            next_member = ReaderContextCrossoverNextMember(
                issue_id=nearest.id,
                issue_number=nearest.issue_number,
            )
        member_ids = {member.id for member in members}
        crossovers.append(
            ReaderContextCrossover(
                id=group.id,
                name=group.name,
                applies_to_current_issue=current_issue_id in member_ids,
                next_member=next_member,
                average_rating=average_rating,
                ratings_count=len(member_ratings),
                read_count=read_count,
            )
        )
    return crossovers


def _build_local_issues(
    *,
    neighborhood: list[Issue],
    current_issue_id: int,
    current_position: int,
    groups: list[DependencyGroup],
    members_by_group: dict[int, list[Issue]],
    effective: dict[int, tuple[float, datetime]],
) -> list[ReaderContextLocalIssue]:
    """Assemble the bounded local-chain issue blocks.

    Args:
        neighborhood: Up to five thread issues centered on the requested issue.
        current_issue_id: Requested issue identifier.
        current_position: Requested issue position inside the thread.
        groups: Deterministically ordered relevant groups.
        members_by_group: Exact owned member issues per group.
        effective: Effective ratings for relevant owned issues.

    Returns:
        Bounded, position-ordered local-chain issues.
    """
    issues: list[ReaderContextLocalIssue] = []
    for candidate in neighborhood:
        if candidate.position < current_position:
            relation = "previous"
        elif candidate.position == current_position:
            relation = "current"
        elif candidate.position == current_position + 1:
            relation = "next"
        else:
            relation = "future"
        memberships = [
            ReaderContextCrossoverMembership(id=group.id, name=group.name)
            for group in groups
            if candidate.id in {member.id for member in members_by_group.get(group.id, [])}
        ]
        rating = effective[candidate.id][0] if candidate.id in effective else None
        issues.append(
            ReaderContextLocalIssue(
                issue_id=candidate.id,
                issue_number=candidate.issue_number,
                position=candidate.position,
                status=candidate.status,
                relation=relation,
                rating=rating,
                crossover_memberships=memberships,
            )
        )
    return issues


async def _local_edges(
    db: AsyncSession,
    neighborhood_ids: set[int],
) -> list[ReaderContextEdge]:
    """Load bounded one-hop dependency/continuity edges touching the neighborhood.

    Continuity rules mirrored from legacy dependencies are excluded so each
    persisted edge is represented exactly once. Edges are deterministically
    ordered and capped.

    Args:
        db: Async database session.
        neighborhood_ids: Local-chain issue identifiers.

    Returns:
        At most 20 deterministically ordered one-hop edges.
    """
    if not neighborhood_ids:
        return []
    dependency_result = await db.execute(
        select(Dependency).where(
            or_(
                Dependency.source_issue_id.in_(neighborhood_ids),
                Dependency.target_issue_id.in_(neighborhood_ids),
            )
        )
    )
    rule_result = await db.execute(
        select(ContinuityRule).where(
            ContinuityRule.legacy_dependency_id.is_(None),
            ContinuityRule.source_type == "issue",
            ContinuityRule.target_type == "issue",
            or_(
                ContinuityRule.source_id.in_(neighborhood_ids),
                ContinuityRule.target_id.in_(neighborhood_ids),
            ),
        )
    )
    edges: list[ReaderContextEdge] = [
        ReaderContextEdge(
            id=dependency.id,
            kind="dependency",
            source_issue_id=dependency.source_issue_id,
            target_issue_id=dependency.target_issue_id,
            note=dependency.note,
        )
        for dependency in dependency_result.scalars()
    ]
    edges.extend(
        ReaderContextEdge(
            id=rule.id,
            kind="continuity",
            source_issue_id=rule.source_id,
            target_issue_id=rule.target_id,
            note=rule.note,
        )
        for rule in rule_result.scalars()
    )
    edges.sort(key=lambda edge: (edge.kind, edge.id))
    return edges[:MAX_CHAIN_EDGES]


async def get_reader_context(
    db: AsyncSession,
    user_id: int,
    issue_id: int,
) -> ReaderContextResponse:
    """Build the bounded reader-context payload for one owned issue.

    Args:
        db: Async database session.
        user_id: Authenticated owner of the requested issue.
        issue_id: ComicPile issue identifier.

    Returns:
        The bounded reader-context response.

    Raises:
        HTTPException: When the issue does not belong to the user.
    """
    issue = await get_owned_issue_or_404(db, user_id, issue_id)
    thread_id = issue.thread_id
    current_position = issue.position

    thread_issues_result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position, Issue.id)
    )
    thread_issues = list(thread_issues_result.scalars())
    ordered_issues = sorted(thread_issues, key=lambda candidate: (candidate.position, candidate.id))
    current_index = next(
        index for index, candidate in enumerate(ordered_issues) if candidate.id == issue_id
    )
    previous_issue = ordered_issues[current_index - 1] if current_index > 0 else None
    neighborhood = ordered_issues[max(0, current_index - 2) : current_index + 3]

    identity = await _confirmed_identity(db, issue_id)
    series_id, series_name = _series(identity.metadata_json) if identity else (None, None)
    if identity is not None and series_id is not None:
        identity_source = "comicvine"
        series_issues = await _same_series_read_issues(db, user_id, series_id)
    else:
        identity_source = "unavailable"
        series_issues = []

    groups = await _relevant_crossover_groups(db, user_id, thread_id)
    members_by_group = await _group_exact_members(
        db,
        user_id,
        [group.id for group in groups],
    )

    rating_issue_ids = {candidate.id for candidate in series_issues}
    rating_issue_ids.update(candidate.id for candidate in neighborhood)
    if previous_issue is not None:
        rating_issue_ids.add(previous_issue.id)
    for members in members_by_group.values():
        rating_issue_ids.update(member.id for member in members)
    effective = await _effective_ratings(db, rating_issue_ids)

    series = _build_series(
        identity_source=identity_source,
        series_id=series_id,
        series_name=series_name,
        series_issues=series_issues,
        previous_issue=previous_issue,
        effective=effective,
    )
    crossovers = _build_crossovers(
        groups=groups,
        members_by_group=members_by_group,
        current_issue_id=issue_id,
        current_position=current_position,
        thread_id=thread_id,
        effective=effective,
    )
    local_issues = _build_local_issues(
        neighborhood=neighborhood,
        current_issue_id=issue_id,
        current_position=current_position,
        groups=groups,
        members_by_group=members_by_group,
        effective=effective,
    )
    edges = await _local_edges(db, {candidate.id for candidate in neighborhood})

    return ReaderContextResponse(
        issue_id=issue_id,
        series=series,
        crossovers=crossovers,
        local_chain=ReaderContextLocalChain(issues=local_issues, edges=edges),
    )