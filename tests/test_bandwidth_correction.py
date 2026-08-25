"""Tests for Snooze bandwidth correction logic."""

import math

import pytest

from comic_pile.bandwidth_correction import (
    BandwidthLevel,
    CorrectionReason,
    SnoozeCorrectionResult,
    classify_candidate_effort,
    compute_snooze_correction,
    normalize_bandwidth,
)


class TestNormalizeBandwidth:
    """Tests for normalize_bandwidth function."""

    def test_valid_levels_unchanged(self) -> None:
        assert normalize_bandwidth("light") == "light"
        assert normalize_bandwidth("balanced") == "balanced"
        assert normalize_bandwidth("deep") == "deep"

    def test_none_returns_balanced(self) -> None:
        assert normalize_bandwidth(None) == "balanced"

    def test_invalid_returns_balanced(self) -> None:
        assert normalize_bandwidth("invalid") == "balanced"
        assert normalize_bandwidth("") == "balanced"


class TestClassifyCandidateEffort:
    """Tests for classify_candidate_effort function."""

    def test_none_source_returns_none(self) -> None:
        assert classify_candidate_effort(None, 15) is None

    def test_none_source_string_returns_none(self) -> None:
        assert classify_candidate_effort("none", 15) is None

    def test_none_minutes_returns_none(self) -> None:
        assert classify_candidate_effort("observed", None) is None

    def test_negative_minutes_returns_none(self) -> None:
        assert classify_candidate_effort("observed", -5) is None

    def test_nan_minutes_returns_none(self) -> None:
        assert classify_candidate_effort("observed", float("nan")) is None

    def test_infinite_minutes_returns_none(self) -> None:
        assert classify_candidate_effort("observed", float("inf")) is None

    def test_light_effort_under_12(self) -> None:
        assert classify_candidate_effort("observed", 10) == "light"
        assert classify_candidate_effort("observed", 11.9) == "light"

    def test_balanced_effort_12_to_19(self) -> None:
        assert classify_candidate_effort("observed", 12) == "balanced"
        assert classify_candidate_effort("observed", 15) == "balanced"
        assert classify_candidate_effort("observed", 19.9) == "balanced"

    def test_deep_effort_20_plus(self) -> None:
        assert classify_candidate_effort("observed", 20) == "deep"
        assert classify_candidate_effort("observed", 30) == "deep"
        assert classify_candidate_effort("publication_era", 25) == "deep"


class TestComputeSnoozeCorrection:
    """Tests for compute_snooze_correction function."""

    def _base_args(self, **overrides) -> dict:
        base = {
            "current_bandwidth": "balanced",
            "current_confidence": 0.5,
            "candidate_effort_level": None,
            "consecutive_snoozes": 1,
            "last_snooze_direction": None,
        }
        base.update(overrides)
        return base

    def test_unknown_effort_degrades_confidence(self) -> None:
        result = compute_snooze_correction(**self._base_args())
        assert result.reason_code == CorrectionReason.CONFIDENCE_DEGRADE.value
        assert result.active_bandwidth == "balanced"
        assert result.active_confidence < 0.5
        assert not result.bandwidth_changed
        assert not result.suggest_clarification
        assert result.applies  # confidence changed

    def test_equal_effort_degrades_confidence(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="balanced",
        ))
        assert result.reason_code == CorrectionReason.CONFIDENCE_DEGRADE.value
        assert result.active_bandwidth == "balanced"
        assert not result.bandwidth_changed

    def test_deep_candidate_from_balanced_shifts_lighter(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="deep",
        ))
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT.value
        assert result.active_bandwidth == "light"
        assert result.bandwidth_changed
        assert result.active_confidence > 0.5
        assert result.direction == "heavier"

    def test_deep_candidate_from_deep_shifts_to_balanced(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="deep",
            candidate_effort_level="deep",
        ))
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT.value
        assert result.active_bandwidth == "balanced"
        assert result.bandwidth_changed
        assert result.direction == "heavier"

    def test_deep_candidate_from_light_no_shift(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="light",
            candidate_effort_level="deep",
        ))
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT.value
        assert result.active_bandwidth == "light"
        assert not result.bandwidth_changed
        assert result.active_confidence > 0.5

    def test_light_candidate_deflates_confidence(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="light",
        ))
        assert result.reason_code == CorrectionReason.LIGHT_SNOOZE_DEFLATE.value
        assert result.active_bandwidth == "balanced"
        assert not result.bandwidth_changed
        assert result.active_confidence < 0.5
        assert result.direction == "lighter"

    def test_heavier_not_deep_deflates_confidence(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="light",
            candidate_effort_level="balanced",
        ))
        assert result.reason_code == CorrectionReason.LIGHT_SNOOZE_DEFLATE.value
        assert result.active_bandwidth == "light"
        assert not result.bandwidth_changed
        assert result.active_confidence < 0.5
        assert result.direction == "heavier"

    def test_contradiction_after_min_snoozes_requests_clarification(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=3,
            last_snooze_direction="lighter",
        ))
        assert result.reason_code == CorrectionReason.CLARIFICATION_NEEDED.value
        assert result.suggest_clarification
        assert not result.bandwidth_changed
        assert result.active_confidence < 0.5

    def test_contradiction_before_min_snoozes_no_clarification(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=2,
            last_snooze_direction="lighter",
        ))
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT.value
        assert not result.suggest_clarification

    def test_same_direction_no_contradiction(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=3,
            last_snooze_direction="heavier",
        ))
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT.value
        assert not result.suggest_clarification

    def test_none_last_direction_no_contradiction(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            candidate_effort_level="deep",
            consecutive_snoozes=3,
            last_snooze_direction=None,
        ))
        assert result.reason_code == CorrectionReason.HEAVY_SNOOZE_SHIFT.value
        assert not result.suggest_clarification

    def test_confidence_clamped_to_valid_range(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            current_confidence=0.05,
            candidate_effort_level="light",
        ))
        assert 0.0 <= result.active_confidence <= 1.0

    def test_confidence_clamped_from_nan(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_confidence=float("nan"),
        ))
        assert result.active_confidence == 0.5

    def test_none_confidence_defaults_to_0_5(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_confidence=None,
        ))
        assert result.active_confidence == 0.5

    def test_none_bandwidth_defaults_to_balanced(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth=None,
        ))
        assert result.active_bandwidth == "balanced"

    def test_applies_false_when_no_change(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="light",
            candidate_effort_level="deep",
            current_confidence=0.6,
        ))
        assert result.active_bandwidth == "light"
        assert not result.bandwidth_changed
        assert math.isclose(result.active_confidence, 0.65, rel_tol=1e-9)
        assert result.applies

    def test_applies_false_when_exact_noop(self) -> None:
        result = compute_snooze_correction(**self._base_args(
            current_bandwidth="balanced",
            current_confidence=0.5,
            candidate_effort_level="balanced",
        ))
        assert result.reason_code == CorrectionReason.CONFIDENCE_DEGRADE.value
        assert result.active_confidence == 0.45
        assert result.applies

    def test_result_structure_complete(self) -> None:
        result = compute_snooze_correction(**self._base_args())
        assert isinstance(result, SnoozeCorrectionResult)
        assert hasattr(result, "active_bandwidth")
        assert hasattr(result, "active_confidence")
        assert hasattr(result, "bandwidth_changed")
        assert hasattr(result, "reason_code")
        assert hasattr(result, "suggest_clarification")
        assert hasattr(result, "applies")
        assert hasattr(result, "direction")