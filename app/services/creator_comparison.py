"""Service for the bounded personal creator comparison API (issues #3091, #3176).

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

Drilldown support (issue #3176): every summary metric is also available through
a bounded drilldown contract. The drilldowns reuse the exact aggregation
helpers that produce the summary values, so a summary number and its evidence
page always reconcile: same headline sample, same role/series scoping, same
rounding. Evidence lists are paginated through an opaque offset cursor so
large creators stay bounded and responsive.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.creator_comparison import (
    MAX_COMPARISON_CREATORS,
    MAX_SERIES_AGGREGATES,
    MIN_COMPARISON_CREATORS,
    MIN_RATED_FOR_RELIABLE,
    MIN_RATED_ISSUES_PER_SERIES,
    CreatorComparisonInputs,
    CreatorCredit,
    build_series_aggregates,
    load_creator_comparison_inputs,
)
from app.schemas.creator_comparison import (
    RATING_BUCKETS,
    CreatorAverageDrilldownResponse,
    CreatorComparisonCoverage,
    CreatorComparisonItem,
    CreatorComparisonResponse,
    CreatorComparisonRoleStat,
    CreatorComparisonSeriesAggregate,
    CreatorDistributionDrilldownResponse,
    CreatorDrilldownIssue,
    CreatorDrilldownRatingObservation,
    CreatorFiveStarRateDrilldownResponse,
    CreatorMedianDrilldownResponse,
    CreatorReadWithoutRatingDrilldownResponse,
    CreatorRoleAverageDrilldownResponse,
    CreatorSeriesAverageDrilldownResponse,
    CreatorUnreadDrilldownResponse,
)
from app.services.creator_series import parse_series_key
from app.services.creator_summary import HEADLINE_ROLES, parse_creator_key

#: Default number of evidence rows on one drilldown page (issue #3176).
DRILLDOWN_PAGE_SIZE_DEFAULT = 50

#: Hard upper bound for one drilldown evidence page (issue #3176).
DRILLDOWN_PAGE_SIZE_MAX = 100


# ---------------------------------------------------------------------------
# Shared aggregation helpers (one canonical implementation for summary and
# drilldown surfaces, so the two can never drift apart).
# ---------------------------------------------------------------------------


#: One rated evidence row: ``(issue_id, effective rating, creator role)``.
RatedEvidenceRow = tuple[int, float, str | None]

#: One evidence row whose rating may legitimately be absent.
EvidenceRow = tuple[int, float | None, str | None]


def _rating_bucket_key(rating: float) -> str:
    """Bucket key for a rating on ComicPile's 1-5 half-star scale.

    Both the summary distribution and the distribution drilldown use this one
    key function, so a drilldown bucket always names a real summary bucket.

    Args:
        rating: Effective rating value.

    Returns:
        The human-readable bucket key (``"5"``, ``"4.5"``, ...).
    """
    if rating == int(rating):
        return str(int(rating))
    return str(rating)


def _compute_rating_distribution(ratings: list[float]) -> dict[str, int]:
    """Compute rating distribution as a dict of rating string to count."""
    distribution: dict[str, int] = defaultdict(int)
    for rating in ratings:
        distribution[_rating_bucket_key(rating)] += 1
    return dict(distribution)


def _compute_top_rating_rate(ratings: list[float]) -> float | None:
    """Compute proportion of ratings at the top of the 1-5 scale (5.0)."""
    if not ratings:
        return None
    top_ratings = sum(1 for rating in ratings if rating >= 5.0)
    return round(top_ratings / len(ratings), 3)


def _average_or_none(values: list[float]) -> float | None:
    """Round the mean to the summary's canonical two decimal places."""
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _median_or_none(values: list[float]) -> float | None:
    """Round the median to the summary's canonical two decimal places."""
    if not values:
        return None
    return round(median(values), 2)


def _creator_profile(
    inputs: CreatorComparisonInputs, creator_id: int
) -> tuple[set[int], set[int], set[str], str | None]:
    """Derive one creator's attributed issue sets from the batch inputs.

    Works for both the multi-creator comparison batch and the single-creator
    drilldown batch, because credits are always filtered by ``external_id``.

    Args:
        inputs: User-scoped comparison inputs.
        creator_id: External person id of the drilled creator.

    Returns:
        ``(issue_ids, headline_issue_ids, roles, display_name)`` where
        ``issue_ids`` holds every issue credited to the creator in any role,
        ``headline_issue_ids`` holds issues with at least one
        headline-eligible role, and ``roles`` holds every credited role.
    """
    issue_ids: set[int] = set()
    headline_issue_ids: set[int] = set()
    roles: set[str] = set()
    display_name: str | None = None
    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            if credit.external_id != creator_id:
                continue
            issue_ids.add(issue_id)
            roles.update(credit.roles)
            if any(role in HEADLINE_ROLES for role in credit.roles):
                headline_issue_ids.add(issue_id)
            if display_name is None:
                display_name = credit.display_name
    return issue_ids, headline_issue_ids, roles, display_name


def _role_issue_ids(
    inputs: CreatorComparisonInputs, creator_id: int, role: str
) -> list[int]:
    """Issue ids where the creator is credited in one role, sorted by issue id."""
    matched: list[int] = []
    for issue_id in sorted(inputs.issue_creator_credits):
        for credit in inputs.issue_creator_credits[issue_id]:
            if credit.external_id == creator_id and role in credit.roles:
                matched.append(issue_id)
                break
    return matched


def _creator_role_on(
    credits: tuple[CreatorCredit, ...], creator_id: int, preferred: str | None = None
) -> str | None:
    """Name the creator's most meaningful role on one issue.

    Prefers the drilled role when given, then the first headline-eligible
    role, then any credited role. Deterministic because credit roles are
    sorted at extraction time.
    """
    for credit in credits:
        if credit.external_id != creator_id:
            continue
        if preferred is not None and preferred in credit.roles:
            return preferred
        for role in credit.roles:
            if role in HEADLINE_ROLES:
                return role
    for credit in credits:
        if credit.external_id == creator_id and credit.roles:
            return credit.roles[0]
    return None


def _headline_rated_rows(
    inputs: CreatorComparisonInputs, creator_id: int, headline_issue_ids: set[int]
) -> list[RatedEvidenceRow]:
    """Rated headline evidence rows as ``(issue_id, rating, role)`` by issue id."""
    rows: list[tuple[int, float, str | None]] = []
    for issue_id in sorted(headline_issue_ids):
        rating = inputs.effective_ratings.get(issue_id)
        if rating is None:
            continue
        role = _creator_role_on(inputs.issue_creator_credits.get(issue_id, ()), creator_id)
        rows.append((issue_id, rating, role))
    return rows


def _format_rating(rating: float) -> str:
    """Format a rating value for display on the 1-5 half-star scale."""
    if rating == int(rating):
        return str(int(rating))
    return str(rating)


def _format_points(points: float) -> str:
    """Format a rating-points total without manufacturing precision."""
    if points == int(points):
        return str(int(points))
    return str(points)


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

    comparisons: dict[str, CreatorComparisonItem] = {}
    insufficient_data_keys: list[str] = []

    for key in requested_keys:
        creator_id = parse_creator_key(key)
        if creator_id is None:
            continue
        issue_ids, headline_issue_ids, creator_roles, creator_name = _creator_profile(
            inputs, creator_id
        )
        if not issue_ids:
            # Creator not found in user's library - silently omit per contract
            continue

        # Headline-rated issues (issues with headline-eligible role AND effective rating).
        headline_rated = [
            inputs.effective_ratings[issue_id]
            for issue_id in headline_issue_ids
            if issue_id in inputs.effective_ratings
        ]
        ratings_count = len(headline_rated)

        average_rating = _average_or_none(headline_rated)
        median_rating = _median_or_none(headline_rated)

        rating_distribution = _compute_rating_distribution(headline_rated)
        top_rating_rate = _compute_top_rating_rate(headline_rated)

        # Role-specific statistics
        role_stats: list[CreatorComparisonRoleStat] = []
        for role in sorted(creator_roles):
            role_issue_id_list = _role_issue_ids(inputs, creator_id, role)
            role_ratings = [
                inputs.effective_ratings[issue_id]
                for issue_id in role_issue_id_list
                if issue_id in inputs.effective_ratings
            ]
            role_stats.append(
                CreatorComparisonRoleStat(
                    role=role,
                    issue_count=len(role_issue_id_list),
                    rated_issue_count=len(role_ratings),
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
                average_rating=average,
            )
            for (
                thread_id,
                thread_title,
                issue_count,
                rated_issue_count,
                average,
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
            display_name=creator_name or canonical_key,
            normalized_roles=sorted(creator_roles),
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


# ---------------------------------------------------------------------------
# Drilldown evidence pages (issue #3176).
# ---------------------------------------------------------------------------


async def _get_creator_drilldown_inputs(
    db: AsyncSession,
    user_id: int,
    creator_id: int,
) -> CreatorComparisonInputs:
    """Load comparison inputs scoped to a single creator.

    This is the same 3-query bounded batch used by
    :func:`get_creator_comparison`, restricted to one creator.
    """
    return await load_creator_comparison_inputs(db, user_id, frozenset({creator_id}))


def _parse_drilldown_cursor(cursor: str | None) -> int:
    """Validate and decode the opaque evidence-page cursor.

    Args:
        cursor: Cursor token from the client, or ``None`` for the first page.

    Returns:
        The row offset the cursor names.

    Raises:
        ValueError: When the cursor is not a page token this API issued.
    """
    if cursor is None or cursor == "":
        return 0
    if not cursor.isdigit():
        raise ValueError("cursor must be a page token returned by a previous page")
    return int(cursor)


def _evidence_page[EvidenceRowT: (RatedEvidenceRow, EvidenceRow)](
    rows: Sequence[EvidenceRowT],
    limit: int,
    cursor: str | None,
) -> tuple[list[EvidenceRowT], str | None]:
    """Slice one bounded evidence page out of the complete row set.

    Args:
        rows: Complete deterministic evidence rows.
        limit: Page size requested by the client.
        cursor: Cursor token from the client, or ``None`` for the first page.

    Returns:
        ``(page_rows, next_cursor)`` where ``next_cursor`` is ``None`` on the
        last page.
    """
    offset = _parse_drilldown_cursor(cursor)
    page = list(rows[offset : offset + limit])
    next_offset = offset + limit
    next_cursor = str(next_offset) if next_offset < len(rows) else None
    return page, next_cursor


def _drilldown_issue(
    inputs: CreatorComparisonInputs,
    issue_id: int,
    rating: float | None,
    role: str | None,
) -> CreatorDrilldownIssue:
    """Build one evidence row with its local thread/series context."""
    thread = inputs.owned_issue_threads.get(issue_id)
    return CreatorDrilldownIssue(
        issue_id=issue_id,
        issue_number=inputs.issue_numbers.get(issue_id, str(issue_id)),
        rating=rating,
        role=role,
        thread_id=thread.thread_id if thread else None,
        thread_title=thread.thread_title if thread else None,
    )


def _require_creator_key(creator_key: str) -> int:
    """Validate a canonical creator key for drilldown endpoints.

    Args:
        creator_key: Canonical ``creator:<external-person-id>`` key.

    Returns:
        The external person id.

    Raises:
        ValueError: When the key is not a canonical creator key.
    """
    creator_id = parse_creator_key(creator_key)
    if creator_id is None:
        raise ValueError(
            f"Invalid creator key {creator_key!r}: expected creator:<external-person-id>"
        )
    return creator_id


def _plural(count: int, noun: str) -> str:
    """Pluralize a noun for a count in a human-readable calculation."""
    return f"{count} {noun}{'s' if count != 1 else ''}"


async def get_average_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorAverageDrilldownResponse:
    """Evidence page for the average rating metric (issue #3176).

    The numerator, denominator, and average use the exact shared headline
    aggregation that produces the summary ``average_rating`` and
    ``ratings_count``, so the drilldown always reconciles with the card. The
    same page also serves the rated-issue-count metric: its evidence set is
    the complete rated headline sample.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded average evidence page.

    Raises:
        ValueError: When the creator key or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    rows = _headline_rated_rows(inputs, creator_id, headline_issue_ids)
    ratings = [rating for _issue_id, rating, _role in rows]
    total_rated = len(ratings)
    total_points = sum(ratings)

    if total_rated:
        average_display = round(total_points / total_rated, 2)
        calculation = (
            f"{_format_points(total_points)} total rating points ÷ "
            f"{_plural(total_rated, 'rated issue')} = {average_display:.2f}★"
        )
    else:
        calculation = "No rated issues yet, so there is no average to explain."

    page, next_cursor = _evidence_page(rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role) for issue_id, rating, role in page]

    return CreatorAverageDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=total_rated,
        next_cursor=next_cursor,
        total_rated=total_rated,
        total_points=total_points,
        issues=issues,
    )


async def get_median_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorMedianDrilldownResponse:
    """Evidence page for the median rating metric (issue #3176).

    Every ranked observation doubles as a supporting-issue row, and the
    middle observation(s) that determine the median are flagged explicitly.
    The median value matches the summary ``median_rating`` exactly because
    both come from the shared headline sample and rounding.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded median evidence page.

    Raises:
        ValueError: When the creator key or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    rows = _headline_rated_rows(inputs, creator_id, headline_issue_ids)
    # Strongest rating first; issue id breaks ties deterministically.
    rows_by_rating = sorted(rows, key=lambda row: (-row[1], row[0]))
    ratings = [rating for _issue_id, rating, _role in rows_by_rating]
    ratings_count = len(ratings)
    median_value = _median_or_none(ratings)

    if ratings_count == 0:
        calculation = "No rated issues yet, so there is no median to explain."
    elif ratings_count % 2 == 1:
        middle_rank = ratings_count // 2 + 1
        middle_value = ratings[ratings_count // 2]
        calculation = (
            f"{_plural(ratings_count, 'rated issue')} sorted by rating; "
            f"middle value (#{middle_rank}) = {_format_rating(middle_value)}★"
        )
    else:
        lower = ratings[ratings_count // 2 - 1]
        upper = ratings[ratings_count // 2]
        median_display = round((lower + upper) / 2, 2)
        calculation = (
            f"{_plural(ratings_count, 'rated issue')} sorted by rating; "
            f"middle observations (#{ratings_count // 2}) = {_format_rating(lower)}★ and "
            f"(#{ratings_count // 2 + 1}) = {_format_rating(upper)}★ → "
            f"median = {median_display:.2f}★"
        )

    observations: list[CreatorDrilldownRatingObservation] = [
        CreatorDrilldownRatingObservation(
            issue_id=issue_id,
            issue_number=inputs.issue_numbers.get(issue_id, str(issue_id)),
            rank=rank,
            rating=rating,
            determines_median=(
                rank == ratings_count // 2 + 1
                if ratings_count % 2 == 1
                else rank in (ratings_count // 2, ratings_count // 2 + 1)
            ),
            role=role,
            thread_id=(
                inputs.owned_issue_threads[issue_id].thread_id
                if issue_id in inputs.owned_issue_threads
                else None
            ),
            thread_title=(
                inputs.owned_issue_threads[issue_id].thread_title
                if issue_id in inputs.owned_issue_threads
                else None
            ),
        )
        for rank, (issue_id, rating, role) in enumerate(rows_by_rating, start=1)
    ]

    offset = _parse_drilldown_cursor(cursor)
    page = observations[offset : offset + limit]
    next_offset = offset + limit
    next_cursor = str(next_offset) if next_offset < len(observations) else None

    return CreatorMedianDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=ratings_count,
        next_cursor=next_cursor,
        ratings_count=ratings_count,
        median_rating=median_value,
        sorted_ratings=page,
    )


async def get_rating_distribution_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    bucket: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorDistributionDrilldownResponse:
    """Evidence page for one rating-distribution bucket (issue #3176).

    A bucket names an exact rating on the 1-5 half-star scale, so its count
    is exactly the count the summary distribution shows for that bucket key.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        bucket: Rating bucket key (``"5"``, ``"4.5"``, ...).
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded bucket evidence page.

    Raises:
        ValueError: When the creator key, bucket, or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    if bucket not in RATING_BUCKETS:
        raise ValueError(
            f"Unknown rating bucket {bucket!r}: expected one of {', '.join(RATING_BUCKETS)}"
        )
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    rows = _headline_rated_rows(inputs, creator_id, headline_issue_ids)
    bucket_rows = [row for row in rows if _rating_bucket_key(row[1]) == bucket]
    bucket_count = len(bucket_rows)
    total_rated = len(rows)

    if total_rated == 0:
        calculation = "No rated issues yet, so every bucket is empty."
    else:
        percentage = round(bucket_count / total_rated * 100, 1)
        calculation = (
            f"{bucket_count} of {total_rated} rated issues "
            f"are exactly {bucket}★ = {percentage:.1f}%"
        )

    page, next_cursor = _evidence_page(bucket_rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role) for issue_id, rating, role in page]

    return CreatorDistributionDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=bucket_count,
        next_cursor=next_cursor,
        bucket=bucket,
        bucket_count=bucket_count,
        total_rated=total_rated,
        issues=issues,
    )


async def get_5_star_rate_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorFiveStarRateDrilldownResponse:
    """Evidence page for the 5-star rate metric (issue #3176).

    The numerator (issues rated 5.0) and denominator (the complete headline
    rated sample) come from the same shared aggregation as the summary
    ``top_rating_rate``.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded five-star evidence page.

    Raises:
        ValueError: When the creator key or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    rows = _headline_rated_rows(inputs, creator_id, headline_issue_ids)
    top_rows = [row for row in rows if row[1] >= 5.0]
    top_count = len(top_rows)
    rated_count = len(rows)

    if rated_count:
        percentage = round(top_count / rated_count * 100, 1)
        calculation = (
            f"{_plural(top_count, 'five-star rating')} ÷ "
            f"{_plural(rated_count, 'rated issue')} = {percentage:.1f}%"
        )
    else:
        calculation = "No rated issues yet, so there is no five-star rate to explain."

    page, next_cursor = _evidence_page(top_rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role) for issue_id, rating, role in page]

    return CreatorFiveStarRateDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=top_count,
        next_cursor=next_cursor,
        top_count=top_count,
        rated_count=rated_count,
        issues=issues,
    )


async def get_role_average_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    role: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorRoleAverageDrilldownResponse:
    """Evidence page for one role's count and average (issue #3176).

    Distinguishes the total credited population from the rated subset used
    by the average, exactly like the summary role statistic: every credited
    issue appears in the evidence (rated rows carry their rating), and the
    average uses only the rated rows.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        role: The drilled creator role.
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded role evidence page.

    Raises:
        ValueError: When the creator key or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, _headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    role_issue_ids = _role_issue_ids(inputs, creator_id, role)
    rows: list[EvidenceRow] = []
    ratings: list[float] = []
    for issue_id in role_issue_ids:
        rating = inputs.effective_ratings.get(issue_id)
        if rating is not None:
            ratings.append(rating)
        rows.append(
            (
                issue_id,
                rating,
                _creator_role_on(
                    inputs.issue_creator_credits.get(issue_id, ()), creator_id, preferred=role
                ),
            )
        )
    issue_count = len(rows)
    rated_issue_count = len(ratings)
    average = _average_or_none(ratings)

    if rated_issue_count:
        total_points = sum(ratings)
        average_display = round(total_points / rated_issue_count, 2)
        calculation = (
            f"{role}: {_plural(issue_count, 'credited issue')}, "
            f"{_plural(rated_issue_count, 'with effective rating')}; "
            f"{_format_points(total_points)} rating points ÷ "
            f"{_plural(rated_issue_count, 'rated issue')} = {average_display:.2f}★"
        )
    else:
        calculation = f"{role}: {_plural(issue_count, 'credited issue')}, none rated yet."

    page, next_cursor = _evidence_page(rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role_name) for issue_id, rating, role_name in page]

    return CreatorRoleAverageDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=issue_count,
        next_cursor=next_cursor,
        role=role,
        issue_count=issue_count,
        rated_issue_count=rated_issue_count,
        average_rating=average,
        issues=issues,
    )


async def get_series_average_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    series_key: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorSeriesAverageDrilldownResponse:
    """Evidence page for one series' attributed issues and average (issue #3176).

    Distinguishes the total attributed population from the rated subset used
    by the average, with the same latest-effective-rating semantics as the
    summary series aggregate.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        series_key: Canonical series key (``thread:<id>``).
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded series evidence page.

    Raises:
        ValueError: When the creator key, series key, or cursor is malformed.
        KeyError: When the creator or series is not in the user's library.
    """
    thread_id = parse_series_key(series_key)
    if thread_id is None:
        raise ValueError(
            f"Invalid series key {series_key!r}: expected thread:<local-thread-id>"
        )
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, _headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    thread_title: str | None = None
    thread_issue_ids: list[int] = []
    for issue_id in sorted(issue_ids):
        thread = inputs.owned_issue_threads.get(issue_id)
        if thread is None or thread.thread_id != thread_id:
            continue
        thread_issue_ids.append(issue_id)
        if thread_title is None:
            thread_title = thread.thread_title

    if not thread_issue_ids:
        raise KeyError(series_key)

    rows: list[EvidenceRow] = []
    ratings: list[float] = []
    for issue_id in thread_issue_ids:
        rating = inputs.effective_ratings.get(issue_id)
        if rating is not None:
            ratings.append(rating)
        rows.append(
            (
                issue_id,
                rating,
                _creator_role_on(inputs.issue_creator_credits.get(issue_id, ()), creator_id),
            )
        )
    issue_count = len(rows)
    rated_issue_count = len(ratings)
    average = _average_or_none(ratings)

    if rated_issue_count:
        total_points = sum(ratings)
        average_display = round(total_points / rated_issue_count, 2)
        calculation = (
            f"{thread_title}: {_plural(issue_count, 'attributed issue')}, "
            f"{_plural(rated_issue_count, 'with effective rating')}; "
            f"{_format_points(total_points)} rating points ÷ "
            f"{_plural(rated_issue_count, 'rated issue')} = {average_display:.2f}★"
        )
    else:
        calculation = (
            f"{thread_title}: {_plural(issue_count, 'attributed issue')}, none rated yet."
        )

    page, next_cursor = _evidence_page(rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role) for issue_id, rating, role in page]

    return CreatorSeriesAverageDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=issue_count,
        next_cursor=next_cursor,
        thread_id=thread_id,
        thread_title=thread_title or series_key,
        issue_count=issue_count,
        rated_issue_count=rated_issue_count,
        average_rating=average,
        min_rated_issues_per_series=MIN_RATED_ISSUES_PER_SERIES,
        issues=issues,
    )


async def get_read_without_rating_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorReadWithoutRatingDrilldownResponse:
    """Evidence page for the read-without-rating count (issue #3176).

    This is the primary data-quality debugging surface: the count matches the
    summary ``read_unrated_count`` exactly because both count attributed
    issues that are marked read without an effective rating. Per-issue cause
    classification does not exist yet (issue #3175), so the response says so
    explicitly instead of implying a known cause. Partial creator metadata is
    never treated as negative attribution evidence: an issue appears here
    only when the creator is actually credited on it.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded read-without-rating evidence page.

    Raises:
        ValueError: When the creator key or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, _headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    rows = [
        (
            issue_id,
            None,
            _creator_role_on(inputs.issue_creator_credits.get(issue_id, ()), creator_id),
        )
        for issue_id in sorted(issue_ids)
        if inputs.owned_issues.get(issue_id) == "read"
        and issue_id not in inputs.effective_ratings
    ]
    count = len(rows)

    if count:
        calculation = (
            f"{_plural(count, 'attributed issue')} marked read with no effective rating "
            "event; the reason each rating is missing has not been classified yet"
        )
    else:
        calculation = "Every attributed issue marked read also has an effective rating."

    page, next_cursor = _evidence_page(rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role) for issue_id, rating, role in page]

    return CreatorReadWithoutRatingDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=count,
        next_cursor=next_cursor,
        count=count,
        classification_available=False,
        issues=issues,
    )


async def get_unread_drilldown(
    db: AsyncSession,
    user_id: int,
    creator_key: str,
    *,
    limit: int = DRILLDOWN_PAGE_SIZE_DEFAULT,
    cursor: str | None = None,
) -> CreatorUnreadDrilldownResponse:
    """Evidence page for the unread/attributed-unread count (issue #3176).

    The count matches the summary ``unread_upcoming_count`` exactly because
    both count attributed issues whose read status is still unread.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the library.
        creator_key: Canonical creator key.
        limit: Bounded page size.
        cursor: Opaque cursor from a previous page.

    Returns:
        The bounded unread evidence page.

    Raises:
        ValueError: When the creator key or cursor is malformed.
        KeyError: When the creator is not attributed in the user's library.
    """
    creator_id = _require_creator_key(creator_key)
    inputs = await _get_creator_drilldown_inputs(db, user_id, creator_id)
    issue_ids, _headline_issue_ids, _roles, _name = _creator_profile(inputs, creator_id)
    if not issue_ids:
        raise KeyError(creator_key)

    rows: list[EvidenceRow] = []
    for issue_id in sorted(issue_ids):
        if inputs.owned_issues.get(issue_id) != "unread":
            continue
        rows.append(
            (
                issue_id,
                inputs.effective_ratings.get(issue_id),
                _creator_role_on(inputs.issue_creator_credits.get(issue_id, ()), creator_id),
            )
        )
    count = len(rows)

    if count:
        calculation = (
            f"{_plural(count, 'attributed issue')} still unread in ComicPile; these are "
            "upcoming for this creator, not missing reads"
        )
    else:
        calculation = "Every attributed issue has already been read."

    page, next_cursor = _evidence_page(rows, limit, cursor)
    issues = [_drilldown_issue(inputs, issue_id, rating, role) for issue_id, rating, role in page]

    return CreatorUnreadDrilldownResponse(
        creator_key=f"creator:{creator_id}",
        calculation=calculation,
        total_count=count,
        next_cursor=next_cursor,
        count=count,
        issues=issues,
    )


__all__ = [
    "DRILLDOWN_PAGE_SIZE_DEFAULT",
    "DRILLDOWN_PAGE_SIZE_MAX",
    "get_creator_comparison",
    "get_average_drilldown",
    "get_median_drilldown",
    "get_rating_distribution_drilldown",
    "get_5_star_rate_drilldown",
    "get_role_average_drilldown",
    "get_series_average_drilldown",
    "get_read_without_rating_drilldown",
    "get_unread_drilldown",
]
