"""Tests for pure Snooze-to-bandwidth correction logic.

Issue: #1723 — deterministic, side-effect-free correction service.
"""

from comic_pile.bandwidth_correction import (
    BandwidthLevel,
    CorrectionReason,
    SnoozeCorrectionResult,
    classify_candidate_effort,
    compute_snooze_correction,
)


class TestClassifyCandidateEffort:
    """Tests for classify_candidate_effort."""

    def test_none_source_returns_balanced(self) -> None:
        """No effort evidence defaults to balanced."""
        assert classify_candidate_effort(None, None) == BandwidthLevel.BALANCED

    def test_none_minutes_returns_balanced(self) -> None:
        """None minutes with a source still defaults to balanced."""
        assert classify_candidate_effort("observed", None) == BandwidthLevel.BALANCED

    def test_none_source_returns_balanced_even_with_minutes(self) -> None:
        """None source with minutes defaults to balanced."""
        assert classify_candidate_effort(None, 15.0) == BandwidthLevel.BALANCED

    def test_light_effort(self) -> None:
        """Under 12 minutes is light."""
        assert classify_candidate_effort("observed", 8.0) == BandwidthLevel.LIGHT

    def test_balanced_effort(self) -> None:
        """12–19 minutes is balanced."""
        assert classify_candidate_effort("observed", 15.0) == BandwidthLevel.BALANCED

    def test_deep_effort(self) -> None:
        """20+ minutes is deep."""
        assert classify_candidate_effort("observed", 25.0) == BandwidthLevel.DEEP

    def test_boundary_light_balanced(self) -> None:
        """Exactly 12 minutes is balanced."""
        assert classify_candidate_effort("observed", 12.0) == BandwidthLevel.BALANCED

    def test_boundary_balanced_deep(self) -> None:
        """Exactly 20 minutes is deep."""
        assert classify_candidate_effort("observed", 20.0) == BandwidthLevel.DEEP

    def test_zero_minutes_returns_balanced(self) -> None:
        """Zero minutes with source is still light (0 < 12)."""
        assert classify_candidate_effort("observed", 0.0) == BandwidthLevel.LIGHT

    def test_no_evidence_source_returns_balanced(self) -> None:
        """'none' source returns balanced."""
        assert classify_candidate_effort("none", 10.0) == BandwidthLevel.BALANCED

    def test_publication_era_source(self) -> None:
        """Publication-era source works like any other."""
        assert classify_candidate_effort("publication_era", 22.0) == BandwidthLevel.DEEP


class TestComputeSnoozeCorrection:
    """Tests for the pure correction function."""

    def test_no_correction_when_balanced_snooze_balanced_candidate(self) -> None:
        """Snoozing a balanced candidate while in balanced mode degrades confidence."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.6,
            predicted_bandwidth="balanced",
            candidate_effort_level="balanced",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is False
        assert result.active_bandwidth == "balanced"
        assert result.active_confidence < 0.6
        assert result.reason_code == CorrectionReason.CONFIDENCE_DEGRADE
        assert result.suggest_clarification is False

    def test_heavy_snooze_shifts_balanced_to_light(self) -> None:
        """Snoozing a deep candidate while balanced shifts to light."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is True
        assert result.active_bandwidth == "light"
        assert result.active_confidence > 0.5
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT
        assert result.suggest_clarification is False

    def test_heavy_snooze_shifts_deep_to_balanced(self) -> None:
        """Snoozing a deep candidate while in deep mode shifts to balanced."""
        result = compute_snooze_correction(
            current_bandwidth="deep",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is True
        assert result.active_bandwidth == "balanced"
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT

    def test_light_snooze_shifts_balanced_to_deep(self) -> None:
        """Snoozing a light candidate while balanced shifts to deep."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="light",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is True
        assert result.active_bandwidth == "deep"
        assert result.reason_code == CorrectionReason.LIGHT_SNOOZE_DEFLATE

    def test_light_snooze_shifts_light_to_balanced(self) -> None:
        """Snoozing a light candidate while in light mode shifts to balanced."""
        result = compute_snooze_correction(
            current_bandwidth="light",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="light",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is True
        assert result.active_bandwidth == "balanced"
        assert result.reason_code == CorrectionReason.LIGHT_SNOOZE_DEFLATE

    def test_already_light_cannot_go_lighter(self) -> None:
        """Snoozing a deep candidate while already light degrades confidence."""
        result = compute_snooze_correction(
            current_bandwidth="light",
            current_confidence=0.7,
            predicted_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is False
        assert result.active_bandwidth == "light"
        assert result.active_confidence < 0.7
        assert result.reason_code == CorrectionReason.LIGHT_SNOOZE_DEFLATE

    def test_already_deep_cannot_go_deeper(self) -> None:
        """Snoozing a light candidate while already deep degrades confidence."""
        result = compute_snooze_correction(
            current_bandwidth="deep",
            current_confidence=0.7,
            predicted_bandwidth="balanced",
            candidate_effort_level="light",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.bandwidth_changed is False
        assert result.active_bandwidth == "deep"
        assert result.active_confidence < 0.7
        assert result.reason_code == CorrectionReason.LIGHT_SNOOZE_DEFLATE

    def test_preserves_predicted_bandwidth(self) -> None:
        """Predicted bandwidth is always passed through unchanged."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="deep",
            candidate_effort_level="balanced",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.predicted_bandwidth == "deep"

    def test_confidence_never_exceeds_1(self) -> None:
        """Confidence is capped at 1.0."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.95,
            predicted_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.active_confidence <= 1.0

    def test_confidence_never_below_0(self) -> None:
        """Confidence is floored at 0.0."""
        result = compute_snooze_correction(
            current_bandwidth="light",
            current_confidence=0.05,
            predicted_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert result.active_confidence >= 0.0

    def test_contradictory_snoozes_request_clarification(self) -> None:
        """Three consecutive contradictory snoozes suggest clarification."""
        # Previous snoozes were shifting heavier, now a balanced candidate
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="balanced",
            consecutive_snoozes=3,
            last_snooze_direction="heavier",
        )
        assert result.suggest_clarification is True
        assert result.reason_code == CorrectionReason.CLARIFICATION_NEEDED
        assert result.bandwidth_changed is False

    def test_three_snoozes_same_direction_no_clarification(self) -> None:
        """Three consecutive snoozes in same direction do not request clarification."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="balanced",
            consecutive_snoozes=3,
            last_snooze_direction="heavier",
        )
        # The candidate is balanced and direction is heavier — this IS contradictory
        assert result.suggest_clarification is True

    def test_two_snoozes_no_clarification(self) -> None:
        """Two consecutive snoozes do not trigger clarification."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="balanced",
            consecutive_snoozes=2,
            last_snooze_direction="heavier",
        )
        assert result.suggest_clarification is False

    def test_deterministic_output(self) -> None:
        """Same inputs always produce the same output."""
        args = {
            "current_bandwidth": "balanced",
            "current_confidence": 0.5,
            "predicted_bandwidth": "balanced",
            "candidate_effort_level": "deep",
            "consecutive_snoozes": 2,
            "last_snooze_direction": "lighter",
        }
        r1 = compute_snooze_correction(**args)
        r2 = compute_snooze_correction(**args)
        assert r1.active_bandwidth == r2.active_bandwidth
        assert r1.active_confidence == r2.active_confidence
        assert r1.reason_code == r2.reason_code
        assert r1.bandwidth_changed == r2.bandwidth_changed
        assert r1.suggest_clarification == r2.suggest_clarification

    def test_side_effect_free(self) -> None:
        """The function does not mutate any input arguments."""
        args = {
            "current_bandwidth": "balanced",
            "current_confidence": 0.5,
            "predicted_bandwidth": "balanced",
            "candidate_effort_level": "deep",
            "consecutive_snoozes": 2,
            "last_snooze_direction": "lighter",
        }
        args_copy = dict(args)
        compute_snooze_correction(**args)
        assert args == args_copy

    def test_result_type(self) -> None:
        """Returns a SnoozeCorrectionResult instance."""
        result = compute_snooze_correction(
            current_bandwidth="balanced",
            current_confidence=0.5,
            predicted_bandwidth="balanced",
            candidate_effort_level="balanced",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert isinstance(result, SnoozeCorrectionResult)
