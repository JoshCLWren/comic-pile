"""Tests for versioned recommendation-context snapshots on roll events."""

import math
import random

import pytest

from comic_pile.recommendation_context import (
    BYPASS_BALANCED_NEUTRAL,
    BYPASS_INVALID_WEIGHTS,
    BYPASS_RANDOM_INTENT,
    BYPASS_UNIFORM_POOL,
    RECOMMENDATION_CONTEXT_VERSION,
    WEIGHTING_MODE_BYPASSED,
    WEIGHTING_MODE_WEIGHTED,
    build_recommendation_context,
    candidate_reason_codes,
    classify_effort,
    normalize_bandwidth,
    normalize_intent,
    read_recommendation_context,
    resolve_selection_plan,
)


def _plan(
    *efforts: int | None,
    bandwidth: str | None = None,
    intent: str | None = None,
    rng: random.Random | None = None,
):
    """Resolve a selection plan from a compact effort list."""
    return resolve_selection_plan(list(efforts), bandwidth=bandwidth, intent=intent, rng=rng)


class TestClassifyEffort:
    def test_none_is_unknown(self) -> None:
        assert classify_effort(None) == "unknown"

    def test_low_band(self) -> None:
        assert classify_effort(0) == "low"
        assert classify_effort(3) == "low"

    def test_medium_band(self) -> None:
        assert classify_effort(4) == "medium"
        assert classify_effort(10) == "medium"

    def test_high_band(self) -> None:
        assert classify_effort(11) == "high"
        assert classify_effort(500) == "high"


class TestNormalizeVocabulary:
    def test_none_defaults_to_balanced(self) -> None:
        assert normalize_bandwidth(None) == "balanced"
        assert normalize_intent(None) == "balanced"

    def test_unknown_values_raise(self) -> None:
        with pytest.raises(ValueError, match="Unknown bandwidth"):
            normalize_bandwidth("spicy")
        with pytest.raises(ValueError, match="Unknown intent"):
            normalize_intent("chaos")


class TestResolveSelectionPlan:
    def test_empty_pool_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one candidate"):
            resolve_selection_plan([], bandwidth="light")

    def test_random_intent_bypasses_weights_completely(self) -> None:
        plan = _plan(1, 40, 7, bandwidth="deep", intent="random", rng=random.Random(7))
        assert plan.mode == WEIGHTING_MODE_BYPASSED
        assert plan.bypass_reason == BYPASS_RANDOM_INTENT
        assert plan.weighting_applied is False
        assert all(weight == 1.0 for weight in plan.weights)
        assert 0 <= plan.index < 3

    def test_balanced_default_is_neutral_control(self) -> None:
        plan = _plan(2, 9, 30, rng=random.Random(11))
        assert plan.mode == WEIGHTING_MODE_BYPASSED
        assert plan.bypass_reason == BYPASS_BALANCED_NEUTRAL
        assert plan.weighting_applied is False
        assert set(plan.weights) == {1.0}

    def test_light_favors_lower_effort(self) -> None:
        plan = _plan(1, 6, 20, bandwidth="light", rng=random.Random(3))
        assert plan.weighting_applied is True
        assert plan.mode == WEIGHTING_MODE_WEIGHTED
        assert plan.weights[0] > plan.weights[1] > plan.weights[2]

    def test_deep_favors_higher_effort_without_excluding_low(self) -> None:
        plan = _plan(1, 6, 20, bandwidth="deep", rng=random.Random(5))
        assert plan.weighting_applied is True
        assert plan.weights[2] > plan.weights[1] > plan.weights[0]
        # Lower-effort candidates stay selectable: positive weight.
        assert all(weight > 0.0 for weight in plan.weights)

    def test_light_selection_is_statistically_biased_toward_low_effort(self) -> None:
        rng = random.Random(2024)
        low_effort_wins = 0
        trials = 400
        for _ in range(trials):
            plan = resolve_selection_plan([0, 900], bandwidth="light", rng=rng)
            if plan.index == 0:
                low_effort_wins += 1
        # Weight ratio is 3.0 : 0.5, so the low-effort candidate must dominate.
        assert low_effort_wins > trials * 0.75

    def test_uniform_pool_under_weighted_mode_falls_back_with_reason(self) -> None:
        plan = _plan(4, 4, 4, bandwidth="light", rng=random.Random(13))
        assert plan.weighting_applied is False
        assert plan.bypass_reason == BYPASS_UNIFORM_POOL
        assert set(plan.weights) == {1.5}

    def test_invalid_weights_fall_back_safely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from comic_pile import recommendation_context as rc

        monkeypatch.setitem(
            rc.BANDWIDTH_EFFORT_WEIGHTS,
            "light",
            {"low": 0.0, "medium": 1.5, "high": 2.0, "unknown": 1.0},
        )
        plan = _plan(1, 6, bandwidth="light", rng=random.Random(17))
        assert plan.weighting_applied is False
        assert plan.bypass_reason == BYPASS_INVALID_WEIGHTS
        assert set(plan.weights) == {1.0}

    def test_single_candidate_returns_index_zero(self) -> None:
        plan = _plan(12, bandwidth="light", rng=random.Random(19))
        assert plan.index == 0
        assert len(plan.weights) == 1


class TestReasonCodes:
    def test_weighted_codes_explain_direction(self) -> None:
        plan = _plan(1, 20, bandwidth="light", rng=random.Random(23))
        codes = [candidate_reason_codes(plan, i) for i in range(len(plan.weights))]
        assert codes[0] == ("effort:low", "w:up")
        assert codes[1] == ("effort:high", "w:down")

    def test_unknown_effort_stays_flat(self) -> None:
        plan = _plan(1, None, bandwidth="light", rng=random.Random(29))
        assert plan.weights[1] == 1.0
        assert candidate_reason_codes(plan, 1) == ("effort:unknown", "w:flat")

    def test_bypass_codes_name_the_reason(self) -> None:
        plan = _plan(1, 2, intent="random", rng=random.Random(31))
        assert candidate_reason_codes(plan, 0) == ("effort:low", "bypass:random_intent")


class TestBuildContext:
    def _thread_ids(self, count: int) -> list[int]:
        return [100 + position for position in range(count)]

    def test_version_is_current(self) -> None:
        plan = _plan(1, 8, bandwidth="light", rng=random.Random(37))
        context = build_recommendation_context(
            thread_ids=self._thread_ids(2),
            die_size=20,
            bandwidth="light",
            intent=None,
            plan=plan,
        )
        assert context["version"] == RECOMMENDATION_CONTEXT_VERSION
        assert RECOMMENDATION_CONTEXT_VERSION >= 1

    def test_candidate_weights_match_passed_selection_weights(self) -> None:
        plan = _plan(2, 9, 30, bandwidth="light", rng=random.Random(41))
        context = build_recommendation_context(
            thread_ids=self._thread_ids(3),
            die_size=50,
            bandwidth="light",
            intent=None,
            plan=plan,
        )
        candidates = context["candidates"]
        assert isinstance(candidates, list)
        assert [entry["weight"] for entry in candidates] == [
            round(float(weight), 6) for weight in plan.weights
        ]
        assert [entry["thread_id"] for entry in candidates] == self._thread_ids(3)
        selected = candidates[plan.index]
        assert selected["thread_id"] == context["selected_thread_id"]
        assert selected["weight"] == context["selected_weight"]

    def test_selected_candidate_records_final_weight_and_bandwidth(self) -> None:
        plan = _plan(1, 8, bandwidth="light", rng=random.Random(43))
        context = build_recommendation_context(
            thread_ids=self._thread_ids(2),
            die_size=20,
            bandwidth="light",
            intent=None,
            plan=plan,
        )
        assert context["bandwidth"] == "light"
        assert context["intent"] == "balanced"
        assert context["mode"] == WEIGHTING_MODE_WEIGHTED
        assert context["selected_weight"] == plan.weights[plan.index]
        assert context["pool_size"] == 2
        assert context["die_size"] == 20

    def test_payload_is_bounded_and_compact(self) -> None:
        plan = _plan(*([2] * 12), bandwidth="light", rng=random.Random(47))
        context = build_recommendation_context(
            thread_ids=self._thread_ids(12),
            die_size=100,
            bandwidth="light",
            intent=None,
            plan=plan,
        )
        serialized = repr(sorted(context.keys()))
        assert "candidates" in serialized
        allowed_top_level = {
            "version",
            "mode",
            "bandwidth",
            "intent",
            "bandwidth_source",
            "bandwidth_confidence",
            "die_size",
            "pool_size",
            "selected_index",
            "selected_thread_id",
            "selected_weight",
            "candidates",
        }
        assert set(context.keys()) <= allowed_top_level
        for entry in context["candidates"]:
            assert set(entry.keys()) == {"thread_id", "weight", "reasons"}

    def test_misaligned_inputs_rejected(self) -> None:
        plan = _plan(1, 8, bandwidth="light", rng=random.Random(53))
        with pytest.raises(ValueError, match="align"):
            build_recommendation_context(
                thread_ids=[1],
                die_size=20,
                bandwidth="light",
                intent=None,
                plan=plan,
            )


class TestReadContextVersions:
    def test_current_version_roundtrip(self) -> None:
        plan = _plan(2, 9, bandwidth="light", rng=random.Random(59))
        payload = build_recommendation_context(
            thread_ids=[7, 8, 9],
            die_size=20,
            bandwidth="light",
            intent=None,
            plan=plan,
            bandwidth_source="request",
            bandwidth_confidence=1.0,
        )
        view = read_recommendation_context(payload)
        assert view.readable is True
        assert view.version == RECOMMENDATION_CONTEXT_VERSION
        assert view.mode == WEIGHTING_MODE_WEIGHTED
        assert view.bandwidth == "light"
        assert view.selected_thread_id == payload["selected_thread_id"]
        assert view.selected_weight == payload["selected_weight"]
        assert view.weighting_applied is True
        assert [thread_id for thread_id, _weight in view.candidate_weights] == [7, 8, 9]
        assert all(math.isfinite(weight) for _t, weight in view.candidate_weights)

    def test_unversioned_legacy_payload_remains_readable(self) -> None:
        legacy = {
            "selected_thread_id": 42,
            "selected_weight": 2.5,
            "candidates": [{"thread_id": 42, "weight": 2.5, "reasons": ["effort:low"]}],
        }
        view = read_recommendation_context(legacy)
        assert view.readable is True
        assert view.version == 0
        assert view.selected_thread_id == 42
        assert view.selected_weight == 2.5
        assert view.candidate_weights == ((42, 2.5),)
        assert view.candidate_reason_codes == (("effort:low",),)

    def test_newer_version_still_readable_best_effort(self) -> None:
        future = {
            "version": RECOMMENDATION_CONTEXT_VERSION + 99,
            "mode": WEIGHTING_MODE_WEIGHTED,
            "future_field": {"unheard": "of"},
            "selected_thread_id": 5,
            "selected_weight": 3.0,
            "candidates": [],
        }
        view = read_recommendation_context(future)
        assert view.readable is True
        assert view.version == RECOMMENDATION_CONTEXT_VERSION + 99
        assert view.selected_thread_id == 5
        assert view.candidate_weights == ()

    def test_non_mapping_payloads_do_not_crash(self) -> None:
        for garbage in (None, [], "context", 17):
            view = read_recommendation_context(garbage)
            assert view.readable is False

    def test_malformed_fields_are_dropped_not_fatal(self) -> None:
        payload = {
            "version": 1,
            "mode": "bogus-mode",
            "selected_weight": "not-a-number",
            "candidates": [
                {"thread_id": "x", "weight": -3},
                {"thread_id": 9, "weight": 1.25, "reasons": "flat"},
            ],
        }
        view = read_recommendation_context(payload)
        assert view.readable is True
        assert view.mode is None
        assert view.selected_weight is None
        assert view.candidate_weights == ((9, 1.25),)
        assert view.candidate_reason_codes == ((),)


class TestBypassContextRoundtrip:
    def test_random_roll_records_explicit_neutral_bypass(self) -> None:
        plan = _plan(3, 14, intent="random", rng=random.Random(61))
        payload = build_recommendation_context(
            thread_ids=[11, 12],
            die_size=20,
            bandwidth="deep",
            intent="random",
            plan=plan,
        )
        view = read_recommendation_context(payload)
        assert view.weighting_applied is False
        assert view.mode == WEIGHTING_MODE_BYPASSED
        assert set(weight for _t, weight in view.candidate_weights) == {1.0}
        reasons = payload["candidates"]
        assert all("bypass:random_intent" in entry["reasons"] for entry in reasons)
