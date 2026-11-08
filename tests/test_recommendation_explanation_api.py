"""Recommendation explanation pruned: HTTP handler gone, projection unit retained."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.recommendation_explanation import RecommendationExplanationProjection

def test_explainable_factor_frozen_dataclass() -> None:
    """ExplainableFactor instances raised by the projection are frozen (immutable)."""
    projection = RecommendationExplanationProjection
    factor = projection.translate_bandwidth("band_light")
    assert factor is not None

    with pytest.raises(FrozenInstanceError):
        factor.code = "mutated"

    factor2 = projection.translate_intent("intent_momentum")
    assert factor2 is not None
    with pytest.raises(FrozenInstanceError):
        factor2.label = "mutated"
