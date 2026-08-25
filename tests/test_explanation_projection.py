"""Unit tests for the recommendation explanation projection."""

from __future__ import annotations

from app.services.explanation_projection import (
    get_primary_explanation,
    project_explanations,
)


def test_momentum_weighted_projection() -> None:
    """Momentum-weighted selections project to the momentum explanation."""
    explanations = project_explanations(["momentum_weighted"])
    assert explanations == ["Weighted by your recent reading momentum"]


def test_pure_random_projection() -> None:
    """Pure-random selections are clearly described as random."""
    explanations = project_explanations(["pure_random"])
    assert explanations == ["Pure random selection"]


def test_empty_codes_project_to_empty() -> None:
    """Missing or empty reason codes project to no explanations."""
    assert project_explanations(None) == []
    assert project_explanations([]) == []


def test_unknown_code_falls_back_to_title_case() -> None:
    """Unknown codes fall back to a safe title-cased rendering."""
    explanations = project_explanations(["series_streak"])
    assert explanations == ["Series Streak"]


def test_get_primary_explanation_returns_first() -> None:
    """The primary explanation is the first projected explanation."""
    assert get_primary_explanation(["momentum_weighted"]) == (
        "Weighted by your recent reading momentum"
    )


def test_get_primary_explanation_none_for_empty() -> None:
    """The primary explanation is None when no codes are present."""
    assert get_primary_explanation([]) is None
    assert get_primary_explanation(None) is None
