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

from app.constants import MIN_RATED_FOR_RELIABLE, MIN_RATED_ISSUES_PER_SERIES
from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread

COMICVINE_PROVIDER = "comicvine"

# Maximum number of creators allowed in a single comparison request
MAX_COMPARISON_CREATORS = 4
MIN_COMPARISON_CREATORS = 2

# Maximum series aggregates to return per creator
MAX_SERIES_AGGREGATES = 5


@dataclass(frozen=True)
class CreatorCredit:
    """One deduplicated creator credit extracted from confirmed issue metadata."""

    external_id: int
    roles: tuple[str, ...] = field(default_factory=tuple)
    display_name: str = ""


@dataclass(frozen=True)
class OwnedIssueThread:
    """Stable local series/run identity attached to one owned issue.

    One thread is one series or one creator run in the reader's own library
    (``#3088``). The title is carried for display only and is never a grouping
    identity. ``issue_number`` is carried so bounded drilldown references
    (``#3174``) can label each issue without a further query.
    """

    thread_id: int
    thread_title: str
    issue_number: str = ""


@dataclass(frozen=True)
class CreatorComparisonInputs:
    """Plain, user-scoped inputs for the creator comparison aggregation.

    ``issues_with_creator_metadata`` deliberately reflects *every* owned issue
    carrying at least one usable confirmed creator credit, exactly like the
    shared ``#2028`` summary inputs. Coverage describes the whole owned library,
    not just the compared subset: a rated issue whose confirmed credits name
    only creators outside the current selection is still fully attributed and
    must never be reported as missing metadata.
    """

    owned_issues: dict[int, str] = field(default_factory=dict)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = field(default_factory=dict)
    issues_with_creator_metadata: frozenset[int] = field(default_factory=frozenset)
    effective_ratings: dict[int, float] = field(default_factory=dict)
    requested_creator_ids: frozenset[int] = field(default_factory=frozenset)
    owned_issue_threads: dict[int, OwnedIssueThread] = field(default_factory=dict)


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

    1. the authenticated user's owned issues, their read/unread status, and
       their stable local thread/series identity;
    2. confirmed ComicVine issue metadata for those issues (creator credits);
    3. the latest effective ``rate`` event rating per owned issue.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.
        requested_creator_ids: Set of external person IDs to compare.

    Returns:
        User-scoped :class:`CreatorComparisonInputs`.
    """
    # 1. Owned issues, statuses, and stable local series identity.
    issue_result = await db.execute(
        select(Issue.id, Issue.status, Issue.thread_id, Thread.title, Issue.issue_number)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
    )
    owned_issues: dict[int, str] = {}
    owned_issue_threads: dict[int, OwnedIssueThread] = {}
    for issue_id, status, thread_id, thread_title, issue_number in issue_result.all():
        owned_issue_id = int(issue_id)
        owned_issues[owned_issue_id] = str(status)
        owned_issue_threads[owned_issue_id] = OwnedIssueThread(
            thread_id=int(thread_id),
            thread_title=str(thread_title),
            issue_number=str(issue_number),
        )

    # 2. Confirmed creator credits per owned issue.
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
        # Coverage follows the shared #2028 semantics: any usable confirmed
        # credit marks the issue as attributed, even when the credited creators
        # are all outside this comparison's selection.
        if credits:
            issues_with_creator_metadata.add(owned_issue_id)
        by_key = per_issue_credits.setdefault(owned_issue_id, {})
        for credit in credits:
            if credit.external_id in requested_creator_ids:
                by_key.setdefault((credit.external_id, credit.roles), credit)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = {
        issue_id: tuple(
            sorted(by_key.values(), key=lambda credit: (credit.external_id, credit.roles))
        )
        for issue_id, by_key in per_issue_credits.items()
        if by_key
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
        owned_issue_threads=owned_issue_threads,
    )


def build_series_aggregates(
    owned_issue_threads: dict[int, OwnedIssueThread],
    creator_issue_ids: frozenset[int],
    effective_ratings: dict[int, float],
    limit: int = MAX_SERIES_AGGREGATES,
) -> list[tuple[int, str, int, int, float]]:
    """Build strongest series/thread aggregates for a creator's issues.

    Series averages use the latest effective rating per issue (shared
    ``#2028``/``#2037`` semantics): an issue re-rated later contributes its
    current rating once, never the mean of its rating history.

    ``#3173`` makes the ranking match the "Strongest series" label: rating
    strength is the primary ordering key, and a series must reach
    ``MIN_RATED_ISSUES_PER_SERIES`` rated issues before it can be ranked at
    all. Series below that sample are excluded rather than ranked on a thin
    average, which is what previously let one lucky 5* issue outrank a long,
    consistently strong run.

    The aggregates are derived from the already-loaded user-scoped inputs, so
    every creator in one bounded batch is served without any further query.

    Args:
        owned_issue_threads: Mapping of owned issue id to its local thread.
        creator_issue_ids: Owned issue ids attributed to the creator.
        effective_ratings: Latest effective rating per owned issue.
        limit: Maximum aggregates returned.

    Returns:
        List of ``(thread_id, thread_title, issue_count, rated_issue_count, average_rating)``
        ordered by average_rating desc, then issue_count desc, then
        case-insensitive title and stable thread id. Only series with at least
        ``MIN_RATED_ISSUES_PER_SERIES`` rated issues are included, so every
        returned average is non-null.
    """
    if not creator_issue_ids:
        return []

    titles: dict[int, str] = {}
    thread_issues: dict[int, list[int]] = {}
    for issue_id in creator_issue_ids:
        owned_thread = owned_issue_threads.get(issue_id)
        if owned_thread is None:
            continue
        titles.setdefault(owned_thread.thread_id, owned_thread.thread_title)
        thread_issues.setdefault(owned_thread.thread_id, []).append(issue_id)

    aggregates: list[tuple[int, str, int, int, float]] = []
    for thread_id_int, issue_ids in thread_issues.items():
        ratings = [
            effective_ratings[issue_id] for issue_id in issue_ids if issue_id in effective_ratings
        ]
        if len(ratings) < MIN_RATED_ISSUES_PER_SERIES:
            # Documented minimum-sample exclusion (#3173). A thinner series is
            # omitted entirely rather than ranked on an unreliable average.
            continue
        aggregates.append(
            (
                thread_id_int,
                titles[thread_id_int],
                len(issue_ids),
                len(ratings),
                round(sum(ratings) / len(ratings), 2),
            )
        )

    aggregates.sort(
        key=lambda aggregate: (
            -aggregate[4],
            -aggregate[2],
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
    "MIN_RATED_ISSUES_PER_SERIES",
    "MAX_SERIES_AGGREGATES",
    "OwnedIssueThread",
    "build_series_aggregates",
    "extract_creator_credits",
    "load_creator_comparison_inputs",
]
