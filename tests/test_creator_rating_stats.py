"""Unit coverage for deterministic creator rating distribution buckets."""

import pytest

from app.services.creator_rating_stats import (
    RATING_BUCKETS,
    bucket_for_rating,
    compute_rating_distribution,
)


def test_bucket_snapping_matches_half_star_scale() -> None:
    """Half-step ratings keep their bucket; off-grid values snap nearest."""
    assert bucket_for_rating(4.5) == 4.5
    assert bucket_for_rating(3.0) == 3.0
    assert bucket_for_rating(3.74) == 3.5
    assert bucket_for_rating(3.76) == 4.0
    assert bucket_for_rating(0.1) == 0.5
    assert bucket_for_rating(9.0) == 5.0


def test_distribution_bucket_shape_and_stats() -> None:
    """Buckets cover the full scale, median/mean/min/max are exact."""
    dist = compute_rating_distribution([5.0, 4.5, 4.5, 2.0, 1.0])
    assert dist is not None
    assert [b.rating for b in dist.buckets] == list(RATING_BUCKETS)
    assert dist.sample_count == 5
    assert dist.min_rating == 1.0
    assert dist.max_rating == 5.0
    assert dist.median_rating == pytest.approx(4.5)
    assert dist.mean_rating == pytest.approx(3.4)


def test_distribution_empty_is_null_not_zero() -> None:
    """No eligible ratings means ``null``, never a zeroed object."""
    assert compute_rating_distribution([]) is None
