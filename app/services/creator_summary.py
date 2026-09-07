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

    coverage = _build_coverage(
        inputs,
        rated_issue_ids=rated_issue_ids,
        read_unrated_issue_ids=read_unrated_issue_ids,
        unread_issue_ids=unread_issue_ids,
    )

    creator_issues: dict[int, set[int]] = defaultdict(set)
    creator_headline_issues: dict[int, set[int]] = defaultdict(set)
    creator_roles: dict[int, set[str]] = defaultdict(set)
    creator_names: dict[int, str] = {}
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            creator_issues[credit.external_id].add(issue_id)
            creator_names.setdefault(credit.external_id, credit.display_name)
            for role in credit.roles:
                creator_roles[credit.external_id].add(role)
            if any(role in HEADLINE_ROLES for role in credit.roles):
                creator_headline_issues[credit.external_id].add(issue_id)

    summaries: dict[str, CreatorSummaryItem] = {}
    for key in requested_keys:
        creator_id = parse_creator_key(key)
        if creator_id is None or creator_id not in creator_issues:
            continue

        headline_rated = [
            inputs.effective_ratings[issue_id]
            for issue_id in creator_issues[creator_id]
            if issue_id in creator_headline_issues[creator_id]
            and issue_id in inputs.effective_ratings
        ]
        ratings_count = len(headline_rated)
        average_rating = (
            round(sum(headline_rated) / ratings_count, 2) if ratings_count else None
        )
        read_unrated_count = sum(
            1 for issue_id in creator_issues[creator_id] if issue_id in read_unrated_issue_ids
        )
        upcoming_count = sum(
            1 for issue_id in creator_issues[creator_id] if issue_id in unread_issue_ids
        )
        summaries[key] = CreatorSummaryItem(
            canonical_creator_key=key,
            display_name=creator_names[creator_id],
            normalized_roles=sorted(creator_roles[creator_id]),
            average_rating=average_rating,
            ratings_count=ratings_count,
            read_unrated_count=read_unrated_count,
            upcoming_count=upcoming_count,
        )

    return CreatorSummariesResponse(summaries=summaries, coverage=coverage)


__all__ = [
    "HEADLINE_ROLES",
    "get_creator_summaries",
    "parse_creator_key",
]