"""Table-driven tests for reading-effort observation validation rules.

These tests cover:
- Valid observations pass unchanged (included=True, reason_code=None).
- Implausibly short observations excluded with reason ``"too_short"``.
- Extreme long observations excluded with reason ``"too_long"``.
- Boundary behavior (values at thresholds, just below, just above).
- No mutation or deletion of original observations (pure classifier contract).
- Centralized thresholds are configurable without code changes.
"""

import pytest

from comic_pile.reading_effort_observation_rules import (
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_MIN_DURATION_SECONDS,
    DurationObservation,
    ObservationResult,
    ObservationThresholds,
    classify_reading_effort_observation,
    classify_reading_effort_observations,
)


# ---------------------------------------------------------------------------
# Table-driven boundary and classification cases
# ---------------------------------------------------------------------------

CLASSIFICATION_CASES: list[tuple[float, bool, str | None]] = [
    # (duration_seconds, expected_included, expected_reason_code)
    # Normal valid observations
    (30.0, True, None),
    (60.0, True, None),
    (300.0, True, None),
    (600.0, True, None),
    (3600.0, True, None),
    (14400.0, True, None),
    # Boundary: just below min → excluded (too_short)
    (29.999, False, "too_short"),
    (5.0, False, "too_short"),
    (0.0, False, "too_short"),
    (0.1, False, "too_short"),
    # Boundary: just above max → excluded (too_long)
    (14400.001, False, "too_long"),
    (20000.0, False, "too_long"),
    (86400.0, False, "too_long"),
]


@pytest.mark.parametrize(
    "duration_seconds,expected_included,expected_reason",
    CLASSIFICATION_CASES,
)
def test_classify_reading_effort_observation_table(
    duration_seconds: float,
    expected_included: bool,
    expected_reason: str | None,
) -> None:
    """Table-driven coverage of boundary and classification behavior."""
    observation = DurationObservation(duration_seconds=duration_seconds)
    result = classify_reading_effort_observation(observation)

    assert result.included is expected_included
    assert result.reason_code == expected_reason
    # Original observation must remain unchanged (pure function contract)
    assert result.observation is observation
    assert result.observation.duration_seconds == duration_seconds


# ---------------------------------------------------------------------------
# Reason codes for excluded observations
# ---------------------------------------------------------------------------


def test_too_short_excluded_with_reason_code() -> None:
    """Implausibly short durations produce ``too_short`` reason code."""
    observation = DurationObservation(duration_seconds=15.0)
    result = classify_reading_effort_observation(observation)

    assert result.included is False
    assert result.reason_code == "too_short"


def test_too_long_excluded_with_reason_code() -> None:
    """Extreme long durations produce ``too_long`` reason code."""
    observation = DurationObservation(duration_seconds=20000.0)
    result = classify_reading_effort_observation(observation)

    assert result.included is False
    assert result.reason_code == "too_long"


# ---------------------------------------------------------------------------
# Boundary behavior covered explicitly
# ---------------------------------------------------------------------------


def test_exact_min_boundary_is_included() -> None:
    """Duration exactly at the minimum threshold is considered valid."""
    observation = DurationObservation(duration_seconds=DEFAULT_MIN_DURATION_SECONDS)
    result = classify_reading_effort_observation(observation)

    assert result.included is True
    assert result.reason_code is None


def test_exact_max_boundary_is_included() -> None:
    """Duration exactly at the maximum threshold is considered valid."""
    observation = DurationObservation(duration_seconds=DEFAULT_MAX_DURATION_SECONDS)
    result = classify_reading_effort_observation(observation)

    assert result.included is True
    assert result.reason_code is None


def test_just_below_min_is_excluded() -> None:
    """A value just under the minimum is excluded as too short."""
    observation = DurationObservation(duration_seconds=DEFAULT_MIN_DURATION_SECONDS - 0.001)
    result = classify_reading_effort_observation(observation)

    assert result.included is False
    assert result.reason_code == "too_short"


def test_just_above_max_is_excluded() -> None:
    """A value just over the maximum is excluded as too long."""
    observation = DurationObservation(duration_seconds=DEFAULT_MAX_DURATION_SECONDS + 0.001)
    result = classify_reading_effort_observation(observation)

    assert result.included is False
    assert result.reason_code == "too_long"


# ---------------------------------------------------------------------------
# Centralized / configurable thresholds
# ---------------------------------------------------------------------------


def test_default_thresholds_documented_and_centralized() -> None:
    """Defaults are exposed as module-level constants, not scattered."""
    assert DEFAULT_MIN_DURATION_SECONDS == 30.0
    assert DEFAULT_MAX_DURATION_SECONDS == 14400.0


def test_configurable_thresholds_override_defaults() -> None:
    """Custom thresholds can be passed without changing module constants."""
    custom = ObservationThresholds(
        min_duration_seconds=120.0,
        max_duration_seconds=600.0,
    )
    short_obs = DurationObservation(duration_seconds=60.0)
    long_obs = DurationObservation(duration_seconds=900.0)

    assert (
        classify_reading_effort_observation(short_obs, custom).included is False
    )
    assert (
        classify_reading_effort_observation(long_obs, custom).included is False
    )
    assert (
        classify_reading_effort_observation(
            DurationObservation(duration_seconds=300.0), custom
        ).included
        is True
    )


# ---------------------------------------------------------------------------
# No mutation / deletion of raw observations
# ---------------------------------------------------------------------------


def test_pure_classifier_does_not_mutate_observation() -> None:
    """The original observation object is never rewritten or deleted."""
    original = DurationObservation(
        duration_seconds=15.0,
        roll_event_id=42,
        rate_event_id=99,
        thread_id=7,
    )
    result = classify_reading_effort_observation(original)

    # Same identity reference preserved
    assert result.observation is original
    # Attributes unchanged
    assert original.duration_seconds == 15.0
    assert original.roll_event_id == 42
    assert original.rate_event_id == 99
    assert original.thread_id == 7
    # No deletion of fields or mutation of nested state (there is none)
    assert result.observation.duration_seconds == 15.0


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------


def test_batch_classify_preserves_order_and_purity() -> None:
    """Batch mapping returns results in input order without mutating inputs."""
    observations = [
        DurationObservation(duration_seconds=10.0),
        DurationObservation(duration_seconds=300.0),
        DurationObservation(duration_seconds=50000.0),
    ]
    results = classify_reading_effort_observations(observations)

    assert len(results) == len(observations)
    assert results[0].included is False
    assert results[0].reason_code == "too_short"
    assert results[1].included is True
    assert results[1].reason_code is None
    assert results[2].included is False
    assert results[2].reason_code == "too_long"

    # Original list and objects untouched
    assert observations[0].duration_seconds == 10.0
    assert observations[1].duration_seconds == 300.0
    assert observations[2].duration_seconds == 50000.0


# ---------------------------------------------------------------------------
# Provenance fields preserved in results
# ---------------------------------------------------------------------------


def test_excluded_result_retains_provenance_for_explainability() -> None:
    """Excluded results keep provenance fields so exclusions stay explainable."""
    observation = DurationObservation(
        duration_seconds=5.0,
        roll_event_id=100,
        rate_event_id=200,
        thread_id=5,
    )
    result = classify_reading_effort_observation(observation)

    assert result.included is False
    assert result.observation.roll_event_id == 100
    assert result.observation.rate_event_id == 200
    assert result.observation.thread_id == 5
