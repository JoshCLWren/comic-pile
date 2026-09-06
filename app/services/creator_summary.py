"""Bounded personal creator summary service (issue #2028).

Builds per-creator reading summaries for the Roll issue card from the reader's
own issues and the creator credits confirmed via ComicVine identity metadata
(issue #2036). The service performs a fixed, user-library-bounded number of
repository queries regardless of how many creator keys are requested and
aggregates in memory, so a single request covers every creator on an issue.

Headline statistics (``average_rating`` / ``ratings_count``) count only
issues where the creator carries at least one headline story-artist role.
Cover and editorial credits never gate headline stats, and unknown provider
role strings remain unclassified rather than guessed. ``read_unrated_count``
and ``upcoming_count`` count any confirmed attribution (including cover
credits). Coverage is computed once per request over the reader's owned issue
universes so lower-bound results stop masquerading as exact ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import creator_summary as creator_summary_repository
from app.schemas.creator_summary import (
    CreatorChapterCoverage,
    CreatorSummaryCoverage,
    CreatorSummaryOutput,
    CreatorSummaryResponse,
)

# Headline story-artist roles that gate reading-average statistics. Cover and
# editorial credits never gate headline stats, and unknown provider role
# strings stay unclassified rather than guessed. Raw role strings are
# lowercased and comma-split before comparison.
HEADLINE_ROLES = frozenset(
    {
        "writer",
        "script",
        "story",
        "artist",
        "penciller",
        "penciler",
        "inker",
        "colorist",
        "letterer",
    }
)


@dataclass(frozen=True)
class _CreatorCredit:
    """One usable creator credit extracted from confirmed issue metadata."""

    creator_id: int
    name: str
    roles: tuple[str, ...]


@dataclass
class _CreatorAggregate:
    """Accumulated reading evidence for one canonical creator."""

    display_name: str
    roles: list[str] = field(default_factory=list)
    headline_ratings: list[float] = field(default_factory=list)
    read_unrated_count: int = 0
    upcoming_count: int = 0


def creator_key(creator_id: int) -> str:
    """Return the canonical creator summary key for a provider creator id.

    Args:
        creator_id: ComicVine provider person id (issue #2036 identity).

    Returns:
        The stable ``creator:<id>`` key used by the summary API.
    """
    return f"creator:{creator_id}"


def _split_roles(role_value: str) -> list[str]:
    """Split a raw comma-joined provider role string into normalized roles.

    Args:
        role_value: Raw provider role string (e.g. ``"writer, cover"``).

    Returns:
        Trimmed, lowercased, non-empty role segments in encounter order.
    """
    roles: list[str] = []
    for part in role_value.split(","):
        normalized = part.strip().lower()
        if normalized:
            roles.append(normalized)
    return roles


def _is_headline_role(roles: tuple[str, ...]) -> bool:
    """Return whether any normalized role is a headline story-artist role.

    Args:
        roles: Normalized roles for one creator on one issue.

    Returns:
        True when at least one role is a known headline role.
    """
    return any(role in HEADLINE_ROLES for role in roles)


def _extract_credits(
    metadata: dict[str, object] | None,
) -> list[_CreatorCredit]:
    """Extract usable creator credits from one confirmed metadata document.

    A credit is usable only when it carries a numeric provider creator id and
    a non-empty display name; credits without a stable id cannot be addressed
    by the analytics identity (issue #2036).

    Args:
        metadata: Confirmed ComicVine issue metadata, or ``None``.

    Returns:
        Usable creator credits found in the metadata.
    """
    credits: list[_CreatorCredit] = []
    if not isinstance(metadata, dict):
        return credits
    raw_credits = metadata.get("creator_credits")
    if not isinstance(raw_credits, list):
        raw_credits = metadata.get("person_credits")
    if not isinstance(raw_credits, list):
        return credits
    for raw in raw_credits:
        if not isinstance(raw, dict):
            continue
        creator_id = raw.get("id")
        name = raw.get("name")
        if not isinstance(creator_id, int) or not isinstance(name, str):
            continue
        if not name.strip():
            continue
        role_value = raw.get("role")
        role = role_value if isinstance(role_value, str) else ""
        credits.append(
            _CreatorCredit(
                creator_id=creator_id,
                name=name.strip(),
                roles=tuple(_split_roles(role)),
            )
        )
    return credits


def _merge_credit(
    existing: _CreatorCredit | None, incoming: _CreatorCredit
) -> _CreatorCredit:
    """Merge one credit into the per-issue set for the same creator.

    Consolidates roles so a creator credited more than once on one issue (for
    example with ``"writer"`` and ``"cover"`` roles) is counted exactly once.

    Args:
        existing: Previously merged credit for the same creator, or ``None``.
        incoming: New credit to merge in.

    Returns:
        The merged credit with deduplicated roles in encounter order.
    """
    if existing is None:
        return incoming
    merged_roles: list[str] = []
    for role in existing.roles + incoming.roles:
        if role not in merged_roles:
            merged_roles.append(role)
    return _CreatorCredit(
        creator_id=incoming.creator_id,
        name=existing.name or incoming.name,
        roles=tuple(merged_roles),
    )


async def summarize_creators(
    db: AsyncSession, *, user_id: int, keys: list[str]
) -> CreatorSummaryResponse:
    """Return per-key creator summaries and library-wide coverage.

    Args:
        db: Async database session.
        user_id: Authenticated reader id.
        keys: Canonical creator keys requested, in order.

    Returns:
        One summary per requested key (empty rows for keys with no attributable
        library evidence) plus a single coverage block.
    """
    thread_ids = await creator_summary_repository.list_user_thread_ids(
        db, user_id=user_id
    )
    rows = await creator_summary_repository.list_issues_with_creator_metadata(
        db, thread_ids=thread_ids
    )

    issue_ids = {issue_id for issue_id, _, _ in rows}
    ratings = await creator_summary_repository.load_effective_ratings(
        db, issue_ids=issue_ids
    )

    issue_status: dict[int, str] = {}
    issue_credits: dict[int, dict[int, _CreatorCredit]] = {}
    issue_usable: dict[int, bool] = {}
    for issue_id, status, metadata in rows:
        issue_status.setdefault(issue_id, status)
        credits = _extract_credits(metadata)
        if credits:
            issue_usable[issue_id] = True
        merged = issue_credits.setdefault(issue_id, {})
        for credit in credits:
            merged[credit.creator_id] = _merge_credit(
                merged.get(credit.creator_id), credit
            )

    rated_total = 0
    rated_metadata = 0
    read_unrated_total = 0
    read_unrated_metadata = 0
    upcoming_total = 0
    upcoming_metadata = 0

    aggregates: dict[str, _CreatorAggregate] = {}

    def _aggregate_for(key: str, name: str) -> _CreatorAggregate:
        aggregate = aggregates.get(key)
        if aggregate is None:
            aggregate = _CreatorAggregate(display_name=name)
            aggregates[key] = aggregate
        return aggregate

    for issue_id in sorted(issue_status):
        status = issue_status[issue_id]
        credits_by_id = issue_credits.get(issue_id, {})
        rating = ratings.get(issue_id)
        usable = issue_usable.get(issue_id, False)

        if rating is not None:
            rated_total += 1
            if usable:
                rated_metadata += 1
        elif status == "read":
            read_unrated_total += 1
            if usable:
                read_unrated_metadata += 1
        elif status == "unread":
            upcoming_total += 1
            if usable:
                upcoming_metadata += 1

        for credit in credits_by_id.values():
            key = creator_key(credit.creator_id)
            aggregate = _aggregate_for(key, credit.name)
            for role in credit.roles:
                if role not in aggregate.roles:
                    aggregate.roles.append(role)
            if rating is not None and _is_headline_role(credit.roles):
                aggregate.headline_ratings.append(rating)
            elif rating is None and status == "read":
                aggregate.read_unrated_count += 1
            elif rating is None and status == "unread":
                aggregate.upcoming_count += 1

    summaries: list[CreatorSummaryOutput] = []
    seen_keys: set[str] = set()
    for key in keys:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        aggregate = aggregates.get(key)
        if aggregate is None:
            summaries.append(CreatorSummaryOutput(canonical_creator_key=key))
            continue
        headline_count = len(aggregate.headline_ratings)
        average_rating: float | None = None
        if headline_count:
            average_rating = round(
                sum(aggregate.headline_ratings) / headline_count, 2
            )
        summaries.append(
            CreatorSummaryOutput(
                canonical_creator_key=key,
                display_name=aggregate.display_name,
                normalized_roles=list(aggregate.roles),
                average_rating=average_rating,
                ratings_count=headline_count,
                read_unrated_count=aggregate.read_unrated_count,
                upcoming_count=aggregate.upcoming_count,
            )
        )

    def _chapter(total: int, with_metadata: int) -> CreatorChapterCoverage:
        """Build one coverage chapter for an issue universe.

        Args:
            total: Issues in the universe.
            with_metadata: Issues with usable creator metadata.

        Returns:
            The coverage chapter for the universe.
        """
        return CreatorChapterCoverage(
            total=total,
            with_creator_metadata=with_metadata,
            complete=total == with_metadata,
        )

    coverage = CreatorSummaryCoverage(
        rated=_chapter(rated_total, rated_metadata),
        read_unrated=_chapter(read_unrated_total, read_unrated_metadata),
        upcoming=_chapter(upcoming_total, upcoming_metadata),
    )

    return CreatorSummaryResponse(
        summaries=summaries,
        coverage=coverage,
        generated_at=datetime.now(UTC),
    )


__all__ = [
    "HEADLINE_ROLES",
    "creator_key",
    "summarize_creators",
]