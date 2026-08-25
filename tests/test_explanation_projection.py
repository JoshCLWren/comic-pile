"""Tests for recommendation explanation projection (#1767).

Verifies that reason codes persisted on roll events are correctly projected
into human-readable explanations for the frontend.
"""

from __future__ import annotations

from app.services.explanation_projection import (
    EXPLANATION_MAP,
    get_primary_explanation,
    project_explanations,
)


class TestExplanationMap:
    """Tests for the EXPLANATION_MAP constant."""

    def test_contains_expected_codes(self) -> None:
        """Map contains all expected reason codes from the roll selection logic."""
        assert "momentum_weighted" in EXPLANATION_MAP
        assert "pure_random" in EXPLANATION_MAP
        assert "fallback_random" in EXPLANATION_MAP

    def test_momentum_weighted_explanation(self) -> None:
        """momentum_weighted maps to correct explanation."""
        assert EXPLANATION_MAP["momentum_weighted"] == "Weighted by your recent reading momentum"

    def test_pure_random_explanation(self) -> None:
        """pure_random maps to correct explanation."""
        assert EXPLANATION_MAP["pure_random"] == "Pure random selection"

    def test_fallback_random_explanation(self) -> None:
        """fallback_random maps to correct explanation."""
        assert EXPLANATION_MAP["fallback_random"] == "Fallback to random selection"


class TestProjectExplanations:
    """Tests for project_explanations()."""

    def test_empty_input_returns_empty_list(self) -> None:
        """Empty or None input returns empty list."""
        assert project_explanations([]) == []
        assert project_explanations(None) == []

    def test_known_codes_map_to_explanations(self) -> None:
        """Known codes map to their human-readable explanations."""
        codes = ["momentum_weighted", "pure_random"]
        result = project_explanations(codes)
        assert result == [
            "Weighted by your recent reading momentum",
            "Pure random selection",
        ]

    def test_unknown_code_falls_back_to_title_case(self) -> None:
        """Unknown codes are safely title-cased rather than crashing."""
        result = project_explanations(["unknown_code"])
        assert result == ["Unknown Code"]

    def test_mixed_known_and_unknown_codes(self) -> None:
        """Known codes map; unknown codes fall back."""
        result = project_explanations(["momentum_weighted", "custom_reason"])
        assert result == [
            "Weighted by your recent reading momentum",
            "Custom Reason",
        ]

    def test_preserves_order(self) -> None:
        """Explanations maintain the same order as input codes."""
        codes = ["pure_random", "momentum_weighted", "fallback_random"]
        result = project_explanations(codes)
        assert result == [
            "Pure random selection",
            "Weighted by your recent reading momentum",
            "Fallback to random selection",
        ]


class TestGetPrimaryExplanation:
    """Tests for get_primary_explanation()."""

    def test_empty_input_returns_none(self) -> None:
        """Empty or None input returns None."""
        assert get_primary_explanation([]) is None
        assert get_primary_explanation(None) is None

    def test_returns_first_explanation(self) -> None:
        """Returns the first explanation from the list."""
        result = get_primary_explanation(["momentum_weighted", "pure_random"])
        assert result == "Weighted by your recent reading momentum"

    def test_single_code_returns_that_explanation(self) -> None:
        """Single code returns its explanation."""
        result = get_primary_explanation(["pure_random"])
        assert result == "Pure random selection"

    def test_unknown_code_returns_title_cased(self) -> None:
        """Unknown code returns title-cased fallback."""
        result = get_primary_explanation(["custom_reason"])
        assert result == "Custom Reason"

    def test_override_roll_returns_none(self) -> None:
        """Override rolls have empty reason codes, so explanation is None."""
        assert get_primary_explanation([]) is None