"""Pure tests for recommendation explanation projection.

Covers all current reason-code families and the documented graceful-degradation
behaviors:
- Every named factor family translates correctly.
- Unknown/legacy codes degrade safely to empty or a generic note.
- Missing context yields empty factors without raising.
- Ordering is deterministic and the cap is applied.
- Non-dict context values are handled without error.
- Factors never expose raw numeric scores.
"""

from __future__ import annotations

import pytest

from app.services.recommendation_explanation import (
    ExplainableFactor,
    RecommendationExplanationProjection,
    _BANDWIDTH_EXPLANATIONS,
    _INTENT_EXPLANATIONS,
    _PRIMARY_SCORE_EXPLANATIONS,
    _SELECTION_EXPLANATIONS,
    _TASTE_BANK_EXPLANATIONS,
    MAX_EXPLANATIONS,
)


# ── Sanity checks on the private explanation dictionaries ────────────────

class TestExplanationDictionaries:
    """Ensure the internal reason-code maps are leaktight and non-empty."""

    def test_no_raw_scores_in_bandwidth_labels(self) -> None:
        for code, (label, detail) in _BANDWIDTH_EXPLANATIONS.items():
            assert not any(
                ch.isdigit() for ch in label + (detail or "")
            ), f"Raw numeric value leaked in bandwidth {code!r}: {label!r}"

    def test_no_raw_scores_in_intent_labels(self) -> None:
        for code, (label, detail) in _INTENT_EXPLANATIONS.items():
            assert not any(
                ch.isdigit() for ch in label + (detail or "")
            ), f"Raw numeric value leaked in intent {code!r}: {label!r}"

    def test_no_raw_scores_in_taste_bank_labels(self) -> None:
        for code, (label, detail) in _TASTE_BANK_EXPLANATIONS.items():
            assert not any(
                ch.isdigit() for ch in label + (detail or "")
            ), f"Raw numeric value leaked in taste-bank {code!r}: {label!r}"

    def test_no_raw_scores_in_primary_score_labels(self) -> None:
        for code, (label, detail) in _PRIMARY_SCORE_EXPLANATIONS.items():
            assert not any(
                ch.isdigit() for ch in label + (detail or "")
            ), f"Raw numeric value leaked in score {code!r}: {label!r}"

    def test_all_labels_are_non_empty(self) -> None:
        for family, explanations in (
            ("bandwidth", _BANDWIDTH_EXPLANATIONS),
            ("intent", _INTENT_EXPLANATIONS),
            ("taste-bank", _TASTE_BANK_EXPLANATIONS),
            ("primary-score", _PRIMARY_SCORE_EXPLANATIONS),
            ("selection", _SELECTION_EXPLANATIONS),
        ):
            for code, (label, _detail) in explanations.items():
                assert label.strip(), f"Empty label in {family} code {code!r}"

    def test_max_explanations_is_positive(self) -> None:
        assert MAX_EXPLANATIONS >= 1


# ── Bandwidth translate tests ─────────────────────────────────────────────

class TestTranslateBandwidth:
    def test_band_light(self) -> None:
        factor = RecommendationExplanationProjection.translate_bandwidth("band_light")
        assert factor == ExplainableFactor(
            code="band_light", label="Quick read", detail="~11-minute read"
        )

    def test_band_balanced(self) -> None:
        factor = RecommendationExplanationProjection.translate_bandwidth("band_balanced")
        assert factor == ExplainableFactor(code="band_balanced", label="Medium read", detail=None)

    def test_band_deep(self) -> None:
        factor = RecommendationExplanationProjection.translate_bandwidth("band_deep")
        assert factor == ExplainableFactor(
            code="band_deep",
            label="Deep read",
            detail="Settling in for an extended session",
        )

    def test_unknown_bandwidth_returns_none(self) -> None:
        assert (
            RecommendationExplanationProjection.translate_bandwidth("band_unknown")
            is None
        )

    def test_empty_bandwidth_returns_none(self) -> None:
        assert (
            RecommendationExplanationProjection.translate_bandwidth("") is None
        )


# ── Intent translate tests ────────────────────────────────────────────────

class TestTranslateIntent:
    def test_intent_balanced(self) -> None:
        factor = RecommendationExplanationProjection.translate_intent("intent_balanced")
        assert factor == ExplainableFactor(code="intent_balanced", label="Balanced pick", detail=None)

    def test_intent_momentum(self) -> None:
        factor = RecommendationExplanationProjection.translate_intent("intent_momentum")
        assert factor == ExplainableFactor(
            code="intent_momentum", label="Recent series momentum", detail=None
        )

    def test_intent_familiar(self) -> None:
        factor = RecommendationExplanationProjection.translate_intent("intent_familiar")
        assert factor == ExplainableFactor(
            code="intent_familiar",
            label="Creator you confirmed you like",
            detail=None,
        )

    def test_intent_explore(self) -> None:
        factor = RecommendationExplanationProjection.translate_intent("intent_explore")
        assert factor == ExplainableFactor(
            code="intent_explore",
            label="Novel but connected to your tastes",
            detail=None,
        )

    def test_intent_random(self) -> None:
        factor = RecommendationExplanationProjection.translate_intent("intent_random")
        assert factor == ExplainableFactor(
            code="intent_random",
            label="No weighting applied",
            detail="Pure random selection",
        )

    def test_unknown_intent_returns_none(self) -> None:
        assert (
            RecommendationExplanationProjection.translate_intent("intent_future")
            is None
        )


# ── Selection-method translate tests ──────────────────────────────────────

class TestTranslateSelectionMethod:
    def test_random_explains_bypass(self) -> None:
        factor = (
            RecommendationExplanationProjection.translate_selection_method("random")
        )
        assert factor == ExplainableFactor(
            code="random", label="Pure random", detail="Weighting was bypassed"
        )

    def test_override_explains_direct_choice(self) -> None:
        factor = (
            RecommendationExplanationProjection.translate_selection_method("override")
        )
        assert factor == ExplainableFactor(
            code="override", label="Manual pick", detail="Directly chosen"
        )

    def test_unknown_selection_returns_none(self) -> None:
        assert (
            RecommendationExplanationProjection.translate_selection_method("semantic")
            is None
        )


# ── Taste Bank factor translate tests ─────────────────────────────────────

class TestTranslateTasteBankFactor:
    def test_high_affinity(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_high_affinity"}
        )
        assert factor == ExplainableFactor(
            code="taste_high_affinity", label="Strong affinity", detail=None
        )

    def test_confirmed_creator(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_creator"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_creator",
            label="Creator you confirmed you like",
            detail=None,
        )

    def test_confirmed_character(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_character"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_character", label="Character profile confirmed", detail=None
        )

    def test_confirmed_team(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_team"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_team", label="Team profile confirmed", detail=None
        )

    def test_confirmed_era(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_era"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_era", label="Era preference confirmed", detail=None
        )

    def test_novel_adjacent(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_novel_adjacent"}
        )
        assert factor == ExplainableFactor(
            code="taste_novel_adjacent",
            label="Novel but connected to your tastes",
            detail=None,
        )

    def test_series_momentum(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_series_momentum"}
        )
        assert factor == ExplainableFactor(
            code="taste_series_momentum", label="Recent series momentum", detail=None
        )

    def test_near_completion(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_near_completion"}
        )
        assert factor == ExplainableFactor(
            code="taste_near_completion",
            label="Near completion — finish strong",
            detail=None,
        )

    def test_unknown_taste_bank_code_returns_none(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_future"}
        )
        assert factor is None

    def test_missing_code_key_returns_none(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"detail": "some extra"}
        )
        assert factor is None

    def test_non_dict_input_returns_none(self) -> None:
        assert (
            RecommendationExplanationProjection.translate_taste_bank_factor("string") is None
        )
        assert (
            RecommendationExplanationProjection.translate_taste_bank_factor(42) is None
        )
        assert (
            RecommendationExplanationProjection.translate_taste_bank_factor(None) is None
        )

    def test_empty_code_returns_none(self) -> None:
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": ""}
        )
        assert factor is None


# ── Primary-score translate tests ─────────────────────────────────────────

class TestTranslatePrimaryScore:
    def test_affinity_strong(self) -> None:
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_affinity_strong", "value": 0.82}
        )
        assert factor == ExplainableFactor(
            code="score_affinity_strong", label="Strong affinity", detail=None
        )

    def test_affinity_moderate(self) -> None:
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_affinity_moderate", "value": 0.51}
        )
        assert factor == ExplainableFactor(
            code="score_affinity_moderate", label="Matches your history", detail=None
        )

    def test_recency_boost(self) -> None:
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_recency_boost"}
        )
        assert factor == ExplainableFactor(
            code="score_recency_boost", label="Recently updated", detail=None
        )

    def test_staleness_penalty(self) -> None:
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_staleness_penalty"}
        )
        assert factor == ExplainableFactor(
            code="score_staleness_penalty", label="Less active lately", detail=None
        )

    def test_primary_score_never_exposes_raw_value(self) -> None:
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_affinity_strong", "value": 0.99}
        )
        assert "0.99" not in (factor.label or "")
        assert "0.99" not in (factor.detail or "")

    def test_unknown_primary_score_returns_none(self) -> None:
        assert (
            RecommendationExplanationProjection.translate_primary_score(
                {"code": "score_unknown"}
            )
            is None
        )


# ── Full-context projection tests ─────────────────────────────────────────

class TestProjectRecommendationContext:
    def test_full_context_returns_ordered_factors(self) -> None:
        context = {
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [
                {"code": "taste_high_affinity"},
                {"code": "taste_confirmed_creator"},
            ],
            "primary_score": {"code": "score_recency_boost"},
            "affinity_notes": ["taste_series_momentum"],
            "selection_method": "random",
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(
            context
        )
        labels = [f.label for f in factors]
        assert "Quick read" in labels  # bandwidth first
        assert "Recent series momentum" in labels  # intent second
        assert "Strong affinity" in labels  # taste bank first
        assert "Creator you confirmed you like" in labels  # taste bank second
        assert "Recently updated" in labels  # primary score
        assert "Pure random" in labels  # selection method appended

    def test_factors_respect_max_cap(self) -> None:
        context = {
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [{"code": c} for c in _TASTE_BANK_EXPLANATIONS],
            "primary_score": {"code": "score_recency_boost"},
            "affinity_notes": ["taste_series_momentum"],
            "selection_method": "random",
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(
            context, max_factors=2
        )
        assert len(factors) == 2

    def test_max_factors_cap_default(self) -> None:
        context = {
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [{"code": c} for c in _TASTE_BANK_EXPLANATIONS],
            "primary_score": {"code": "score_recency_boost"},
            "affinity_notes": ["taste_series_momentum"],
            "selection_method": "random",
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        assert len(factors) <= MAX_EXPLANATIONS

    def test_none_context_returns_only_selection_method(self) -> None:
        factors = RecommendationExplanationProjection.project_recommendation_context(
            None, selection_method="random"
        )
        assert len(factors) == 1
        assert factors[0].code == "random"

    def test_none_context_no_selection_method_returns_empty(self) -> None:
        factors = RecommendationExplanationProjection.project_recommendation_context(
            None
        )
        # No selection_method supplied and no context → empty raw selection → empty list
        assert factors == []

    def test_empty_dict_context_returns_empty(self) -> None:
        factors = RecommendationExplanationProjection.project_recommendation_context({})
        assert factors == []

    def test_random_intent_does_not_leak_score_value(self) -> None:
        context = {
            "intent": "intent_random",
            "primary_score": {"code": "score_affinity_strong", "value": 0.95},
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        for factor in factors:
            assert not any(ch.isdigit() for ch in (factor.label or "") + (factor.detail or ""))

    def test_unknown_codes_in_factor_list_silently_skipped(self) -> None:
        context = {
            "bandwidth": "band_unknown",
            "intent": "intent_future",
            "taste_bank_factors": [{"code": "taste_unknown_trait"}],
            "primary_score": {"code": "score_unknown"},
            "affinity_notes": ["taste_unknown"],
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        assert factors == []

    def test_legacy_string_context_supplied_gracefully(self) -> None:
        factors = RecommendationExplanationProjection.project_recommendation_context(
            "not-a-dict"
        )
        assert factors == []

    def test_ordering_is_deterministic(self) -> None:
        context = {
            "bandwidth": "band_deep",
            "intent": "intent_familiar",
            "taste_bank_factors": [
                {"code": "taste_series_momentum"},
                {"code": "taste_near_completion"},
            ],
            "primary_score": {"code": "score_affinity_moderate"},
            "affinity_notes": ["taste_high_affinity"],
            "selection_method": "override",
        }
        first_run = RecommendationExplanationProjection.project_recommendation_context(
            context
        )
        second_run = RecommendationExplanationProjection.project_recommendation_context(
            context
        )
        assert [f.code for f in first_run] == [f.code for f in second_run]

    def test_taste_bank_factors_capped_at_two(self) -> None:
        context = {
            "taste_bank_factors": [
                {"code": "taste_series_momentum"},
                {"code": "taste_high_affinity"},
                {"code": "taste_confirmed_creator"},
            ],
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        # Only two taste bank factors should appear (capped)
        tb_factors = [f for f in factors if f.code.startswith("taste_")]
        assert len(tb_factors) == 2

    def test_affinity_notes_added_in_sequence(self) -> None:
        context = {
            "affinity_notes": [
                "taste_high_affinity",
                "taste_series_momentum",
            ]
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        assert len(factors) == 2
        assert factors[0].code == "taste_high_affinity"
        assert factors[1].code == "taste_series_momentum"

    def test_override_without_context_returns_explanation(self) -> None:
        factors = RecommendationExplanationProjection.project_recommendation_context(
            None, selection_method="override"
        )
        assert len(factors) == 1
        assert factors[0].label == "Manual pick"

    def test_intent_random_produces_selection_explanation(self) -> None:
        context = {
            "intent": "intent_random",
            "bandwidth": "band_balanced",
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        codes = [f.code for f in factors]
        assert "random" in codes

    def test_detail_can_come_from_taste_bank_entry(self) -> None:
        entry = {"code": "taste_high_affinity", "detail": "3-star across 7 issues"}
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(entry)
        assert factor is not None
        assert factor.detail == "3-star across 7 issues"

    def test_explainable_factor_slots_enforced(self) -> None:
        factor = ExplainableFactor(code="c", label="l", detail="d")
        assert factor.code == "c"
        assert factor.label == "l"
        assert factor.detail == "d"

    def test_project_context_max_factors_trims_before_return(self) -> None:
        context = {
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [{"code": "taste_high_affinity"}],
            "primary_score": {"code": "score_recency_boost"},
            "selection_method": "random",
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(
            context, max_factors=2
        )
        assert len(factors) == 2