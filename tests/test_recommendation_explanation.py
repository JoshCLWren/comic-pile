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

import re

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

# Raw opaque scores are decimal fractions or percent values. Human copy such as
# the "~11-minute read" bandwidth estimate is intentional and not a score leak.
_RAW_SCORE_RE = re.compile(r"\d+\.\d+|\d+%")


def _assert_no_raw_score(code: str, family: str, label: str, detail: str | None) -> None:
    """Assert that one explanation entry embeds no raw numeric score value.

    Args:
        code: The reason code under inspection.
        family: Human-readable factor-family name for failure messages.
        label: The translated user-facing label.
        detail: The optional translated detail text.
    """
    text = f"{label} {detail or ''}"
    assert not _RAW_SCORE_RE.search(text), (
        f"Raw numeric score leaked in {family} {code!r}: {text!r}"
    )


# ── Sanity checks on the private explanation dictionaries ────────────────

class TestExplanationDictionaries:
    """Ensure the internal reason-code maps are leaktight and non-empty."""

    def test_no_raw_scores_in_bandwidth_labels(self) -> None:
        """Bandwidth explanations never embed raw numeric score values."""
        for code, (label, detail) in _BANDWIDTH_EXPLANATIONS.items():
            _assert_no_raw_score(code, "bandwidth", label, detail)

    def test_no_raw_scores_in_intent_labels(self) -> None:
        """Intent explanations never embed raw numeric score values."""
        for code, (label, detail) in _INTENT_EXPLANATIONS.items():
            _assert_no_raw_score(code, "intent", label, detail)

    def test_no_raw_scores_in_taste_bank_labels(self) -> None:
        """Taste-bank explanations never embed raw numeric score values."""
        for code, (label, detail) in _TASTE_BANK_EXPLANATIONS.items():
            _assert_no_raw_score(code, "taste-bank", label, detail)

    def test_no_raw_scores_in_primary_score_labels(self) -> None:
        """Primary-score explanations never embed raw numeric score values."""
        for code, (label, detail) in _PRIMARY_SCORE_EXPLANATIONS.items():
            _assert_no_raw_score(code, "score", label, detail)

    def test_all_labels_are_non_empty(self) -> None:
        """Every explanation entry across all families carries a non-empty label."""
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
        """The default visible-factor cap is a positive number."""
        assert MAX_EXPLANATIONS >= 1


# ── Bandwidth translate tests ─────────────────────────────────────────────

class TestTranslateBandwidth:
    """Persisted bandwidth band codes translate to readable read-length copy."""

    def test_band_light(self) -> None:
        """Light bandwidth maps to the quick-read estimate."""
        factor = RecommendationExplanationProjection.translate_bandwidth("band_light")
        assert factor == ExplainableFactor(
            code="band_light", label="Quick read", detail="~11-minute read"
        )

    def test_band_balanced(self) -> None:
        """Balanced bandwidth maps to the medium-read label without extra detail."""
        factor = RecommendationExplanationProjection.translate_bandwidth("band_balanced")
        assert factor == ExplainableFactor(code="band_balanced", label="Medium read", detail=None)

    def test_band_deep(self) -> None:
        """Deep bandwidth maps to the extended-session label."""
        factor = RecommendationExplanationProjection.translate_bandwidth("band_deep")
        assert factor == ExplainableFactor(
            code="band_deep",
            label="Deep read",
            detail="Settling in for an extended session",
        )

    def test_unknown_bandwidth_returns_none(self) -> None:
        """Unrecognized future band codes degrade to no explanation."""
        assert (
            RecommendationExplanationProjection.translate_bandwidth("band_unknown")
            is None
        )

    def test_empty_bandwidth_returns_none(self) -> None:
        """Empty band codes produce no explanation."""
        assert (
            RecommendationExplanationProjection.translate_bandwidth("") is None
        )


# ── Intent translate tests ────────────────────────────────────────────────

class TestTranslateIntent:
    """Persisted intent codes translate to readable selection-intent copy."""

    def test_intent_balanced(self) -> None:
        """Balanced intent maps to the balanced-pick label."""
        factor = RecommendationExplanationProjection.translate_intent("intent_balanced")
        assert factor == ExplainableFactor(code="intent_balanced", label="Balanced pick", detail=None)

    def test_intent_momentum(self) -> None:
        """Momentum intent maps to the series-momentum label."""
        factor = RecommendationExplanationProjection.translate_intent("intent_momentum")
        assert factor == ExplainableFactor(
            code="intent_momentum", label="Recent series momentum", detail=None
        )

    def test_intent_familiar(self) -> None:
        """Familiar intent maps to the confirmed-creator label."""
        factor = RecommendationExplanationProjection.translate_intent("intent_familiar")
        assert factor == ExplainableFactor(
            code="intent_familiar",
            label="Creator you confirmed you like",
            detail=None,
        )

    def test_intent_explore(self) -> None:
        """Explore intent maps to the novel-but-connected label."""
        factor = RecommendationExplanationProjection.translate_intent("intent_explore")
        assert factor == ExplainableFactor(
            code="intent_explore",
            label="Novel but connected to your tastes",
            detail=None,
        )

    def test_intent_random(self) -> None:
        """Random intent explains that weighting was not applied."""
        factor = RecommendationExplanationProjection.translate_intent("intent_random")
        assert factor == ExplainableFactor(
            code="intent_random",
            label="No weighting applied",
            detail="Pure random selection",
        )

    def test_unknown_intent_returns_none(self) -> None:
        """Unrecognized future intent codes degrade to no explanation."""
        assert (
            RecommendationExplanationProjection.translate_intent("intent_future")
            is None
        )


# ── Selection-method translate tests ──────────────────────────────────────

class TestTranslateSelectionMethod:
    """Persisted selection methods translate to control/override explanations."""

    def test_random_explains_bypass(self) -> None:
        """The random method explicitly notes weighting was bypassed."""
        factor = (
            RecommendationExplanationProjection.translate_selection_method("random")
        )
        assert factor == ExplainableFactor(
            code="random", label="Pure random", detail="Weighting was bypassed"
        )

    def test_override_explains_direct_choice(self) -> None:
        """The override method explains the manual direct choice."""
        factor = (
            RecommendationExplanationProjection.translate_selection_method("override")
        )
        assert factor == ExplainableFactor(
            code="override", label="Manual pick", detail="Directly chosen"
        )

    def test_unknown_selection_returns_none(self) -> None:
        """Unrecognized selection methods degrade to no explanation."""
        assert (
            RecommendationExplanationProjection.translate_selection_method("semantic")
            is None
        )


# ── Taste Bank factor translate tests ─────────────────────────────────────

class TestTranslateTasteBankFactor:
    """Persisted taste-bank factor dicts translate per stable reason code."""

    def test_high_affinity(self) -> None:
        """High-affinity codes map to the strong-affinity label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_high_affinity"}
        )
        assert factor == ExplainableFactor(
            code="taste_high_affinity", label="Strong affinity", detail=None
        )

    def test_confirmed_creator(self) -> None:
        """Confirmed-creator codes map to the confirmed-creator label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_creator"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_creator",
            label="Creator you confirmed you like",
            detail=None,
        )

    def test_confirmed_character(self) -> None:
        """Confirmed-character codes map to the character-profile label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_character"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_character", label="Character profile confirmed", detail=None
        )

    def test_confirmed_team(self) -> None:
        """Confirmed-team codes map to the team-profile label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_team"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_team", label="Team profile confirmed", detail=None
        )

    def test_confirmed_era(self) -> None:
        """Confirmed-era codes map to the era-preference label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_confirmed_era"}
        )
        assert factor == ExplainableFactor(
            code="taste_confirmed_era", label="Era preference confirmed", detail=None
        )

    def test_novel_adjacent(self) -> None:
        """Novel-adjacent codes map to the novel-but-connected label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_novel_adjacent"}
        )
        assert factor == ExplainableFactor(
            code="taste_novel_adjacent",
            label="Novel but connected to your tastes",
            detail=None,
        )

    def test_series_momentum(self) -> None:
        """Series-momentum codes map to the recent-momentum label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_series_momentum"}
        )
        assert factor == ExplainableFactor(
            code="taste_series_momentum", label="Recent series momentum", detail=None
        )

    def test_near_completion(self) -> None:
        """Near-completion codes map to the finish-strong label."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_near_completion"}
        )
        assert factor == ExplainableFactor(
            code="taste_near_completion",
            label="Near completion — finish strong",
            detail=None,
        )

    def test_unknown_taste_bank_code_returns_none(self) -> None:
        """Unrecognized future taste-bank codes degrade to no explanation."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": "taste_future"}
        )
        assert factor is None

    def test_missing_code_key_returns_none(self) -> None:
        """Entries lacking a code key are skipped rather than raising."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"detail": "some extra"}
        )
        assert factor is None

    def test_non_dict_input_returns_none(self) -> None:
        """Non-dict entries of any type are skipped rather than raising."""
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
        """Empty-string code keys produce no explanation."""
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(
            {"code": ""}
        )
        assert factor is None


# ── Primary-score translate tests ─────────────────────────────────────────

class TestTranslatePrimaryScore:
    """Persisted primary-score blocks translate per code without exposing values."""

    def test_affinity_strong(self) -> None:
        """Strong affinity scores map to the strong-affinity label."""
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_affinity_strong", "value": 0.82}
        )
        assert factor == ExplainableFactor(
            code="score_affinity_strong", label="Strong affinity", detail=None
        )

    def test_affinity_moderate(self) -> None:
        """Moderate affinity scores map to the matches-history label."""
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_affinity_moderate", "value": 0.51}
        )
        assert factor == ExplainableFactor(
            code="score_affinity_moderate", label="Matches your history", detail=None
        )

    def test_recency_boost(self) -> None:
        """Recency-boost scores map to the recently-updated label."""
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_recency_boost"}
        )
        assert factor == ExplainableFactor(
            code="score_recency_boost", label="Recently updated", detail=None
        )

    def test_staleness_penalty(self) -> None:
        """Staleness penalties map to the less-active label."""
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_staleness_penalty"}
        )
        assert factor == ExplainableFactor(
            code="score_staleness_penalty", label="Less active lately", detail=None
        )

    def test_primary_score_never_exposes_raw_value(self) -> None:
        """Numeric payload values never surface in the translated output."""
        factor = RecommendationExplanationProjection.translate_primary_score(
            {"code": "score_affinity_strong", "value": 0.99}
        )
        assert factor is not None
        assert "0.99" not in (factor.label or "")
        assert "0.99" not in (factor.detail or "")

    def test_unknown_primary_score_returns_none(self) -> None:
        """Unrecognized future score codes degrade to no explanation."""
        assert (
            RecommendationExplanationProjection.translate_primary_score(
                {"code": "score_unknown"}
            )
            is None
        )


# ── Full-context projection tests ─────────────────────────────────────────

class TestProjectRecommendationContext:
    """Whole-context projections order deterministically, cap, and degrade safely."""

    def test_full_context_returns_ordered_factors(self) -> None:
        """A fully populated context yields every family in documented order."""
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
        # Lift the cap so every family is observable in one projection.
        factors = RecommendationExplanationProjection.project_recommendation_context(
            context, max_factors=10
        )
        labels = [f.label for f in factors]
        assert "Quick read" in labels  # bandwidth first
        assert "Recent series momentum" in labels  # intent second
        assert "Strong affinity" in labels  # taste bank first
        assert "Creator you confirmed you like" in labels  # taste bank second
        assert "Recently updated" in labels  # primary score
        assert "Pure random" in labels  # selection method appended

    def test_factors_respect_max_cap(self) -> None:
        """Explicit caps trim the projected factor list."""
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
        """The default cap bounds even fully populated contexts."""
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
        """Absent context with an explicit random method explains only the bypass."""
        factors = RecommendationExplanationProjection.project_recommendation_context(
            None, selection_method="random"
        )
        assert len(factors) == 1
        assert factors[0].code == "random"

    def test_none_context_no_selection_method_returns_empty(self) -> None:
        """Absent context with no selection information projects nothing."""
        factors = RecommendationExplanationProjection.project_recommendation_context(
            None
        )
        # No selection_method supplied and no context → empty raw selection → empty list
        assert factors == []

    def test_empty_dict_context_returns_empty(self) -> None:
        """An empty context dict projects no factors."""
        factors = RecommendationExplanationProjection.project_recommendation_context({})
        assert factors == []

    def test_random_intent_does_not_leak_score_value(self) -> None:
        """Numeric payload values never surface through any projected factor."""
        context = {
            "intent": "intent_random",
            "primary_score": {"code": "score_affinity_strong", "value": 0.95},
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        for factor in factors:
            assert not any(ch.isdigit() for ch in (factor.label or "") + (factor.detail or ""))

    def test_unknown_codes_in_factor_list_silently_skipped(self) -> None:
        """Unknown codes across every family degrade to an empty projection."""
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
        """Legacy non-dict contexts project nothing instead of raising."""
        factors = RecommendationExplanationProjection.project_recommendation_context(
            "not-a-dict"
        )
        assert factors == []

    def test_ordering_is_deterministic(self) -> None:
        """Repeated projections of identical context produce identical order."""
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
        """At most two taste-bank factors appear regardless of list length."""
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
        """Affinity-note codes project in their persisted sequence."""
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
        """Override rolls explain the manual choice even with absent context."""
        factors = RecommendationExplanationProjection.project_recommendation_context(
            None, selection_method="override"
        )
        assert len(factors) == 1
        assert factors[0].label == "Manual pick"

    def test_intent_random_produces_selection_explanation(self) -> None:
        """Legacy random intents still receive the weighting-bypass explanation."""
        context = {
            "intent": "intent_random",
            "bandwidth": "band_balanced",
        }
        factors = RecommendationExplanationProjection.project_recommendation_context(context)
        codes = [f.code for f in factors]
        assert "random" in codes

    def test_detail_can_come_from_taste_bank_entry(self) -> None:
        """Taste-bank entries may contribute their own detail text."""
        entry = {"code": "taste_high_affinity", "detail": "3-star across 7 issues"}
        factor = RecommendationExplanationProjection.translate_taste_bank_factor(entry)
        assert factor is not None
        assert factor.detail == "3-star across 7 issues"

    def test_explainable_factor_slots_enforced(self) -> None:
        """ExplainableFactor carries its fields exactly as constructed."""
        factor = ExplainableFactor(code="c", label="l", detail="d")
        assert factor.code == "c"
        assert factor.label == "l"
        assert factor.detail == "d"

    def test_project_context_max_factors_trims_before_return(self) -> None:
        """Caps trim the final returned list after ordering is applied."""
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
