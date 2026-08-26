"""Tests for robust reading-effort aggregation (issue #1702)."""

import math

import pytest

from comic_pile.reading_effort import (
    DEFAULT_MIN_TRUSTED_SAMPLE_COUNT,
    EffortObservation,
    EffortSource,
    EffortSummary,
    aggregate_efforts,
    estimate_issue_effort,
    median,
    resolve_issue_effort,
)


def _observation(
    thread_id: int,
    issue_id: int | None,
    duration_seconds: float,
) -> EffortObservation:
    """Build one validated observation for tests."""
    return EffortObservation(
        thread_id=thread_id,
        issue_id=issue_id,
        duration_seconds=duration_seconds,
    )


def _phase_one_exclusion_reason(duration_seconds: float) -> str | None:
    """Return a reason code when a duration would be excluded by #1701 rules."""
    if duration_seconds < 60.0:
        return "implausibly_short"
    if duration_seconds > 21600.0:
        return "implausibly_long"
    return None


def _apply_phase_one_rules(durations: list[float]) -> list[float]:
    """Keep only durations surviving the #1701 validity rules."""
    return [d for d in durations if _phase_one_exclusion_reason(d) is None]


def test_median_odd_and_even_counts() -> None:
    """Odd pools return the middle value; even pools average the middle pair."""
    assert median([5.0]) == 5.0
    assert median([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert median([4.0, 1.0, 3.0, 2.0]) == 2.5


def test_median_requires_at_least_one_value() -> None:
    """Empty input is a programming error, not a zero effort estimate."""
    with pytest.raises(ValueError, match="at least one value"):
        median([])


def test_repeated_valid_reads_produce_deterministic_median_estimate() -> None:
    """Identical observation multisets yield identical estimates regardless of order."""
    ordered = [
        _observation(7, 11, 600.0),
        _observation(7, 11, 900.0),
        _observation(7, 11, 750.0),
    ]
    shuffled = [
        _observation(7, 11, 900.0),
        _observation(7, 11, 750.0),
        _observation(7, 11, 600.0),
    ]

    first_summary = aggregate_efforts(ordered)
    second_summary = aggregate_efforts(reversed(shuffled))

    assert first_summary == second_summary

    issue_estimate = first_summary.issues[11]
    assert issue_estimate.median_seconds == 750.0
    assert issue_estimate.sample_count == 3
    assert issue_estimate.source == EffortSource.ISSUE
    assert issue_estimate.trusted is True

    resolved_first = estimate_issue_effort(ordered, issue_id=11, thread_id=7)
    resolved_second = estimate_issue_effort(shuffled, issue_id=11, thread_id=7)
    assert resolved_first == resolved_second
    assert resolved_first is not None
    assert resolved_first.median_seconds == 750.0


def test_outliers_excluded_by_phase_one_rules_do_not_affect_estimate() -> None:
    """Durations rejected by the #1701 contract never reach the aggregation."""
    raw_durations = [
        45.0,
        600.0,
        720.0,
        540.0,
        172800.0,
        660.0,
    ]

    exclusions = {
        _phase_one_exclusion_reason(d) for d in raw_durations if _phase_one_exclusion_reason(d)
    }
    assert exclusions == {"implausibly_short", "implausibly_long"}

    valid_durations = _apply_phase_one_rules(raw_durations)
    assert valid_durations == [600.0, 720.0, 540.0, 660.0]

    observations = [_observation(7, 11, d) for d in valid_durations]
    estimate = estimate_issue_effort(observations, issue_id=11, thread_id=7)

    assert estimate is not None
    assert estimate.median_seconds == 630.0
    assert estimate.sample_count == 4
    assert estimate.trusted is True

    clean_only = estimate_issue_effort(
        [_observation(7, 11, d) for d in [600.0, 720.0, 540.0, 660.0]],
        issue_id=11,
        thread_id=7,
    )
    assert estimate == clean_only


def test_median_resists_residual_extreme_value_in_sufficient_pool() -> None:
    """A lone extreme survivor shifts the median by one rank, not off center."""
    clean = [500.0, 550.0, 600.0, 650.0, 700.0]
    contaminated = clean + [400000.0]

    clean_observations = [_observation(7, 11, d) for d in clean]
    contaminated_observations = [_observation(7, 11, d) for d in contaminated]

    clean_estimate = estimate_issue_effort(clean_observations, issue_id=11, thread_id=7)
    noisy_estimate = estimate_issue_effort(contaminated_observations, issue_id=11, thread_id=7)

    assert clean_estimate is not None
    assert noisy_estimate is not None
    assert clean_estimate.median_seconds == 600.0
    assert noisy_estimate.median_seconds == 625.0
    assert noisy_estimate.sample_count == 6


def test_estimates_expose_sample_count_and_confidence_and_source() -> None:
    """Every estimate carries its evidence size, confidence label, and source pool."""
    observations = [
        _observation(7, 11, 600.0),
        _observation(7, 11, 700.0),
        _observation(7, 11, 800.0),
        _observation(8, None, 100.0),
    ]

    summary = aggregate_efforts(observations)

    issue_estimate = summary.issues[11]
    assert issue_estimate.sample_count == 3
    assert issue_estimate.source == EffortSource.ISSUE
    assert issue_estimate.source == "issue"
    assert issue_estimate.trusted is True
    assert issue_estimate.confidence == "observed"

    sparse_thread_estimate = summary.threads[8]
    assert sparse_thread_estimate.sample_count == 1
    assert sparse_thread_estimate.source == EffortSource.THREAD
    assert sparse_thread_estimate.source == "thread"
    assert sparse_thread_estimate.trusted is False
    assert sparse_thread_estimate.confidence == "sparse"


def test_no_data_produces_no_estimates_and_no_certainty() -> None:
    """Empty history yields empty indexes and ``None``, never a fake estimate."""
    summary = aggregate_efforts([])
    assert summary.threads == {}
    assert summary.issues == {}

    assert estimate_issue_effort([], issue_id=11, thread_id=7) is None

    empty_resolution = resolve_issue_effort(
        summary=EffortSummary(threads={}, issues={}),
        issue_id=11,
        thread_id=7,
    )
    assert empty_resolution is None


def test_sparse_issue_data_falls_back_to_trusted_thread_history() -> None:
    """Two issue reads below the minimum defer to an established series history."""
    observations = [
        _observation(7, 11, 480.0),
        _observation(7, 11, 540.0),
        _observation(7, 12, 900.0),
        _observation(7, 12, 960.0),
        _observation(7, 12, 1020.0),
    ]

    summary = aggregate_efforts(observations)

    issue_estimate = summary.issues[11]
    assert issue_estimate.trusted is False
    assert issue_estimate.confidence == "sparse"

    resolved = resolve_issue_effort(summary=summary, issue_id=11, thread_id=7)
    assert resolved is not None
    assert resolved.source == EffortSource.THREAD
    assert resolved.trusted is True
    assert resolved.confidence == "observed"
    assert resolved.sample_count == 5
    assert resolved.median_seconds == 900.0


def test_sparse_everywhere_reports_untrusted_instead_of_inventing_certainty() -> None:
    """Below-minimum pools stay visible but explicitly untrusted."""
    observations = [
        _observation(8, None, 300.0),
        _observation(8, None, 360.0),
    ]

    resolved = estimate_issue_effort(observations, issue_id=13, thread_id=8)
    assert resolved is not None
    assert resolved.source == EffortSource.THREAD
    assert resolved.trusted is False
    assert resolved.confidence == "sparse"
    assert resolved.sample_count == 2
    assert resolved.median_seconds == 330.0


def test_both_pools_sparse_prefers_most_specific_evidence_untrusted() -> None:
    """When neither pool meets the minimum, issue-level evidence still wins."""
    observations = [
        _observation(9, 14, 1000.0),
        _observation(9, 14, 1400.0),
    ]

    resolved = estimate_issue_effort(observations, issue_id=14, thread_id=9)

    assert resolved is not None
    assert resolved.source == EffortSource.ISSUE
    assert resolved.trusted is False
    assert resolved.confidence == "sparse"
    assert resolved.median_seconds == 1200.0
    assert resolved.sample_count == 2


def test_sufficient_issue_evidence_preferred_over_thread_history() -> None:
    """A trusted issue estimate wins even when the thread pool is also rich."""
    observations = [
        _observation(7, 11, 1200.0),
        _observation(7, 11, 1260.0),
        _observation(7, 11, 1320.0),
        _observation(7, 11, 1380.0),
        _observation(7, 12, 300.0),
        _observation(7, 12, 320.0),
        _observation(7, 12, 340.0),
    ]

    resolved = estimate_issue_effort(observations, issue_id=11, thread_id=7)

    assert resolved is not None
    assert resolved.source == EffortSource.ISSUE
    assert resolved.trusted is True
    assert resolved.sample_count == 4
    assert resolved.median_seconds == 1290.0


def test_mixed_issue_and_thread_histories_partition_correctly() -> None:
    """Interleaved histories aggregate into exactly their own pools."""
    observations = [
        _observation(1, 101, 600.0),
        _observation(2, 201, 2400.0),
        _observation(1, 101, 660.0),
        _observation(2, 201, 2500.0),
        _observation(1, 102, 1200.0),
        _observation(2, None, 90.0),
        _observation(1, 101, 720.0),
        _observation(2, 201, 2600.0),
    ]

    summary = aggregate_efforts(observations)

    assert sorted(summary.threads) == [1, 2]
    assert sorted(summary.issues) == [101, 102, 201]

    thread_one = summary.threads[1]
    assert thread_one.sample_count == 4
    assert thread_one.median_seconds == 690.0
    assert thread_one.trusted is True

    thread_two = summary.threads[2]
    assert thread_two.sample_count == 4
    assert thread_two.median_seconds == 2450.0

    issue_101 = summary.issues[101]
    assert issue_101.sample_count == 3
    assert issue_101.median_seconds == 660.0

    issue_102 = summary.issues[102]
    assert issue_102.sample_count == 1
    assert issue_102.trusted is False

    legacy_resolution = resolve_issue_effort(summary=summary, issue_id=999, thread_id=2)
    assert legacy_resolution is not None
    assert legacy_resolution.source == EffortSource.THREAD
    assert legacy_resolution.median_seconds == 2450.0


def test_legacy_observations_without_issue_linkage_stay_thread_only() -> None:
    """Observations lacking issue ids contribute to threads but never invent issues."""
    summary = aggregate_efforts([_observation(8, None, 420.0)])

    assert summary.threads[8].sample_count == 1
    assert summary.issues == {}


def test_minimum_sample_default_is_documented_and_enforced() -> None:
    """The default gate is three readings and configurable per call."""
    assert DEFAULT_MIN_TRUSTED_SAMPLE_COUNT == 3

    single_read = [_observation(7, 11, 600.0)]

    strict = aggregate_efforts(single_read)
    assert strict.issues[11].trusted is False

    lenient = aggregate_efforts(single_read, min_trusted_sample_count=1)
    assert lenient.issues[11].trusted is True

    with pytest.raises(ValueError, match="at least 1"):
        aggregate_efforts(single_read, min_trusted_sample_count=0)


def test_invalid_observations_are_rejected_loudly() -> None:
    """Corrupt identifiers or durations fail fast instead of skewing estimates."""
    with pytest.raises(ValueError, match="thread_id must be positive"):
        _observation(0, 11, 600.0)
    with pytest.raises(ValueError, match="issue_id must be positive"):
        _observation(7, -3, 600.0)
    with pytest.raises(ValueError, match="finite and non-negative"):
        _observation(7, 11, -1.0)
    with pytest.raises(ValueError, match="finite and non-negative"):
        _observation(7, 11, math.nan)
    with pytest.raises(ValueError, match="finite and non-negative"):
        _observation(7, 11, math.inf)
