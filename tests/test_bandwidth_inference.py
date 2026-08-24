"""Tests for pure bandwidth inference from historical reading decisions.

These are pure unit tests — no database, no async, no fixtures beyond
plain dataclass construction.  Covers acceptance criteria for issue #1707:
- Sufficient history produces light/balanced/deep with confidence.
- Insufficient or contradictory history returns balanced/low-confidence safely.
- Predictions are deterministic for fixed history.
- The service exposes reason/evidence data useful for tests and future explanations.
- No Roll probabilities or UI change.
"""

from __future__ import annotations

import pytest

from app.constants import BandwidthLevel
from app.services.bandwidth_inference import (
    DEEP_MIN_MINUTES,
    LIGHT_MAX_MINUTES,
    MIN_EFFORT_OBSERVATIONS,
    Daypart,
    HistoricalObservation,
    _classify_effort,
    _daypart_from_hour,
    _median,
    infer_bandwidth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obs(
    effort: float,
    *,
    snoozed: bool = False,
    hour: int | None = None,
    rating: float | None = None,
) -> HistoricalObservation:
    """Shorthand for building a historical observation."""
    return HistoricalObservation(
        effort_minutes=effort,
        was_snoozed=snoozed,
        session_hour=hour,
        rating=rating,
    )


def _light_obs(*, n: int = 5) -> list[HistoricalObservation]:
    """Return n predominantly light-effort observations."""
    return [_obs(5.0 + i * 0.5) for i in range(n)]


def _deep_obs(*, n: int = 5) -> list[HistoricalObservation]:
    """Return n predominantly deep-effort observations."""
    return [_obs(22.0 + i * 1.0) for i in range(n)]


def _balanced_obs(*, n: int = 6) -> list[HistoricalObservation]:
    """Return n balanced-effort observations (mixed light and deep)."""
    return [
        _obs(5.0),
        _obs(25.0),
        _obs(14.0),
        _obs(6.0),
        _obs(22.0),
        _obs(15.0),
    ][:n]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestClassifyEffort:
    """Test effort classification into bandwidth bands."""

    def test_light_effort(self) -> None:
        """Effort at or below LIGHT_MAX classifies as LIGHT."""
        assert _classify_effort(0.0) == BandwidthLevel.LIGHT
        assert _classify_effort(5.0) == BandwidthLevel.LIGHT
        assert _classify_effort(LIGHT_MAX_MINUTES) == BandwidthLevel.LIGHT

    def test_balanced_effort(self) -> None:
        """Effort between LIGHT_MAX and DEEP_MIN classifies as BALANCED."""
        assert _classify_effort(11.0) == BandwidthLevel.BALANCED
        assert _classify_effort(15.0) == BandwidthLevel.BALANCED
        assert _classify_effort(19.9) == BandwidthLevel.BALANCED

    def test_deep_effort(self) -> None:
        """Effort at or above DEEP_MIN classifies as DEEP."""
        assert _classify_effort(DEEP_MIN_MINUTES) == BandwidthLevel.DEEP
        assert _classify_effort(25.0) == BandwidthLevel.DEEP
        assert _classify_effort(60.0) == BandwidthLevel.DEEP


class TestDaypartFromHour:
    """Test hour-to-daypart mapping."""

    def test_morning(self) -> None:
        """Hours 6-11 map to morning."""
        for hour in range(6, 12):
            assert _daypart_from_hour(hour) == Daypart.MORNING

    def test_afternoon(self) -> None:
        """Hours 12-17 map to afternoon."""
        for hour in range(12, 18):
            assert _daypart_from_hour(hour) == Daypart.AFTERNOON

    def test_evening(self) -> None:
        """Hours 18-22 map to evening."""
        for hour in range(18, 23):
            assert _daypart_from_hour(hour) == Daypart.EVENING

    def test_night(self) -> None:
        """Hours 23-5 map to night."""
        for hour in [*range(23, 24), *range(0, 6)]:
            assert _daypart_from_hour(hour) == Daypart.NIGHT


class TestMedian:
    """Test median computation."""

    def test_odd_count(self) -> None:
        """Median of odd-count list is the middle element."""
        assert _median([1.0, 3.0, 5.0]) == 3.0

    def test_even_count(self) -> None:
        """Median of even-count list is the average of two middle elements."""
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_single_element(self) -> None:
        """Median of a single element is that element."""
        assert _median([42.0]) == 42.0


# ---------------------------------------------------------------------------
# Insufficient history → safe neutral default
# ---------------------------------------------------------------------------


class TestInsufficientHistory:
    """Test that insufficient history returns balanced/low-confidence."""

    def test_empty_history(self) -> None:
        """Empty history returns BALANCED with very low confidence."""
        result = infer_bandwidth([])
        assert result.level == BandwidthLevel.BALANCED
        assert result.confidence == 0.1
        assert result.evidence.effort_observations == 0

    def test_too_few_observations(self) -> None:
        """Fewer than MIN_EFFORT_OBSERVATIONS returns BALANCED."""
        obs = [_obs(5.0), _obs(8.0)]  # only 2 observations
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.BALANCED
        assert result.confidence == 0.1
        assert result.evidence.effort_observations == 2

    def test_exactly_at_threshold_still_predicts(self) -> None:
        """Exactly MIN_EFFORT_OBSERVATIONS is enough for a non-neutral prediction."""
        obs = [_obs(5.0), _obs(6.0), _obs(4.0)]
        result = infer_bandwidth(obs)
        # All light → should predict LIGHT, not BALANCED
        assert result.level == BandwidthLevel.LIGHT
        assert result.confidence > 0.1

    def test_zero_effort_observations_filtered(self) -> None:
        """Observations with effort_minutes=0 are filtered out."""
        obs = [_obs(0.0), _obs(0.0), _obs(0.0)]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.BALANCED
        assert result.evidence.effort_observations == 0


# ---------------------------------------------------------------------------
# Sufficient history → correct predictions
# ---------------------------------------------------------------------------


class TestSufficientHistory:
    """Test that sufficient history produces correct bandwidth predictions."""

    def test_all_light_observations(self) -> None:
        """All light observations predict LIGHT with high confidence."""
        obs = _light_obs(n=6)
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.LIGHT
        assert result.confidence > 0.3
        assert result.evidence.light_fraction == 1.0
        assert result.evidence.deep_fraction == 0.0

    def test_all_deep_observations(self) -> None:
        """All deep observations predict DEEP with high confidence."""
        obs = _deep_obs(n=6)
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.DEEP
        assert result.confidence > 0.3
        assert result.evidence.deep_fraction == 1.0
        assert result.evidence.light_fraction == 0.0

    def test_balanced_mixed_observations(self) -> None:
        """Mixed light and deep observations predict BALANCED."""
        obs = _balanced_obs(n=6)
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.BALANCED
        assert result.confidence > 0.0

    def test_majority_light_with_some_balanced(self) -> None:
        """Majority light + some balanced still predicts LIGHT."""
        obs = [
            _obs(5.0),
            _obs(6.0),
            _obs(7.0),
            _obs(8.0),  # 4 light
            _obs(14.0),
            _obs(15.0),  # 2 balanced
        ]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.LIGHT

    def test_majority_deep_with_some_balanced(self) -> None:
        """Majority deep + some balanced predicts DEEP."""
        obs = [
            _obs(22.0),
            _obs(25.0),
            _obs(30.0),
            _obs(28.0),  # 4 deep
            _obs(14.0),
            _obs(15.0),  # 2 balanced
        ]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.DEEP


# ---------------------------------------------------------------------------
# Snooze behavior influence
# ---------------------------------------------------------------------------


class TestSnoozeInfluence:
    """Test that snooze behavior influences bandwidth prediction."""

    def test_snoozed_heavy_comics_reduce_deep_confidence(self) -> None:
        """Heavy comics that were snoozed reduce deep prediction confidence."""
        obs_snoozed = [_obs(25.0, snoozed=True) for _ in range(6)]
        obs_not_snoozed = [_obs(25.0, snoozed=False) for _ in range(6)]

        result_snoozed = infer_bandwidth(obs_snoozed)
        result_not_snoozed = infer_bandwidth(obs_not_snoozed)

        # Both predict DEEP (all deep effort), but the snooze evidence must
        # strictly reduce confidence rather than being ignored.
        assert result_snoozed.level == BandwidthLevel.DEEP
        assert result_not_snoozed.level == BandwidthLevel.DEEP
        assert result_snoozed.confidence < result_not_snoozed.confidence

    def test_snooze_heavy_rate_tracked(self) -> None:
        """Snooze heavy rate is correctly computed."""
        obs = [
            _obs(25.0, snoozed=True),  # deep + snoozed
            _obs(5.0, snoozed=True),  # light + snoozed
            _obs(22.0, snoozed=False),  # deep, not snoozed
            _obs(6.0, snoozed=False),  # light, not snoozed
            _obs(24.0, snoozed=True),  # deep + snoozed
            _obs(8.0, snoozed=False),  # light, not snoozed
        ]
        result = infer_bandwidth(obs)
        # 2 out of 3 snoozed were deep → snooze_heavy_rate = 2/3
        assert result.evidence.snooze_heavy_rate == pytest.approx(2 / 3, abs=0.01)

    def test_no_snooze_gives_zero_rates(self) -> None:
        """No snoozes gives zero snooze rates."""
        obs = _light_obs(n=6)
        result = infer_bandwidth(obs)
        assert result.evidence.snooze_rate == 0.0
        assert result.evidence.snooze_heavy_rate == 0.0


# ---------------------------------------------------------------------------
# Time-of-day prior
# ---------------------------------------------------------------------------


class TestTimeOfDayPrior:
    """Test that time-of-day prior influences prediction."""

    def test_morning_prior_favors_light(self) -> None:
        """Morning session slightly favors lighter predictions."""
        obs = _balanced_obs(n=6)
        result_morning = infer_bandwidth(obs, session_hour=8)
        result_evening = infer_bandwidth(obs, session_hour=20)

        # With evenly split evidence the weak prior tilts the prediction:
        # morning nudges toward light, evening toward deep, while both
        # record their daypart evidence.
        assert result_morning.evidence.daypart == "morning"
        assert result_evening.evidence.daypart == "evening"
        assert result_morning.level == BandwidthLevel.LIGHT
        assert result_evening.level == BandwidthLevel.DEEP

    def test_night_prior_favors_deep(self) -> None:
        """Night session slightly favors deeper predictions."""
        obs = [
            _obs(14.0),
            _obs(16.0),
            _obs(18.0),  # balanced
            _obs(20.0),
            _obs(22.0),
            _obs(24.0),  # deep
        ]
        result_neutral = infer_bandwidth(obs)
        result_night = infer_bandwidth(obs, session_hour=0)
        result_morning = infer_bandwidth(obs, session_hour=8)

        # The prior is not a hard rule: an even balanced/deep split remains
        # BALANCED by default and in the morning, while night tips the
        # borderline evidence toward DEEP.
        assert result_neutral.evidence.daypart is None
        assert result_morning.evidence.daypart == "morning"
        assert result_night.evidence.daypart == "night"
        assert result_neutral.level == BandwidthLevel.BALANCED
        assert result_morning.level == BandwidthLevel.BALANCED
        assert result_night.level == BandwidthLevel.DEEP

    def test_no_hour_omits_prior(self) -> None:
        """No session_hour means no daypart prior is applied."""
        obs = _balanced_obs(n=6)
        result = infer_bandwidth(obs)
        assert result.evidence.daypart is None
        assert result.evidence.daypart_prior == 0.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Test that predictions are deterministic for fixed history."""

    def test_same_input_same_output(self) -> None:
        """Identical inputs always produce identical outputs."""
        obs = [
            _obs(5.0),
            _obs(25.0),
            _obs(14.0),
            _obs(6.0),
            _obs(22.0),
            _obs(15.0),
        ]
        result1 = infer_bandwidth(obs, session_hour=14)
        result2 = infer_bandwidth(obs, session_hour=14)

        assert result1.level == result2.level
        assert result1.confidence == result2.confidence
        assert result1.evidence.mean_effort == result2.evidence.mean_effort
        assert result1.evidence.reasons == result2.evidence.reasons

    def test_tuple_input_same_as_list(self) -> None:
        """Tuple and list inputs produce the same result."""
        obs_list: list[HistoricalObservation] = [_obs(5.0), _obs(6.0), _obs(4.0)]
        obs_tuple: tuple[HistoricalObservation, ...] = tuple(obs_list)

        result_list = infer_bandwidth(obs_list)
        result_tuple = infer_bandwidth(obs_tuple)

        assert result_list.level == result_tuple.level
        assert result_list.confidence == result_tuple.confidence

    def test_different_hour_different_evidence(self) -> None:
        """Different session hours produce different daypart evidence."""
        obs = _balanced_obs(n=6)
        result_morning = infer_bandwidth(obs, session_hour=8)
        result_night = infer_bandwidth(obs, session_hour=23)

        assert result_morning.evidence.daypart != result_night.evidence.daypart
        assert result_morning.evidence.daypart_prior != result_night.evidence.daypart_prior


# ---------------------------------------------------------------------------
# Evidence and reasoning
# ---------------------------------------------------------------------------


class TestEvidenceAndReasoning:
    """Test that evidence and reasoning are exposed correctly."""

    def test_evidence_has_all_fields(self) -> None:
        """Evidence contains all required fields."""
        obs = _light_obs(n=6)
        result = infer_bandwidth(obs)
        ev = result.evidence

        assert ev.effort_observations == 6
        assert ev.mean_effort > 0
        assert ev.median_effort > 0
        assert 0.0 <= ev.light_fraction <= 1.0
        assert 0.0 <= ev.deep_fraction <= 1.0
        assert 0.0 <= ev.snooze_rate <= 1.0
        assert 0.0 <= ev.snooze_heavy_rate <= 1.0
        assert 0.0 <= ev.alignment_score <= 1.0
        assert 0.0 <= ev.evidence_sufficiency <= 1.0

    def test_reasons_are_populated(self) -> None:
        """Reasons list is non-empty for predictions with sufficient history."""
        obs = _light_obs(n=6)
        result = infer_bandwidth(obs)
        assert len(result.evidence.reasons) > 0

    def test_insufficient_history_reasons(self) -> None:
        """Insufficient history includes explanation in reasons."""
        result = infer_bandwidth([_obs(5.0)])
        assert any("Insufficient" in r for r in result.evidence.reasons)

    def test_confidence_bounded(self) -> None:
        """Confidence is always between 0 and MAX_CONFIDENCE."""
        from app.services.bandwidth_inference import MAX_CONFIDENCE

        obs_sets = [
            _light_obs(n=10),
            _deep_obs(n=10),
            _balanced_obs(n=6),
            [],
            [_obs(5.0)],
        ]
        for obs in obs_sets:
            result = infer_bandwidth(obs)
            assert 0.0 <= result.confidence <= MAX_CONFIDENCE

    def test_prediction_source_is_inferred(self) -> None:
        """Source is always 'inferred' for the pure service."""
        result = infer_bandwidth(_light_obs(n=6))
        assert result.source == "inferred"

    def test_evidence_sufficiency_scales_with_observations(self) -> None:
        """Evidence sufficiency increases with more observations."""
        result_few = infer_bandwidth(_light_obs(n=MIN_EFFORT_OBSERVATIONS))
        result_many = infer_bandwidth(_light_obs(n=MIN_EFFORT_OBSERVATIONS * 4))

        assert result_many.evidence.evidence_sufficiency > result_few.evidence.evidence_sufficiency


# ---------------------------------------------------------------------------
# Contradictory evidence
# ---------------------------------------------------------------------------


class TestContradictoryEvidence:
    """Test that contradictory evidence reduces confidence."""

    def test_equal_distribution_reduces_confidence(self) -> None:
        """Equal light/balanced/deep distribution reduces confidence."""
        obs = [
            _obs(5.0),
            _obs(15.0),
            _obs(25.0),
            _obs(6.0),
            _obs(14.0),
            _obs(22.0),
        ]
        result = infer_bandwidth(obs)

        # 5.0/6.0 are light, 14.0/15.0 are balanced, 22.0/25.0 are deep:
        # two observations per band, so every band fraction is 2/6 ≈ 33%,
        # below the 40% dominance threshold → contradictory evidence.
        assert result.evidence.light_fraction == pytest.approx(1 / 3, abs=0.01)
        assert result.evidence.deep_fraction == pytest.approx(1 / 3, abs=0.01)
        assert result.confidence < 0.5

        # Evenly split (contradictory) history resolves to the safe
        # neutral level with low confidence.
        assert result.level == BandwidthLevel.BALANCED


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test boundary and edge cases."""

    def test_all_same_effort(self) -> None:
        """All identical effort values produce a clear prediction."""
        obs = [_obs(15.0) for _ in range(6)]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.BALANCED
        assert result.evidence.mean_effort == 15.0

    def test_effort_exactly_at_light_boundary(self) -> None:
        """Effort exactly at LIGHT_MAX still classifies as light."""
        obs = [_obs(LIGHT_MAX_MINUTES) for _ in range(6)]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.LIGHT

    def test_effort_exactly_at_deep_boundary(self) -> None:
        """Effort exactly at DEEP_MIN still classifies as deep."""
        obs = [_obs(DEEP_MIN_MINUTES) for _ in range(6)]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.DEEP

    def test_very_large_effort(self) -> None:
        """Very large effort values are handled gracefully."""
        obs = [_obs(120.0) for _ in range(6)]
        result = infer_bandwidth(obs)
        assert result.level == BandwidthLevel.DEEP
        assert result.evidence.mean_effort == 120.0

    def test_zero_effort_filtered_out(self) -> None:
        """Zero-effort observations are filtered from computation."""
        obs = [_obs(0.0)] * 5 + [_obs(5.0)]
        result = infer_bandwidth(obs)
        # Only 1 valid observation → insufficient
        assert result.level == BandwidthLevel.BALANCED
        assert result.evidence.effort_observations == 1

    def test_negative_effort_filtered(self) -> None:
        """Negative effort values are filtered out."""
        obs = [_obs(-5.0)] * 3 + [_obs(5.0)]
        result = infer_bandwidth(obs)
        assert result.evidence.effort_observations == 1

    def test_mixed_valid_and_zero_effort(self) -> None:
        """Mix of valid and zero-effort observations uses only valid ones."""
        obs = [_obs(5.0), _obs(0.0), _obs(6.0), _obs(0.0), _obs(4.0)]
        result = infer_bandwidth(obs)
        # 3 valid observations → just enough
        assert result.evidence.effort_observations == 3
        assert result.level == BandwidthLevel.LIGHT


# ---------------------------------------------------------------------------
# Data structure immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    """Test that data structures are frozen."""

    def test_historical_observation_frozen(self) -> None:
        """HistoricalObservation is immutable."""
        obs = _obs(5.0)
        with pytest.raises(AttributeError):
            obs.effort_minutes = 10.0

    def test_bandwidth_prediction_frozen(self) -> None:
        """BandwidthPrediction is immutable."""
        result = infer_bandwidth(_light_obs(n=6))
        with pytest.raises(AttributeError):
            result.level = BandwidthLevel.DEEP

    def test_bandwidth_evidence_frozen(self) -> None:
        """BandwidthEvidence is immutable."""
        result = infer_bandwidth(_light_obs(n=6))
        with pytest.raises(AttributeError):
            result.evidence.mean_effort = 99.0
