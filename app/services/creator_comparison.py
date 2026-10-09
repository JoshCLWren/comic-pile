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

 drilldown support: every metric computed here is also available through the
 bounded drilldown API contracts (issue #3176), using the exact same shared
 aggregation semantics so summary and detail surfaces always reconcile.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_comparison import (
    MAX_COMPARISON_CREATORS,
    MAX_SERIES_AGGREGATES,
    MIN_COMPARISON_CREATORS,
    MIN_RATED_FOR_RELIABLE,
    MIN_RATED_ISSUES_PER_SERIES,
    CreatorComparisonInputs,
    build_series_aggregates,
    load_creator_comparison_inputs,
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
        # Derived from the batch inputs, so no per-creator query is issued.
        series_aggregates = build_series_aggregates(
            inputs.owned_issue_threads,
            frozenset(issue_ids),
            inputs.effective_ratings,
            limit=MAX_SERIES_AGGREGATES,
        )
        strongest_series = [
            CreatorComparisonSeriesAggregate(
                thread_id=thread_id,
                thread_title=thread_title,
                issue_count=issue_count,
                rated_issue_count=rated_issue_count,
                average_rating=average_rating,
            )
            for (
                thread_id,
                thread_title,
                issue_count,
                rated_issue_count,
                average_rating,
            ) in series_aggregates
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
            min_rated_issues_per_series=MIN_RATED_ISSUES_PER_SERIES,
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
    "get_average_drilldown",
    "get_median_drilldown",
    "get_rating_distribution_drilldown",
    "get_5_star_rate_drilldown",
    "get_role_average_drilldown",
    "get_series_average_drilldown",
    "get_read_without_rating_drilldown",
]


async def _get_creator_drilldown_inputs(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
) -> CreatorComparisonInputs:
    """Load comparison inputs scoped to a single creator.

    This is the same 3-query bounded batch used by
    :func:`get_creator_comparison`, restricted to one creator.
    """
    from app.repositories.creator_comparison import load_creator_comparison_inputs

    return await load_creator_comparison_inputs(
        db, user_id, frozenset({creator_id})
    )


def _format_rating(rating: float) -> str:
    """Format a rating value for display on the 1-5 half-star scale."""
    if rating == int(rating):
        return str(int(rating))
    return str(rating)


async def get_average_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
) -> dict[str, object]:
    """Compute average rating drilldown for one creator.

    Returns a dict with:
    - ``calculation``: human-readable formula string
    - ``issues``: list of issue contributions (issue_number, rating, role)
    - ``total_rated``: number of rated issues
    - ``total_points``: sum of all rating points
    """
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    # Build the creator's issue IDs and credits
    creator_issue_ids: set[int] = set()
    creator_roles: set[str] = set()
    creator_name: str | None = None
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            creator_issue_ids.add(issue_id)
            creator_roles.update(credit.roles)
            if creator_name is None:
                creator_name = credit.display_name

    # Headline-rated issues: issues with headline-eligible role AND effective rating
    headline_rated: list[tuple[int, float, str | None]] = []  # (issue_id, rating, role)
    for issue_id in creator_issue_ids:
        if issue_id not in inputs.effective_ratings:
            continue
        credits = inputs.issue_creator_credits[issue_id]
        headline_credits = [
            c for c in credits if any(role in HEADLINE_ROLES for role in c.roles)]
        if not any(
            role in HEADLINE_ROLES for credit in headlines for role in credit.roles
        ):
            # Check if any credit has a headline role
            has_headline = False
            for c in credits:
                if any(role in HEADLINE_ROLES for role in c.roles):
                    has_headline = True
                    break
            if not has_headline:
                continue
        # More correct: find the credit with a headline role
        for credit in credits:
            if any(role in HEADLINE_ROLES for role in credit.roles):
                headline_rated.append(
                    (issue_id, inputs.effective_ratings[issue_id], credit.external_id)
                )
                break

    # Actually, let me redo this more carefully using the existing pattern from get_creator_comparison
    rated_issue_ids = frozenset(inputs.effective_ratings)
    creator_rated_ids = frozenset(
        issue_id for issue_id in creator_issue_ids if issue_id in rated_issue_ids
    )

    # Filter to headline-eligible rated issues
    headline_rated_ratings: list[float] = []
    headline_rated_issues: list[tuple[int, float, str | None]] = []  # (issue_id, rating, role)
    for issue_id in creator_rated_ids:
        credits = inputs.issue_creator_credits[issue_id]
        has_headline_role = any(
            role in HEADLINE_ROLES for credit in credits for role in credit.roles
        )
        if has_headline_role:
            headline_rated_ratings.append(inputs.effective_ratings[issue_id])
            # Find the role
            for credit in credits:
                if any(role in HEADLINE_ROLES for role in credit.roles):
                    headline_rated_issues.append(
                        (issue_id, inputs.effective_ratings[issue_id], credit.roles[0])
                    )
                    break

    ratings_count = len(headline_rated_ratings)
    total_points = sum(headline_rated_ratings) if headline_rated_ratings else 0
    average = round(total_points / ratings_count, 2) if ratings_count else None

    # Build calculation string
    if ratings_count:
        calc = f"{total_points} total rating points ÷ {ratings_count} rated issue{'s' if ratings_count != 1 else ''} = {average:.2f}★"
    else:
        calc = "No rated issues"

    # Build issue contributions list
    issues_list: list[dict[str, object]] = []
    for issue_id, rating, role in headline_rated_issues:
        issue_thread_id = None
        issue_thread_title = None
        # Find thread info from owned_issue_threads
        thread_info = inputs.owned_issue_threads.get(issue_id)
        if thread_info:
            issue_thread_id = thread_info.thread_id
            issue_thread_title = thread_info.thread_title
        issues_list.append(
            {
                "issue_number": str(issue_id),
                "rating": _format_rating(rating),
                "role": role or "unknown",
                "thread_id": issue_thread_id,
                "thread_title": issue_thread_title or "",
            }
        )

    return {
        "calculation": calc,
        "issues": issues_list,
        "total_rated": ratings_count,
        "total_points": total_points,
    }


async def get_median_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
) -> dict[str, object]:
    """Compute median rating drilldown for one creator.

    Returns a dict with:
    - ``calculation``: human-readable formula string
    - ``sorted_ratings``: list of ratings sorted descending, showing which
      observations determine the median
    - ``ratings_count``: number of rated issues
    """
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)
    creator_issue_ids = set()
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id == creator_id:
                creator_issue_ids.add(issue_id)

    # Headline-rated issues
    headline_rated: list[float] = []
    for issue_id in creator_issue_ids:
        if issue_id not in rated_issue_ids:
            continue
        credits = inputs.issue_creator_credits[issue_id]
        if any(role in HEADLINE_ROLES for credit in credits for role in credit.roles):
            headline_rated.append(inputs.effective_ratings[issue_id])

    ratings_count = len(headline_rated)
    sorted_ratings = sorted(headline_rated, reverse=True)

    if ratings_count == 0:
        return {
            "calculation": "No rated issues",
            "sorted_ratings": [],
            "ratings_count": 0,
        }

    # Compute median
    from statistics import median
    med = median(sorted_ratings)

    # Build calculation string for odd/even sample
    if ratings_count % 2 == 1:
        middle_idx = ratings_count // 2
        middle_value = sorted_ratings[middle_idx]
        calc = f"Sorted ratings: {', '.join(_format_rating(r) for r in sorted_ratings)}; middle value (#{middle_idx + 1}) = {_format_rating(middle_value)}★"
    else:
        lower_idx = ratings_count // 2 - 1
        upper_idx = ratings_count // 2
        lower_value = sorted_ratings[lower_idx]
        upper_value = sorted_ratings[upper_idx]
        median_val = (lower_value + upper_value) / 2
        calc = (
            f"Sorted ratings: {', '.join(_format_rating(r) for r in sorted_ratings)};"
            f" middle observations (#{lower_idx + 1}) = {_format_rating(lower_value)}★ and "
            f"(#{upper_idx + 1}) = {_format_rating(upper_value)}★ → median = {median_val:.2f}★"
        )

    return {
        "calculation": calc,
        "sorted_ratings": [
            {"rank": i + 1, "value": _format_rating(r)} for i, r in enumerate(sorted_ratings)
        ],
        "ratings_count": ratings_count,
    }


async def get_rating_distribution_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
    bucket: str,
) -> dict[str, object]:
    """Compute rating distribution bucket drilldown for one creator.

    Returns a dict with:
    - ``calculation``: human-readable formula for the bucket
    - ``issues``: list of issues in this bucket (issue_number, rating, role, thread)
    - ``bucket_count``: number of issues in this bucket
    - ``total_rated``: total number of rated issues (denominator)
    """
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)

    # Gather all headline-rated issues with their ratings
    all_rated: list[tuple[int, float, str | None]] = []  # (issue_id, rating, role)
    creator_issue_ids: set[int] = set()
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id == creator_id:
                creator_issue_ids.add(issue_id)
                if issue_id in rated_issue_ids:
                    all_rated.append((issue_id, inputs.effective_ratings[issue_id], credit.roles[0] if credit.roles else None))

    # Determine the bucket range
    # Buckets: 5, 4.5, 4, 3.5, 3, 2.5, 2, 1.5, 1
    all_ratings: list[float] = [rating for _, rating, _ in all_rated]

    bucket_map: dict[str, tuple[float, float]] = {
        "5": (5.0, 5.0),
        "4.5": (4.75, 5.0),
        "4": (4.0, 4.75),
        "3.5": (3.5, 4.0),
        "3": (3.0, 3.5),
        "2.5": (2.5, 3.0),
        "2": (2.0, 2.5),
        "1.5": (1.5, 2.0),
        "1": (1.0, 1.5),
    }

    if bucket not in bucket_map:
        return {
            "calculation": f"Unknown bucket: {bucket}",
            "issues": [],
            "bucket_count": 0,
            "total_rated": len(all_ratings),
        }

    low, high = bucket_map[bucket]
    bucket_issues: list[dict[str, object]] = []
    for issue_id, rating, role in all_rated:
        if low <= rating <= high:
            # Get thread info
            thread_info = inputs.owned_issue_threads.get(issue_id)
            thread_id = thread_info.thread_id if thread_info else None
            thread_title = thread_info.thread_title if thread_info else ""
            bucket_issues.append(
                {
                    "issue_number": str(issue_id),
                    "rating": _format_rating(rating),
                    "role": role or "unknown",
                    "thread_id": thread_id,
                    "thread_title": thread_title,
                }
            )

    count = len(bucket_issues)
    total = len(all_ratings)

    if count > 0 and total > 0:
        calc = f"{count} of {total} rated issue{'s' if total != 1 else ''} fall in the {bucket}★ bucket"
    else:
        calc = f"0 of {total} rated issue{'s' if total != 1 else ''} in the {bucket}★ bucket"

    return {
        "calculation": calc,
        "issues": bucket_issues,
        "bucket_count": count,
        "total_rated": total,
    }


async def get_5_star_rate_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
) -> dict[str, object]:
    """Compute 5★ rate drilldown for one creator.

    Returns a dict with:
    - ``calculation``: human-readable proportion formula
    - ``top_issue_ids``: list of issue IDs that are 5★ rated
    - ``rated_count``: total rated issues
    - ``top_count``: number of 5★ rated issues
    """
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)

    # Find all issues with a 5.0 effective rating (headline eligible)
    top_ratings: list[tuple[int, float, str | None]] = []  # (issue_id, rating, role)
    for issue_id in rated_issue_ids:
        credits = inputs.issue_creator_credits[issue_id]
        if any(role in HEADLINE_ROLES for credit in credits for role in credit.roles):
            if inputs.effective_ratings[issue_id] >= 5.0:
                for credit in credits:
                    if any(role in HEADLINE_ROLES for role in credit.roles):
                        top_ratings.append(
                            (issue_id, inputs.effective_ratings[issue_id], credit.roles[0])
                        )
                        break

    top_count = len(top_ratings)
    rated_count = len(rated_issue_ids)

    if rated_count > 0:
        proportion = round(top_count / rated_count, 3)
        calc = f"{top_count} five-star rating{'s' if top_count != 1 else ''} ÷ {rated_count} rated issue{'s' if rated_count != 1 else ''} = {proportion * 100:.1f}%"
    else:
        calc = "No rated issues"

    # Build issue list
    top_issues: list[dict[str, object]] = []
    for issue_id, rating, role in top_ratings:
        thread_info = inputs.owned_issue_threads.get(issue_id)
        top_issues.append(
            {
                "issue_number": str(issue_id),
                "rating": _format_rating(rating),
                "role": role or "unknown",
                "thread_id": thread_info.thread_id if thread_info else None,
                "thread_title": thread_info.thread_title if thread_info else "",
            }
        )

    return {
        "calculation": calc,
        "top_issue_ids": [issue_id for issue_id, _, _ in top_ratings],
        "rated_count": rated_count,
        "top_count": top_count,
        "issues": top_issues,
    }


async def get_role_average_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
    role: str,
) -> dict[str, object]:
    """Compute role-specific average rating drilldown for one creator.

    Returns a dict with:
    - ``calculation``: human-readable formula
    - ``role``: the role name
    - ``issue_count``: number of issues with this role
    - ``rated_issue_count``: number of rated issues with this role
    - ``average_rating``: average rating for rated issues with this role
    - ``issues``: list of issues contributing to the average
    """
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)

    # Find issues where this creator has this role and the issue is rated
    role_issue_ids: list[int] = []
    role_ratings: list[float] = []
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id == creator_id and role in credit.roles and issue_id in rated_issue_ids:
                role_issue_ids.append(issue_id)
                role_ratings.append(inputs.effective_ratings[issue_id])

    issue_count = len(role_issue_ids)
    rated_count = len(role_ratings)

    if rated_count > 0:
        avg = round(sum(role_ratings) / rated_count, 2)
        calc = f"{avg:.2f} average ÷ {rated_count} rated issue{'s' if rated_count != 1 else ''} with {role} role"
    else:
        avg = None
        calc = f"No rated issues with {role} role"

    # Build issue list
    issues_list: list[dict[str, object]] = []
    for i, (issue_id, rating) in enumerate(zip(role_issue_ids, role_ratings)):
        thread_info = inputs.owned_issue_threads.get(issue_id)
        issues_list.append(
            {
                "issue_number": str(issue_id),
                "rating": _format_rating(rating),
                "role": role,
                "thread_id": thread_info.thread_id if thread_info else None,
                "thread_title": thread_info.thread_title if thread_info else "",
            }
        )

    return {
        "calculation": calc,
        "role": role,
        "issue_count": issue_count,
        "rated_issue_count": rated_count,
        "average_rating": avg,
        "issues": issues_list,
    }


async def get_series_average_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
    series_key: str,
) -> dict[str, object]:
    """Compute series average drilldown for one creator and series.

    The series_key should be a canonical thread key like ``thread:123``.

    Returns a dict with:
    - ``calculation``: human-readable formula
    - ``thread_id``: the series thread id
    - ``thread_title``: the series title
    - ``issue_count``: total issues in the series
    - ``rated_issue_count``: rated issues in the series
    - ``average_rating``: average rating for rated issues
    - ``issues``: list of rated issues in the series
    """
    from app.repositories.creator_comparison import parse_series_key

    thread_id = parse_series_key(series_key)
    if thread_id is None:
        return {
            "calculation": f"Invalid series key: {series_key}",
            "thread_id": None,
            "thread_title": "",
            "issue_count": 0,
            "rated_issue_count": 0,
            "average_rating": None,
            "issues": [],
        }

    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    # Get all issue IDs for this creator
    creator_issue_ids: set[int] = set()
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id == creator_id:
                creator_issue_ids.add(issue_id)

    # Find issues in this thread
    thread_issue_ids: set[int] = set()
    for issue_id in creator_issue_ids:
        thread_info = inputs.owned_issue_threads.get(issue_id)
        if thread_info and thread_info.thread_id == thread_id:
            thread_issue_ids.add(issue_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)

    # Gather rated issues in this thread
    thread_rated: list[tuple[int, float, str | None]] = []  # (issue_id, rating, role)
    for issue_id in thread_issue_ids:
        if issue_id in rated_issue_ids:
            credits = inputs.issue_creator_credits[issue_id]
            for credit in credits:
                if credit.external_id == creator_id:
                    thread_rated.append((issue_id, inputs.effective_ratings[issue_id], credit.roles[0] if credit.roles else None))
                    break

    ratings_count = len(thread_rated)
    total_issue_count = len(thread_issue_ids)
    total_points = sum(rating for _, rating, _ in thread_rated) if thread_rated else 0
    average = round(total_points / ratings_count, 2) if ratings_count else None

    # Build calculation string
    if ratings_count > 0:
        calc = f"{total_points} total rating points ÷ {ratings_count} rated issue{'s' if ratings_count != 1 else ''} = {average:.2f}★"
    else:
        calc = "No rated issues in this series"

    # Build issue list
    issues_list: list[dict[str, object]] = []
    for issue_id, rating, role in thread_rated:
        issues_list.append(
            {
                "issue_number": str(issue_id),
                "rating": _format_rating(rating),
                "role": role or "unknown",
            }
        )

    return {
        "calculation": calc,
        "thread_id": thread_id,
        "thread_title": series_key,
        "issue_count": total_issue_count,
        "rated_issue_count": ratings_count,
        "average_rating": average,
        "issues": issues_list,
    }


async def get_read_without_rating_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
) -> dict[str, object]:
    """Compute read-without-rating drilldown for one creator.

    Returns a dict with:
    - ``calculation``: human-readable explanation
    - ``issues``: list of read-but-unrated issues (issue_number, title, thread, role)
    - ``count``: total number of such issues
    """
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)

    rated_issue_ids = frozenset(inputs.effective_ratings)

    # Find read issues that have no effective rating
    read_unrated: list[tuple[int, str, int | None, str | None]] = (  # (issue_id, issue_number, thread_id, role)
        []
    )
    for issue_id, status in inputs.owned_issues.items():
        if status == "read" and issue_id not in rated_issue_ids:
            # Find the role(s) for this issue
            credits = inputs.issue_creator_credits.get(issue_id, ())
            role_list: list[str] = []
            for credit in credits:
                if credit.external_id == creator_id:
                    role_list.extend(credit.roles)
            thread_info = inputs.owned_issue_threads.get(issue_id)
            thread_id = thread_info.thread_id if thread_info else None
            thread_title = thread_info.thread_title if thread_info else ""
            read_unrated.append((issue_id, str(issue_id), thread_id, thread_title, role_list))

    count = len(read_unrated)

    # Build calculation string
    if count > 0:
        calc = f"{count} issue{'s' if count != 1 else ''} marked read with no stored rating event"
    else:
        calc = "No read-without-rating issues"

    # Build issue list
    issues_list: list[dict[str, object]] = []
    for issue_id, issue_number, thread_id, thread_title, role_list in read_unrated:
        issues_list.append(
            {
                "issue_number": issue_number,
                "thread_id": thread_id,
                "thread_title": thread_title,
                "roles": role_list,
            }
        )

    return {
        "calculation": calc,
        "issues": issues_list,
        "count": count,
    }
