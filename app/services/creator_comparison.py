"""Service for the bounded personal creator comparison API (issue #3091).

This service coordinates the aggregation of personal creator comparison data
for 2-4 canonical creators, reusing the rating, role, and coverage semantics
from #2028/#2037 rather than reimplementing a competing definition.
Every personal aggregate is scoped through the authenticated user's owned
ComicPile issues and their confirmed local issue metadata.

Key semantics (matching #2028 exactly):
- Only real ``rate`` events with a rating contribute.
- When an issue has multiple rate events, the latest event by timestamp/id wins.
- One issue contributes at most once to a creator's headline average/count even
  if that creator has multiple roles on the issue.
- Headline-eligible roles: writer, artist, penciler, inker, colorist, letterer.
- Coverage distinguishes complete from lower-bound statistics.
- Missing/unconfirmed metadata never counts as negative attribution evidence.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_comparison import (
    CreatorComparisonInputs,
    MAX_COMPARISON_CREATORS,
    MIN_COMPARISON_CREATORS,
    MIN_RATED_FOR_RELIABLE,
    MAX_SERIES_AGGREGATES,
    load_creator_comparison_inputs,
    load_series_aggregates,
)
from app.schemas.creator_comparison import (
    CreatorComparisonCoverage,
    CreatorComparisonItem,
    CreatorComparisonResponse,
    CreatorComparisonRoleStat,
    CreatorComparisonSeriesAggregate,
)
from app.services.creator_summary import HEADLINE_ROLES, parse_creator_key


def _build_coverage(
    inputs: CreatorComparisonInputs,
    *,
    rated_issue_ids: frozenset[int],
    read_unrated_issue_ids: frozenset[int],
    unread_issue_ids: frozenset[int],
) -> CreatorComparisonCoverage:
    """Build the explicit metadata-coverage block from the owned-issue sets."""

    def _with_metadata(issue_ids: frozenset[int]) -> int:
        return sum(1 for issue_id in issue_ids if issue_id in inputs.issues_with_creator_metadata)

    rated_total = len(rated_issue_ids)
    rated_with = _with_metadata(rated_issue_ids)
    read_unrated_total = len(read_unrated_issue_ids)
    read_unrated_with = _with_metadata(read_unrated_issue_ids)
    unread_total = len(unread_issue_ids)
    unread_with = _with_metadata(unread_issue_ids)

    return CreatorComparisonCoverage(
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


def _compute_rating_distribution(ratings: list[float]) -> dict[str, int]:
    """Compute rating distribution as a dict of rating string to count."""
    distribution: dict[str, int] = defaultdict(int)
    for rating in ratings:
        # Rating is on 1-5 scale with 0.5 increments; use integer part for display
        key = str(int(rating)) if rating == int(rating) else str(rating)
        distribution[key] += 1
    return dict(distribution)


def _compute_top_rating_rate(ratings: list[float]) -> float | None:
    """Compute proportion of ratings at the top of the 1-5 scale (5.0)."""
    if not ratings:
        return None
    top_ratings = sum(1 for r in ratings if r >= 5.0)
    return round(top_ratings / len(ratings), 3)


async def get_creator_comparison(
    db: AsyncSession,
    user_id: int,
    requested_keys: list[str],
) -> CreatorComparisonResponse:
    """Compute bounded personal comparison for the requested creator keys.

    Only creator keys visible in the authenticated user's own confirmed issue
    metadata are compared; unknown or foreign keys are silently omitted so a
    creator key can never leak another user's library state.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the aggregated library.
        requested_keys: Bounded list of canonical creator keys to compare (2-4).

    Returns:
        The batch comparison response keyed by requested visible creator keys.

    Raises:
        ValueError: When the number of keys is not in [2, 4] or keys are malformed.
    """
    if len(requested_keys) < MIN_COMPARISON_CREATORS or len(requested_keys) > MAX_COMPARISON_CREATORS:
        raise ValueError(
            f"Comparison requires {MIN_COMPARISON_CREATORS} to {MAX_COMPARISON_CREATORS} creator keys, got {len(requested_keys)}"
        )

    requested_creator_ids: set[int] = set()
    for key in requested_keys:
        creator_id = parse_creator_key(key)
        if creator_id is None:
            raise ValueError(f"Invalid creator key format: {key}")
        requested_creator_ids.add(creator_id)

    if len(requested_creator_ids) != len(requested_keys):
        raise ValueError("Duplicate creator keys are not allowed")

    inputs = await load_creator_comparison_inputs(db, user_id, frozenset(requested_creator_ids))

    # Build coverage over owned library (same as #2028).
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

    # Aggregate per-requested-creator statistics.
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

    comparisons: dict[str, CreatorComparisonItem] = {}
    insufficient_data_keys: list[str] = []

    for key in requested_keys:
        creator_id = parse_creator_key(key)
        if creator_id is None or creator_id not in creator_issues:
            # Creator not found in user's library - silently omit per contract
            continue

        issue_ids = creator_issues[creator_id]
        headline_issue_ids = creator_headline_issues[creator_id]

        # Headline-rated issues (issues with headline-eligible role AND effective rating)
        headline_rated = [
            inputs.effective_ratings[issue_id]
            for issue_id in issue_ids
            if issue_id in headline_issue_ids and issue_id in inputs.effective_ratings
        ]
        ratings_count = len(headline_rated)

        average_rating = round(sum(headline_rated) / ratings_count, 2) if ratings_count else None
        median_rating = round(median(headline_rated), 2) if ratings_count else None

        rating_distribution = _compute_rating_distribution(headline_rated)
        top_rating_rate = _compute_top_rating_rate(headline_rated)

        # Role-specific statistics
        role_stats: list[CreatorComparisonRoleStat] = []
        for role in sorted(creator_roles[creator_id]):
            role_issue_ids = [
                issue_id
                for issue_id in issue_ids
                if any(
                    role in credit.roles
                    for credit in inputs.issue_creator_credits[issue_id]
                    if credit.external_id == creator_id
                )
            ]
            role_ratings = [
                inputs.effective_ratings[issue_id]
                for issue_id in role_issue_ids
                if issue_id in inputs.effective_ratings
            ]
            role_stats.append(
                CreatorComparisonRoleStat(
                    role=role,
                    issue_count=len(role_issue_ids),
                    average_rating=(
                        round(sum(role_ratings) / len(role_ratings), 2) if role_ratings else None
                    ),
                )
            )

        # Strongest series/thread aggregates (effective-rating semantics shared
        # with creator detail: latest rating per issue, never rating history).
        series_aggregates = await load_series_aggregates(
            db,
            user_id,
            frozenset(issue_ids),
            inputs.effective_ratings,
            limit=MAX_SERIES_AGGREGATES,
        )
        strongest_series = [
            CreatorComparisonSeriesAggregate(
                thread_id=thread_id,
                thread_title=thread_title,
                issue_count=issue_count,
                average_rating=average_rating,
            )
            for thread_id, thread_title, issue_count, average_rating in series_aggregates
        ]

        # Unread/upcoming and read-unrated counts
        unread_upcoming_count = sum(
            1 for issue_id in issue_ids if inputs.owned_issues.get(issue_id) == "unread"
        )
        read_unrated_count = sum(
            1
            for issue_id in issue_ids
            if inputs.owned_issues.get(issue_id) == "read" and issue_id not in inputs.effective_ratings
        )

        # Insufficient data flag
        insufficient_data = ratings_count < MIN_RATED_FOR_RELIABLE
        if insufficient_data:
            insufficient_data_keys.append(key)

        canonical_key = f"creator:{creator_id}"
        comparisons[canonical_key] = CreatorComparisonItem(
            canonical_creator_key=canonical_key,
            display_name=creator_names[creator_id],
            normalized_roles=sorted(creator_roles[creator_id]),
            average_rating=average_rating,
            median_rating=median_rating,
            ratings_count=ratings_count,
            rating_distribution=rating_distribution,
            top_rating_rate=top_rating_rate,
            role_stats=role_stats,
            strongest_series=strongest_series,
            unread_upcoming_count=unread_upcoming_count,
            read_unrated_count=read_unrated_count,
            insufficient_data=insufficient_data,
        )

    return CreatorComparisonResponse(
        comparisons=comparisons,
        coverage=coverage,
        insufficient_data_keys=insufficient_data_keys,
    )


__all__ = [
    "get_creator_comparison",
]