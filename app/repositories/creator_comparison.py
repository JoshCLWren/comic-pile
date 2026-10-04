"""Data access for the bounded personal creator comparison API (issue #3091).

This repository owns all query construction for creator comparison.
Every query is user-scoped to ensure that one user's creator data never leaks
to another user. The comparison is bounded to 2-4 creators and served by a
fixed, small number of queries regardless of library size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread

COMICVINE_PROVIDER = "comicvine"

# Maximum number of creators allowed in a single comparison request
MAX_COMPARISON_CREATORS = 4
MIN_COMPARISON_CREATORS = 2

# Minimum rated issues for reliable statistics
MIN_RATED_FOR_RELIABLE = 3

# Maximum series aggregates to return per creator
MAX_SERIES_AGGREGATES = 5


@dataclass(frozen=True)
class CreatorCredit:
    """One deduplicated creator credit extracted from confirmed issue metadata."""

    external_id: int
    roles: tuple[str, ...] = field(default_factory=tuple)
    display_name: str = ""


@dataclass(frozen=True)
class CreatorComparisonInputs:
    """Plain, user-scoped inputs for the creator comparison aggregation."""

    owned_issues: dict[int, str] = field(default_factory=dict)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = field(default_factory=dict)
    issues_with_creator_metadata: frozenset[int] = field(default_factory=frozenset)
    effective_ratings: dict[int, float] = field(default_factory=dict)
    requested_creator_ids: frozenset[int] = field(default_factory=frozenset)


def _coerce_creator_id(value: object) -> int | None:
    """Coerce a provider person id to an int when it is numeric."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def extract_creator_credits(metadata: dict[str, Any]) -> list[CreatorCredit]:
    """Extract deduplicated creator credits from confirmed issue metadata."""
    raw = metadata.get("creator_credits")
    if not isinstance(raw, list):
        return []
    credits: list[CreatorCredit] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        creator_id = _coerce_creator_id(item.get("id"))
        name = item.get("name")
        if creator_id is None or not isinstance(name, str) or not name.strip():
            continue
        role_value = item.get("role")
        roles: tuple[str, ...] = ()
        if role_value is not None:
            parsed = {part.strip() for part in str(role_value).split(",") if part.strip()}
            roles = tuple(sorted(parsed))
        dedupe = (creator_id, roles)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        credits.append(
            CreatorCredit(
                external_id=creator_id,
                roles=roles,
                display_name=name.strip(),
            )
        )
    return credits


async def load_creator_comparison_inputs(
    db: AsyncSession,
    user_id: int,
    requested_creator_ids: frozenset[int],
) -> CreatorComparisonInputs:
    """Load every user-scoped input needed for one bounded batch comparison.

    The batch is served by exactly three queries no matter how many creator
    keys are requested (max 4):

    1. the authenticated user's owned issues and their read/unread status;
    2. confirmed ComicVine issue metadata for those issues (creator credits);
    3. the latest effective ``rate`` event rating per owned issue.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.
        requested_creator_ids: Set of external person IDs to compare.

    Returns:
        User-scoped :class:`CreatorComparisonInputs`.
    """
    # 1. Owned issues and statuses.
    issue_result = await db.execute(
        select(Issue.id, Issue.status)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
    )
    owned_issues: dict[int, str] = {
        int(issue_id): str(status) for issue_id, status in issue_result.all()
    }

    # 2. Confirmed creator credits per owned issue (filtered to requested creators).
    metadata_result = await db.execute(
        select(Issue.id, ExternalIdentity.metadata_json)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(Thread.user_id == user_id)
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .where(ExternalIdentity.provider == COMICVINE_PROVIDER)
    )
    per_issue_credits: dict[int, dict[tuple[int, tuple[str, ...]], CreatorCredit]] = {}
    issues_with_creator_metadata: set[int] = set()
    for issue_id, metadata in metadata_result.all():
        if not isinstance(metadata, dict):
            continue
        credits = extract_creator_credits(metadata)
        owned_issue_id = int(issue_id)
        # Filter to only requested creator IDs
        filtered_credits = [c for c in credits if c.external_id in requested_creator_ids]
        if filtered_credits:
            issues_with_creator_metadata.add(owned_issue_id)
        by_key = per_issue_credits.setdefault(owned_issue_id, {})
        for credit in filtered_credits:
            by_key.setdefault((credit.external_id, credit.roles), credit)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = {
        issue_id: tuple(
            sorted(by_key.values(), key=lambda credit: (credit.external_id, credit.roles))
        )
        for issue_id, by_key in per_issue_credits.items()
    }

    # 3. Latest effective rating per owned issue (latest event wins).
    rate_result = await db.execute(
        select(Event.issue_id, Event.rating)
        .join(Issue, Issue.id == Event.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.issue_id.is_not(None))
        .where(Event.rating.is_not(None))
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
    )
    effective_ratings: dict[int, float] = {}
    for issue_id, rating in rate_result.all():
        if issue_id is not None and int(issue_id) not in effective_ratings:
            effective_ratings[int(issue_id)] = float(rating)

    return CreatorComparisonInputs(
        owned_issues=owned_issues,
        issue_creator_credits=issue_creator_credits,
        issues_with_creator_metadata=frozenset(issues_with_creator_metadata),
        effective_ratings=effective_ratings,
        requested_creator_ids=requested_creator_ids,
    )


async def load_series_aggregates(
    db: AsyncSession,
    user_id: int,
    creator_issue_ids: frozenset[int],
    effective_ratings: dict[int, float],
    limit: int = MAX_SERIES_AGGREGATES,
) -> list[tuple[int, str, int, float | None]]:
    """Load strongest series/thread aggregates for a creator's issues.

    Series averages use the latest effective rating per issue (shared
    #2028/#2037 semantics): an issue re-rated later contributes its current
    rating once, never the mean of its rating history.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the aggregated library.
        creator_issue_ids: Owned issue ids attributed to the creator.
        effective_ratings: Latest effective rating per owned issue.
        limit: Maximum aggregates returned.

    Returns list of (thread_id, thread_title, issue_count, average_rating)
    ordered by issue_count desc, average_rating desc (nulls last), then
    case-insensitive title and stable thread id.
    """
    if not creator_issue_ids:
        return []

    result = await db.execute(
        select(Thread.id, Thread.title, Issue.id)
        .join(Issue, Issue.thread_id == Thread.id)
        .where(Thread.user_id == user_id)
        .where(Issue.id.in_(creator_issue_ids))
    )
    titles: dict[int, str] = {}
    thread_issues: dict[int, list[int]] = {}
    for thread_id, thread_title, issue_id in result.all():
        thread_id_int = int(thread_id)
        titles.setdefault(thread_id_int, str(thread_title))
        thread_issues.setdefault(thread_id_int, []).append(int(issue_id))

    aggregates: list[tuple[int, str, int, float | None]] = []
    for thread_id_int, issue_ids in thread_issues.items():
        ratings = [
            effective_ratings[issue_id] for issue_id in issue_ids if issue_id in effective_ratings
        ]
        average = round(sum(ratings) / len(ratings), 2) if ratings else None
        aggregates.append((thread_id_int, titles[thread_id_int], len(issue_ids), average))

    aggregates.sort(
        key=lambda aggregate: (
            -aggregate[2],
            aggregate[3] is None,
            -(aggregate[3] or 0.0),
            titles[aggregate[0]].casefold(),
            titles[aggregate[0]],
            aggregate[0],
        )
    )
    return aggregates[:limit]


__all__ = [
    "COMICVINE_PROVIDER",
    "CreatorComparisonInputs",
    "CreatorCredit",
    "MAX_COMPARISON_CREATORS",
    "MIN_COMPARISON_CREATORS",
    "MIN_RATED_FOR_RELIABLE",
    "MAX_SERIES_AGGREGATES",
    "extract_creator_credits",
    "load_creator_comparison_inputs",
    "load_series_aggregates",
]