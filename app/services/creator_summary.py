"""Bounded personal creator summary aggregation (issue #2028).

This service derives the compact personal statistics Roll creator annotations
need from one authenticated batch request. Every personal aggregate is scoped
through the authenticated user's owned ComicPile issues and their confirmed
local issue metadata. No ComicVine call and no materialized/precomputed
``creator_stats`` table is involved.

Rating semantics:
- Only real ``rate`` events with a rating contribute.
- When an issue has multiple rate events, the latest event by timestamp/id is
  the effective rating.
- One issue contributes at most once to a creator's headline average/count even
  if that creator has multiple roles on the issue.

Creator-role semantics:
- One small explicit classification decides headline eligibility. Interior/story
  roles contribute to the headline average/count; pure cover/editorial credits
  never silently behave as interior/story contribution.
- Unknown provider role strings remain unknown/unclassified rather than being
  guessed into a stronger role.
- A creator with both headline-eligible and excluded roles on the same issue
  still contributes that issue only once to headline statistics.

Coverage semantics:
- Counts are only exhaustive when the relevant owned issues have confirmed
  creator metadata. Missing/unconfirmed metadata never counts as negative
  attribution evidence; it only makes the matching result explicitly partial.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_summary import (
    CreatorSummaryInputs,
    load_creator_summary_inputs,
)
from app.schemas.creator_summary import (
    CreatorSummariesResponse,
    CreatorSummaryCoverage,
    CreatorSummaryItem,
)

#: Explicit headline-eligible role classification (issue #2028). Interior/story
#: credits (writing and interior art) contribute to the headline average/count.
#: Pure cover/editorial-only credits and any unknown role string stay outside
#: the headline classification and never silently distort the interior/story
#: average. The list is intentionally small and explicit so #2037 can reuse it.
HEADLINE_ROLES: frozenset[str] = frozenset(
    {"writer", "artist", "penciler", "inker", "colorist", "letterer"}
)


@dataclass(frozen=True)
class _CreatorAggregates:
    """Personal statistics aggregated for one requested creator.

    Kept separate from :class:`CreatorSummaryItem` so the aggregation stage can
    be bounded by the requested creator ids while the response stage still
    echoes each requested key exactly as the client spelled it (issue #3387).

    Attributes:
        display_name: Provider display name first seen on a confirmed credit.
        roles: Sorted distinct normalized roles across the creator's credits.
        average_rating: Rounded headline average, or ``None`` with no ratings.
        ratings_count: Distinct headline-eligible rated issues attributed.
        read_unrated_count: Attributed read-but-unrated owned issues.
        upcoming_count: Attributed unread owned issues.
    """

    display_name: str
    roles: list[str]
    average_rating: float | None
    ratings_count: int
    read_unrated_count: int
    upcoming_count: int


def parse_creator_key(key: str) -> int | None:
    """Parse a canonical creator key into the stable external person id.

    Canonical keys are ``creator:<external-person-id>`` (issue #2036). Any
    other shape (role-scoped taste keys, display-name-derived keys, malformed
    input) parses to ``None`` and is never guessed into an identity.

    Args:
        key: Canonical serialized creator key.

    Returns:
        The stable external person id, or ``None`` for non-canonical keys.
    """
    parts = key.split(":")
    if len(parts) != 2 or parts[0] != "creator" or not parts[1].isdigit():
        return None
    return int(parts[1])


def _build_coverage(
    inputs: CreatorSummaryInputs,
    *,
    rated_issue_ids: frozenset[int],
    read_unrated_issue_ids: frozenset[int],
    unread_issue_ids: frozenset[int],
) -> CreatorSummaryCoverage:
    """Build the explicit metadata-coverage block from the owned-issue sets.

    A coverage total of zero makes the matching ``complete`` field vacuously
    true (there is nothing missing when the category is empty).

    Args:
        inputs: User-scoped aggregation inputs.
        rated_issue_ids: Owned issues with an effective rating.
        read_unrated_issue_ids: Owned read-but-unrated issues.
        unread_issue_ids: Owned unread issues.

    Returns:
        The coverage block distinguishing complete from lower-bound statistics.
    """

    def _with_metadata(issue_ids: frozenset[int]) -> int:
        return sum(1 for issue_id in issue_ids if issue_id in inputs.issues_with_creator_metadata)

    rated_total = len(rated_issue_ids)
    rated_with = _with_metadata(rated_issue_ids)
    read_unrated_total = len(read_unrated_issue_ids)
    read_unrated_with = _with_metadata(read_unrated_issue_ids)
    unread_total = len(unread_issue_ids)
    unread_with = _with_metadata(unread_issue_ids)

    return CreatorSummaryCoverage(
        rated_issues_total=rated_total,
        rated_issues_with_creator_metadata=rated_with,
        ratings_complete=rated_with >= rated_total,
        read_unrated_issues_total=read_unrated_total,
        read_unrated_issues_with_creator_metadata=read_unrated_with,
        read_unrated_complete=read_unrated_with >= read_unrated_total,
        unread_issues_total=unread_total,
        unread_issues_with_creator_metadata=unread_with,
        upcoming_complete=unread_with >= unread_total,
    )


def requested_creator_ids(requested_keys: list[str]) -> frozenset[int]:
    """Resolve the canonical creator ids a batch request can possibly return.

    A batch request names at most ``MAX_CREATOR_KEYS`` creators and only those
    can appear in the response, so the aggregation never has to build
    statistics for the rest of the library. Keys that are not canonical parse
    to nothing and are simply absent from the set, which leaves the
    silently-omitted unknown/foreign key behavior unchanged.

    Args:
        requested_keys: Bounded list of canonical creator keys from the request.

    Returns:
        The distinct stable external person ids named by canonical keys.
    """
    return frozenset(
        creator_id
        for key in requested_keys
        if (creator_id := parse_creator_key(key)) is not None
    )


def aggregate_creators(
    inputs: CreatorSummaryInputs,
    *,
    wanted_creator_ids: frozenset[int],
    read_unrated_issue_ids: frozenset[int],
    unread_issue_ids: frozenset[int],
) -> dict[int, _CreatorAggregates]:
    """Aggregate personal statistics for exactly the requested creator ids.

    A mature library can credit thousands of creators while one batch request
    names at most ``MAX_CREATOR_KEYS`` of them. Aggregating every creator and
    then discarding all but the requested ones made this stage scale with library
    size instead of with request size, so credits outside ``wanted_creator_ids``
    are skipped while they are walked rather than aggregated and filtered
    afterwards (issue #3387). The returned statistics are identical either way.

    Args:
        inputs: User-scoped aggregation inputs.
        wanted_creator_ids: Stable external person ids the request can return.
        read_unrated_issue_ids: Owned issues that are read and not rated.
        unread_issue_ids: Owned unread issues.

    Returns:
        Personal aggregates keyed by requested creator id.
    """
    creator_issues: dict[int, set[int]] = defaultdict(set)
    creator_headline_issues: dict[int, set[int]] = defaultdict(set)
    creator_roles: dict[int, set[str]] = defaultdict(set)
    creator_names: dict[int, str] = {}
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            creator_id = credit.external_id
            if creator_id not in wanted_creator_ids:
                continue
            creator_issues[creator_id].add(issue_id)
            creator_names.setdefault(creator_id, credit.display_name)
            creator_roles[creator_id].update(credit.roles)
            if any(role in HEADLINE_ROLES for role in credit.roles):
                creator_headline_issues[creator_id].add(issue_id)

    creator_stats: dict[int, _CreatorAggregates] = {}
    for creator_id, issue_ids in creator_issues.items():
        headline_ratings = [
            inputs.effective_ratings[issue_id]
            for issue_id in issue_ids
            if issue_id in creator_headline_issues[creator_id]
            and issue_id in inputs.effective_ratings
        ]
        ratings_count = len(headline_ratings)
        creator_stats[creator_id] = _CreatorAggregates(
            display_name=creator_names[creator_id],
            roles=sorted(creator_roles[creator_id]),
            average_rating=(
                round(sum(headline_ratings) / ratings_count, 2) if ratings_count else None
            ),
            ratings_count=ratings_count,
            read_unrated_count=sum(
                1 for issue_id in issue_ids if issue_id in read_unrated_issue_ids
            ),
            upcoming_count=sum(1 for issue_id in issue_ids if issue_id in unread_issue_ids),
        )
    return creator_stats


async def get_creator_summaries(
    db: AsyncSession,
    user_id: int,
    requested_keys: list[str],
) -> CreatorSummariesResponse:
    """Compute bounded personal summaries for the requested creator keys.

    Only creator keys visible in the authenticated user's own confirmed issue
    metadata are returned; unknown or foreign keys are silently omitted so a
    creator key can never leak another user's library state.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the aggregated library.
        requested_keys: Bounded list of canonical creator keys to summarize.

    Returns:
        The batch summary response keyed by requested visible creator keys.
    """
    inputs = await load_creator_summary_inputs(db, user_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)
    read_unrated_issue_ids = frozenset(
        issue_id
        for issue_id, status in inputs.owned_issues.items()
        if status == "read" and issue_id not in inputs.effective_ratings
    )
    unread_issue_ids = frozenset(
        issue_id for issue_id, status in inputs.owned_issues.items() if status == "unread"
    )

    # Coverage is deliberately library-wide: it reports how much of the owned
    # library carries confirmed creator metadata, so it must not shrink or shift
    # when a caller asks about fewer creators.
    coverage = _build_coverage(
        inputs,
        rated_issue_ids=rated_issue_ids,
        read_unrated_issue_ids=read_unrated_issue_ids,
        unread_issue_ids=unread_issue_ids,
    )

    creator_stats = aggregate_creators(
        inputs,
        wanted_creator_ids=requested_creator_ids(requested_keys),
        read_unrated_issue_ids=read_unrated_issue_ids,
        unread_issue_ids=unread_issue_ids,
    )

    # ``canonical_creator_key`` echoes the requested key verbatim, so the key
    # spelling the client sent is what the response reports back.
    summaries: dict[str, CreatorSummaryItem] = {}
    for key in requested_keys:
        creator_id = parse_creator_key(key)
        if creator_id is None or creator_id not in creator_stats:
            continue
        aggregates = creator_stats[creator_id]
        summaries[key] = CreatorSummaryItem(
            canonical_creator_key=key,
            display_name=aggregates.display_name,
            normalized_roles=aggregates.roles,
            average_rating=aggregates.average_rating,
            ratings_count=aggregates.ratings_count,
            read_unrated_count=aggregates.read_unrated_count,
            upcoming_count=aggregates.upcoming_count,
        )

    return CreatorSummariesResponse(summaries=summaries, coverage=coverage)


__all__ = [
    "HEADLINE_ROLES",
    "aggregate_creators",
    "get_creator_summaries",
    "parse_creator_key",
    "requested_creator_ids",
]