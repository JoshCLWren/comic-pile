"""Deterministic creator rating-distribution statistics (issue #3087).

Comic Pile ratings are real numbers on a 0.5–5.0 scale (``app/schemas/rate.py``
bounds ratings to that range). Distribution buckets match the product's real
granularity: one bucket per half-star step from 0.5 to 5.0. Off-grid values
are snapped deterministically to the nearest half-star step.

"""

from __future__ import annotations

from statistics import mean, median

from app.schemas.creator_detail import (
    CreatorRatingBucket,
    CreatorRatingDistribution,
)

#: One bucket per half-star step on the actual product rating scale (0.5–5.0).
RATING_BUCKETS: tuple[float, ...] = tuple(0.5 * step for step in range(1, 11))


def bucket_for_rating(value: float) -> float:
    """Snap a rating to the nearest half-star bucket (deterministic ties-to-even).

    Args:
        value: An observed effective rating on the 0.5–5.0 product scale.

    Returns:
        The bucket center, clamped to [0.5, 5.0].
    """
    snapped = round(value * 2) / 2
    return min(max(snapped, 0.5), 5.0)


def compute_rating_distribution(ratings: list[float]) -> CreatorRatingDistribution | None:
    """Compute headline rating distribution statistics for one creator.

    Args:
        ratings: Latest effective ratings, one per issue, already scoped to
            headline-eligible roles (one issue contributes at most once).

    Returns:
        The distribution, or ``None`` when there are no eligible ratings —
        ``null`` means no eligible ratings, never zero counts.
    """
    if not ratings:
        return None
    counts: dict[float, int] = dict.fromkeys(RATING_BUCKETS, 0)
    for value in ratings:
        counts[bucket_for_rating(value)] += 1
    buckets = [CreatorRatingBucket(rating=bucket, count=counts[bucket]) for bucket in RATING_BUCKETS]
    return CreatorRatingDistribution(
        buckets=buckets,
        sample_count=len(ratings),
        mean_rating=round(mean(ratings), 2),
        median_rating=round(median(ratings), 2),
        min_rating=min(ratings),
        max_rating=max(ratings),
    )


__all__ = [
    "RATING_BUCKETS",
    "bucket_for_rating",
    "compute_rating_distribution",
]
