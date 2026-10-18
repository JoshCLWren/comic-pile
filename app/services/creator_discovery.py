"""Explainable personal taste-discovery views (issue #3093).

Discovery answers questions a plain creator directory cannot: which creators are
consistently good *for this user*, which are polarizing, which are read the
most, which are promising on thin evidence, which are loved but still have
unread work, and which the user has warmed to or cooled on over time.

Every definition is deterministic and derived only from the authenticated
user's own latest effective ratings and confirmed creator credits, reusing the
canonical creator identity and rating semantics of ``#2028``/``#2037``. No
provider request, no LLM ranking, and no precomputed table participates; the
whole response is pure in-memory work over the already-loaded user-scoped
:class:`~app.repositories.creator_summary.CreatorSummaryInputs`.

Definitions (all thresholds live in :mod:`app.constants`):

- ``consistently_loved``: ``rated_issue_count >= 3`` and
  ``average_rating >= 4.0`` and population ``rating_stddev <= 0.5``.
- ``polarizing``: ``rated_issue_count >= 3`` and
  ``rating_spread = max - min >= 2.0``.
- ``most_read``: ``rated_issue_count >= 1`` (any rated creator).
- ``highest_top_rating_rate``: ``rated_issue_count >= 3`` and the proportion of
  ratings at the top of the scale (``5.0``) ``>= 0.6``.
- ``great_average_small_sample``: ``1 <= rated_issue_count <= 2`` and
  ``average_rating >= 4.0`` — explicitly below the reliability floor.
- ``loved_with_unread``: ``rated_issue_count >= 1`` and
  ``average_rating >= 4.0`` and at least one attributed unread owned issue.
- ``moved_over_time``: at least ``6`` rated issues carrying a rating timestamp;
  the history is split into earlier and recent halves and the change between the
  half averages must reach ``0.5`` in either direction.

Within every view results are ordered deterministically with the canonical
creator key as the final tie-breaker, so equal-score creators never reorder
between requests. Views are bounded to
:data:`~app.constants.MAX_DISCOVERY_ENTRIES` entries each; the unbounded count
is still reported so the UI can say how many qualified.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, median, pstdev

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    CONSISTENCY_LOVED_MAX_STDDEV,
    CONSISTENCY_LOVED_MIN_AVERAGE,
    DISCOVERY_MIN_RELIABLE_SAMPLE,
    LOVED_WITH_UNREAD_MIN_AVERAGE,
    MAX_DISCOVERY_ENTRIES,
    POLARIZING_MIN_SPREAD,
    SMALL_SAMPLE_MAX,
    SMALL_SAMPLE_MIN_AVERAGE,
    TOP_RATING_RATE_MIN_PROPORTION,
    TOP_RATING_VALUE,
    TREND_MIN_DELTA,
    TREND_MIN_SAMPLE,
)
from app.repositories.creator_summary import (
    CreatorSummaryInputs,
    load_creator_summary_inputs,
)
from app.schemas.creator_discovery import (
    CreatorDiscoveryCoverage,
    CreatorDiscoveryEntry,
    CreatorDiscoveryMode,
    CreatorDiscoveryReason,
    CreatorDiscoveryResponse,
    CreatorDiscoveryView,
)
from app.services.creator_summary import HEADLINE_ROLES

#: Human-readable title and deterministic explanation for every view. Kept next
#: to the builder so the copy and the enforced rule cannot drift apart.
_VIEW_COPY: dict[CreatorDiscoveryMode, tuple[str, str, int]] = {
    CreatorDiscoveryMode.CONSISTENTLY_LOVED: (
        "Most consistently loved",
        "High personal average with at least "
        f"{DISCOVERY_MIN_RELIABLE_SAMPLE} rated issues and a standard deviation of "
        f"{CONSISTENCY_LOVED_MAX_STDDEV} or less.",
        DISCOVERY_MIN_RELIABLE_SAMPLE,
    ),
    CreatorDiscoveryMode.POLARIZING: (
        "Most polarizing",
        "At least "
        f"{DISCOVERY_MIN_RELIABLE_SAMPLE} rated issues with a spread of "
        f"{POLARIZING_MIN_SPREAD} or more between the lowest and highest rating.",
        DISCOVERY_MIN_RELIABLE_SAMPLE,
    ),
    CreatorDiscoveryMode.MOST_READ: (
        "Most read",
        "Creators with the largest rated sample in your library.",
        1,
    ),
    CreatorDiscoveryMode.HIGHEST_TOP_RATING_RATE: (
        "Highest top-rating rate",
        f"At least {DISCOVERY_MIN_RELIABLE_SAMPLE} rated issues with "
        f"{int(TOP_RATING_RATE_MIN_PROPORTION * 100)}% or more at the top of your scale.",
        DISCOVERY_MIN_RELIABLE_SAMPLE,
    ),
    CreatorDiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE: (
        "Great average, small sample",
        f"An average of {SMALL_SAMPLE_MIN_AVERAGE} or more from "
        f"{SMALL_SAMPLE_MAX} rated issues or fewer — promising, but not yet proven.",
        1,
    ),
    CreatorDiscoveryMode.LOVED_WITH_UNREAD: (
        "Loved creators with unread work",
        f"An average of {LOVED_WITH_UNREAD_MIN_AVERAGE} or more with unread issues still in your pile.",
        1,
    ),
    CreatorDiscoveryMode.MOVED_OVER_TIME: (
        "Warmed to / cooled on",
        f"At least {TREND_MIN_SAMPLE} dated ratings where the recent half averages "
        f"{TREND_MIN_DELTA} or more away from the earlier half.",
        TREND_MIN_SAMPLE,
    ),
}


@dataclass(frozen=True)
class _CreatorProfile:
    """One creator's fully computed discovery metrics.

    Attributes:
        canonical_creator_key: Stable ``creator:<id>`` key.
        display_name: Latest confirmed display name.
        normalized_roles: Sorted distinct confirmed roles.
        rated_issue_count: Headline-eligible rated sample size.
        average_rating: Mean of the rated sample, or ``None`` when unrated.
        median_rating: Median of the rated sample, or ``None`` when unrated.
        rating_stddev: Population standard deviation, or ``None`` when unrated.
        rating_spread: Max minus min rating, or ``None`` when unrated.
        min_rating: Lowest effective rating, or ``None`` when unrated.
        max_rating: Highest effective rating, or ``None`` when unrated.
        top_rating_count: Ratings at the top of the scale.
        top_rating_rate: Proportion at the top of the scale, or ``None``.
        unread_issue_count: Attributed unread owned issues.
        read_unrated_issue_count: Attributed read-but-unrated owned issues.
        trend_points: ``(timestamp, issue_id, rating)`` for every rated issue
            carrying a timestamp, ascending by timestamp then issue id.
    """

    canonical_creator_key: str
    display_name: str
    normalized_roles: tuple[str, ...]
    rated_issue_count: int
    average_rating: float | None
    median_rating: float | None
    rating_stddev: float | None
    rating_spread: float | None
    min_rating: float | None
    max_rating: float | None
    top_rating_count: int
    top_rating_rate: float | None
    unread_issue_count: int
    read_unrated_issue_count: int
    trend_points: tuple[tuple[datetime, int, float], ...]


def _build_profiles(inputs: CreatorSummaryInputs) -> list[_CreatorProfile]:
    """Compute every discovery metric once per creator.

    Args:
        inputs: User-scoped creator summary inputs.

    Returns:
        Profiles for every creator with at least one confirmed credit, ordered
        by canonical creator key for a stable base iteration order.
    """
    creator_issue_ids: dict[int, set[int]] = defaultdict(set)
    creator_roles: dict[int, set[str]] = defaultdict(set)
    creator_names: dict[int, str] = {}
    creator_headline_issues: dict[int, set[int]] = defaultdict(set)

    for issue_id, credits in inputs.issue_creator_credits.items():
        for credit in credits:
            creator_id = credit.external_id
            creator_issue_ids[creator_id].add(issue_id)
            creator_names.setdefault(creator_id, credit.display_name)
            creator_roles[creator_id].update(credit.roles)
            if any(role in HEADLINE_ROLES for role in credit.roles):
                creator_headline_issues[creator_id].add(issue_id)

    profiles: list[_CreatorProfile] = []
    for creator_id, issue_ids in creator_issue_ids.items():
        rated_issue_ids = sorted(
            issue_id
            for issue_id in issue_ids
            if issue_id in creator_headline_issues[creator_id]
            and issue_id in inputs.effective_ratings
        )
        ratings = [inputs.effective_ratings[issue_id] for issue_id in rated_issue_ids]
        rated_issue_count = len(ratings)

        average_rating: float | None = None
        median_rating: float | None = None
        rating_stddev: float | None = None
        rating_spread: float | None = None
        min_rating: float | None = None
        max_rating: float | None = None
        if ratings:
            average_rating = round(mean(ratings), 2)
            median_rating = round(median(ratings), 2)
            rating_stddev = round(pstdev(ratings), 2) if len(ratings) > 1 else 0.0
            min_rating = min(ratings)
            max_rating = max(ratings)
            rating_spread = round(max_rating - min_rating, 2)

        top_rating_count = sum(1 for rating in ratings if rating >= TOP_RATING_VALUE)
        top_rating_rate = (
            round(top_rating_count / rated_issue_count, 3) if rated_issue_count else None
        )

        unread_issue_count = sum(
            1 for issue_id in issue_ids if inputs.owned_issues.get(issue_id) == "unread"
        )
        read_unrated_issue_count = sum(
            1
            for issue_id in issue_ids
            if inputs.owned_issues.get(issue_id) == "read"
            and issue_id not in inputs.effective_ratings
        )

        trend_points = tuple(
            sorted(
                (
                    (
                        inputs.effective_rating_timestamps[issue_id],
                        issue_id,
                        inputs.effective_ratings[issue_id],
                    )
                    for issue_id in rated_issue_ids
                    if issue_id in inputs.effective_rating_timestamps
                ),
                key=lambda point: (point[0], point[1]),
            )
        )

        profiles.append(
            _CreatorProfile(
                canonical_creator_key=f"creator:{creator_id}",
                display_name=creator_names[creator_id],
                normalized_roles=tuple(sorted(creator_roles[creator_id])),
                rated_issue_count=rated_issue_count,
                average_rating=average_rating,
                median_rating=median_rating,
                rating_stddev=rating_stddev,
                rating_spread=rating_spread,
                min_rating=min_rating,
                max_rating=max_rating,
                top_rating_count=top_rating_count,
                top_rating_rate=top_rating_rate,
                unread_issue_count=unread_issue_count,
                read_unrated_issue_count=read_unrated_issue_count,
                trend_points=trend_points,
            )
        )

    profiles.sort(key=lambda profile: profile.canonical_creator_key)
    return profiles


def _reason(
    metric: str,
    label: str,
    value: float,
    threshold: float,
    comparison: str,
) -> CreatorDiscoveryReason:
    """Build one structured qualification reason."""
    return CreatorDiscoveryReason(
        metric=metric,
        label=label,
        value=round(float(value), 3),
        threshold=round(float(threshold), 3),
        comparison=comparison,
    )


def _entry(
    profile: _CreatorProfile,
    *,
    reasons: list[CreatorDiscoveryReason],
    trend_direction: str | None = None,
    earlier_average_rating: float | None = None,
    recent_average_rating: float | None = None,
    trend_delta: float | None = None,
    trend_sample_count: int = 0,
) -> CreatorDiscoveryEntry:
    """Project one profile into a discovery entry for a specific view."""
    return CreatorDiscoveryEntry(
        canonical_creator_key=profile.canonical_creator_key,
        display_name=profile.display_name,
        normalized_roles=list(profile.normalized_roles),
        rated_issue_count=profile.rated_issue_count,
        average_rating=profile.average_rating,
        median_rating=profile.median_rating,
        rating_stddev=profile.rating_stddev,
        rating_spread=profile.rating_spread,
        min_rating=profile.min_rating,
        max_rating=profile.max_rating,
        top_rating_rate=profile.top_rating_rate,
        top_rating_count=profile.top_rating_count,
        unread_issue_count=profile.unread_issue_count,
        read_unrated_issue_count=profile.read_unrated_issue_count,
        trend_direction=trend_direction,
        earlier_average_rating=earlier_average_rating,
        recent_average_rating=recent_average_rating,
        trend_delta=trend_delta,
        trend_sample_count=trend_sample_count,
        reasons=reasons,
    )


def _consistently_loved(profiles: list[_CreatorProfile]) -> list[CreatorDiscoveryEntry]:
    """Creators with a high personal average and low dispersion."""
    scored: list[tuple[tuple[float, float, int, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        if profile.rated_issue_count < DISCOVERY_MIN_RELIABLE_SAMPLE:
            continue
        average = profile.average_rating
        stddev = profile.rating_stddev
        if average is None or stddev is None:
            continue
        if average < CONSISTENCY_LOVED_MIN_AVERAGE or stddev > CONSISTENCY_LOVED_MAX_STDDEV:
            continue
        reasons = [
            _reason(
                "average_rating", "average rating", average, CONSISTENCY_LOVED_MIN_AVERAGE, "gte"
            ),
            _reason(
                "rating_stddev",
                "rating standard deviation",
                stddev,
                CONSISTENCY_LOVED_MAX_STDDEV,
                "lte",
            ),
            _reason(
                "rated_issue_count",
                "rated issues",
                profile.rated_issue_count,
                DISCOVERY_MIN_RELIABLE_SAMPLE,
                "gte",
            ),
        ]
        key = (-average, stddev, -profile.rated_issue_count, profile.canonical_creator_key)
        scored.append((key, _entry(profile, reasons=reasons)))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


def _polarizing(profiles: list[_CreatorProfile]) -> list[CreatorDiscoveryEntry]:
    """Creators whose ratings span a wide range on a meaningful sample."""
    scored: list[tuple[tuple[float, float, int, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        if profile.rated_issue_count < DISCOVERY_MIN_RELIABLE_SAMPLE:
            continue
        spread = profile.rating_spread
        stddev = profile.rating_stddev
        if spread is None or stddev is None:
            continue
        if spread < POLARIZING_MIN_SPREAD:
            continue
        reasons = [
            _reason("rating_spread", "rating spread", spread, POLARIZING_MIN_SPREAD, "gte"),
            _reason(
                "rated_issue_count",
                "rated issues",
                profile.rated_issue_count,
                DISCOVERY_MIN_RELIABLE_SAMPLE,
                "gte",
            ),
        ]
        key = (-stddev, -spread, -profile.rated_issue_count, profile.canonical_creator_key)
        scored.append((key, _entry(profile, reasons=reasons)))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


def _most_read(profiles: list[_CreatorProfile]) -> list[CreatorDiscoveryEntry]:
    """Creators with the largest rated sample in the library."""
    scored: list[tuple[tuple[int, float, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        if profile.rated_issue_count < 1:
            continue
        reasons = [
            _reason("rated_issue_count", "rated issues", profile.rated_issue_count, 1, "gte"),
        ]
        key = (
            -profile.rated_issue_count,
            -(profile.average_rating or 0.0),
            profile.canonical_creator_key,
        )
        scored.append((key, _entry(profile, reasons=reasons)))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


def _highest_top_rating_rate(profiles: list[_CreatorProfile]) -> list[CreatorDiscoveryEntry]:
    """Creators with the highest proportion of top-of-scale ratings."""
    scored: list[tuple[tuple[float, int, float, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        if profile.rated_issue_count < DISCOVERY_MIN_RELIABLE_SAMPLE:
            continue
        top_rate = profile.top_rating_rate
        if top_rate is None or top_rate < TOP_RATING_RATE_MIN_PROPORTION:
            continue
        reasons = [
            _reason(
                "top_rating_rate",
                "top-rating rate",
                top_rate,
                TOP_RATING_RATE_MIN_PROPORTION,
                "gte",
            ),
            _reason(
                "rated_issue_count",
                "rated issues",
                profile.rated_issue_count,
                DISCOVERY_MIN_RELIABLE_SAMPLE,
                "gte",
            ),
        ]
        key = (
            -top_rate,
            -profile.rated_issue_count,
            -(profile.average_rating or 0.0),
            profile.canonical_creator_key,
        )
        scored.append((key, _entry(profile, reasons=reasons)))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


def _great_average_small_sample(
    profiles: list[_CreatorProfile],
) -> list[CreatorDiscoveryEntry]:
    """Promising creators whose evidence is still below the reliability floor."""
    scored: list[tuple[tuple[float, int, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        if not (1 <= profile.rated_issue_count <= SMALL_SAMPLE_MAX):
            continue
        average = profile.average_rating
        if average is None or average < SMALL_SAMPLE_MIN_AVERAGE:
            continue
        reasons = [
            _reason(
                "average_rating",
                "average rating",
                average,
                SMALL_SAMPLE_MIN_AVERAGE,
                "gte",
            ),
            _reason(
                "rated_issue_count",
                "rated issues",
                profile.rated_issue_count,
                SMALL_SAMPLE_MAX,
                "lte",
            ),
        ]
        key = (-average, -profile.rated_issue_count, profile.canonical_creator_key)
        scored.append((key, _entry(profile, reasons=reasons)))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


def _loved_with_unread(profiles: list[_CreatorProfile]) -> list[CreatorDiscoveryEntry]:
    """Highly rated creators who still have unread work in the library."""
    scored: list[tuple[tuple[int, float, int, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        if profile.rated_issue_count < 1 or profile.unread_issue_count < 1:
            continue
        average = profile.average_rating
        if average is None or average < LOVED_WITH_UNREAD_MIN_AVERAGE:
            continue
        reasons = [
            _reason(
                "average_rating",
                "average rating",
                average,
                LOVED_WITH_UNREAD_MIN_AVERAGE,
                "gte",
            ),
            _reason(
                "unread_issue_count", "unread issues", profile.unread_issue_count, 1, "gte"
            ),
        ]
        key = (
            -profile.unread_issue_count,
            -average,
            -profile.rated_issue_count,
            profile.canonical_creator_key,
        )
        scored.append((key, _entry(profile, reasons=reasons)))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


def _moved_over_time(profiles: list[_CreatorProfile]) -> list[CreatorDiscoveryEntry]:
    """Creators the user has warmed to or cooled on across dated ratings."""
    scored: list[tuple[tuple[float, int, str], CreatorDiscoveryEntry]] = []
    for profile in profiles:
        points = profile.trend_points
        if len(points) < TREND_MIN_SAMPLE:
            continue
        midpoint = len(points) // 2
        earlier = [rating for _timestamp, _issue_id, rating in points[:midpoint]]
        recent = [rating for _timestamp, _issue_id, rating in points[midpoint:]]
        earlier_average = round(mean(earlier), 2)
        recent_average = round(mean(recent), 2)
        delta = round(recent_average - earlier_average, 2)
        if abs(delta) < TREND_MIN_DELTA:
            continue
        direction = "warmed" if delta > 0 else "cooled"
        reasons = [
            _reason("trend_delta", "change in average", abs(delta), TREND_MIN_DELTA, "gte"),
            _reason(
                "trend_sample_count",
                "dated rated issues",
                len(points),
                TREND_MIN_SAMPLE,
                "gte",
            ),
        ]
        entry = _entry(
            profile,
            reasons=reasons,
            trend_direction=direction,
            earlier_average_rating=earlier_average,
            recent_average_rating=recent_average,
            trend_delta=delta,
            trend_sample_count=len(points),
        )
        key = (-abs(delta), -len(points), profile.canonical_creator_key)
        scored.append((key, entry))
    scored.sort(key=lambda item: item[0])
    return [entry for _key, entry in scored]


#: Signature shared by every view builder.
_DiscoveryBuilder = Callable[[list[_CreatorProfile]], list[CreatorDiscoveryEntry]]

#: Every mode paired with its deterministic builder, in canonical display order.
_BUILDERS: tuple[tuple[CreatorDiscoveryMode, _DiscoveryBuilder], ...] = (
    (CreatorDiscoveryMode.CONSISTENTLY_LOVED, _consistently_loved),
    (CreatorDiscoveryMode.POLARIZING, _polarizing),
    (CreatorDiscoveryMode.MOST_READ, _most_read),
    (CreatorDiscoveryMode.HIGHEST_TOP_RATING_RATE, _highest_top_rating_rate),
    (CreatorDiscoveryMode.GREAT_AVERAGE_SMALL_SAMPLE, _great_average_small_sample),
    (CreatorDiscoveryMode.LOVED_WITH_UNREAD, _loved_with_unread),
    (CreatorDiscoveryMode.MOVED_OVER_TIME, _moved_over_time),
)


def _build_view(
    mode: CreatorDiscoveryMode,
    entries: list[CreatorDiscoveryEntry],
) -> CreatorDiscoveryView:
    """Bound one view's entries and attach its deterministic copy."""
    title, description, min_sample = _VIEW_COPY[mode]
    bounded = entries[:MAX_DISCOVERY_ENTRIES]
    return CreatorDiscoveryView(
        mode=mode,
        title=title,
        description=description,
        min_sample=min_sample,
        total=len(entries),
        truncated=len(entries) > len(bounded),
        max_entries=MAX_DISCOVERY_ENTRIES,
        entries=bounded,
    )


async def get_creator_discoveries(
    db: AsyncSession,
    user_id: int,
) -> CreatorDiscoveryResponse:
    """Compute bounded, explainable personal taste-discovery views.

    Args:
        db: Async database session.
        user_id: Authenticated user owning the aggregated library.

    Returns:
        One bounded view per discovery mode in canonical order, plus explicit
        metadata-coverage state. Every view is present even when empty.
    """
    inputs = await load_creator_summary_inputs(db, user_id)
    profiles = _build_profiles(inputs)

    rated_issue_ids = frozenset(inputs.effective_ratings)
    rated_with_metadata = rated_issue_ids & inputs.issues_with_creator_metadata
    coverage = CreatorDiscoveryCoverage(
        rated_issues_total=len(rated_issue_ids),
        rated_issues_with_creator_metadata=len(rated_with_metadata),
        ratings_complete=len(rated_with_metadata) >= len(rated_issue_ids),
    )

    views: list[CreatorDiscoveryView] = []
    for mode, builder in _BUILDERS:
        entries = builder(profiles)
        views.append(_build_view(mode, entries))

    return CreatorDiscoveryResponse(
        views=views,
        coverage=coverage,
        minimum_reliable_sample=DISCOVERY_MIN_RELIABLE_SAMPLE,
        max_entries_per_view=MAX_DISCOVERY_ENTRIES,
    )


__all__ = [
    "get_creator_discoveries",
]
