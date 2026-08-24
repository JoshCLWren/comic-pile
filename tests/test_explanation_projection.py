"""Unit tests for the recommendation explanation projection."""

from __future__ import annotations

from app.services.explanation_projection import (
    get_primary_explanation,
    project_explanations,
)


def test_momentum_weighted_projection() -> None:
    explanations = project_explanations(["momentum_weighted"])
    assert explanations == ["Weighted by your recent reading momentum"]


def test_pure_random_projection() -> None:
    explanations = project_explanations(["pure_random"])
    assert explanations == ["Pure random selection"]


def test_empty_codes_project_to_empty() -> None:
    assert project_explanations(None) == []
    assert project_explanations([]) == []


def test_unknown_code_falls_back_to_title_case() -> None:
    explanations = project_explanations(["series_streak"])
    assert explanations == ["Series Streak"]


def test_get_primary_explanation_returns_first() -> None:
    assert get_primary_explanation(["momentum_weighted"]) == (
        "Weighted by your recent reading momentum"
    )


def test_get_primary_explanation_none_for_empty() -> None:
    assert get_primary_explanation([]) is None
    assert get_primary_explanation(None) is None
