"""Unit tests for bounded bandwidth x intent recommendation weighting (#1761).

These tests are pure unit tests: they exercise only the standard-library
``comic_pile.recommendation_weighting`` module and require no database.
"""

import math
import random

import pytest

from comic_pile.recommendation_weighting import (
    BANDWIDTH_DEEP,
    BANDWIDTH_DEVIATION_CAP,
    BANDWIDTH_BALANCED,
    BANDWIDTH_LIGHT,
    EXPLORE_FACTOR_CAP,
    EXPLORE_NOVEL_BONUS,
    FAMILIAR_AGGREGATE_BONUS_CAP,
    FAMILIAR_FACTOR_CAP,
    FINAL_WEIGHT_CAP,
    FINAL_WEIGHT_FLOOR,
    INTENT_BALANCED,
    INTENT_EXPLORE,
    INTENT_FAMILIAR,
    INTENT_MOMENTUM,
    INTENT_RANDOM,
    MOMENTUM_FACTOR_CAP,
    REASON_EFFORT_UNKNOWN_NEUTRAL,
    REASON_FINAL_WEIGHT_CLAMPED,
    REASON_INTENT_BALANCED_NEUTRAL,
    REASON_KNOWN_CANDIDATE_NEUTRAL,
    REASON_LESS_EXPOSED_CANDIDATE,
    REASON_LOW_RATING_NO_BOOST,
    REASON_NOVEL_CANDIDATE,
    REASON_STALE_RUN_DECAY,
    REASON_TASTE_ADJACENT,
    REASON_TASTE_REJECTED_IGNORED,
    VERDICT_CONFIRMED,
    VERDICT_INFERRED,
    VERDICT_REJECTED,
    VERDICT_SOMETIMES,
    CandidateSignals,
    bandwidth_factor,
    combine_factors,
    explore_factor,
    familiar_factor,
    intent_factor,
    momentum_factor,
    select_candidate_index,
    weight_candidate,
    weight_pool,
)


def _momentum_bonus(decay: float, strength: float, streak: int = 0) -> float:
    """Recompute the expected momentum bonus for deterministic assertions."""
    from comic_pile.recommendation_weighting import (
        MOMENTUM_BASE_BONUS,
        MOMENTUM_STREAK_BONUS_PER_READ,
    )

    return (
        MOMENTUM_BASE_BONUS * decay * strength
        + min(streak, 4) * MOMENTUM_STREAK_BONUS_PER_READ * decay
    )


class TestBandwidthFactor:
    """Bandwidth-side factor behavior."""

    def test_light_bandwidth_boosts_light_effort(self) -> None:
        """Light bandwidth aligns with light effort as a small boost."""
        factor, reasons = bandwidth_factor(BANDWIDTH_LIGHT, 8.0)
        assert factor == 1.10
        assert reasons == ("bandwidth_effort_aligned",)

    def test_light_bandwidth_dampens_heavy_effort(self) -> None:
        """Light bandwidth misaligns with heavy effort as a capped dampening."""
        factor, reasons = bandwidth_factor(BANDWIDTH_LIGHT, 30.0)
        assert factor == 1.0 - BANDWIDTH_DEVIATION_CAP
        assert reasons == ("bandwidth_effort_misaligned",)

    def test_deep_bandwidth_mirrors_light(self) -> None:
        """Deep bandwidth dampens light effort and boosts heavy effort."""
        light_factor, _ = bandwidth_factor(BANDWIDTH_DEEP, 5.0)
        heavy_factor, _ = bandwidth_factor(BANDWIDTH_DEEP, 25.0)
        assert light_factor == 0.90
        assert heavy_factor == 1.10

    def test_balanced_bandwidth_is_exactly_neutral(self) -> None:
        """Balanced bandwidth never deviates regardless of effort."""
        for effort in (None, 5.0, 15.0, 40.0):
            factor, reasons = bandwidth_factor(BANDWIDTH_BALANCED, effort)
            assert factor == 1.0
            assert reasons == ()

    def test_unknown_effort_is_neutral_with_reason(self) -> None:
        """Missing effort fails to neutral instead of guessing."""
        factor, reasons = bandwidth_factor(BANDWIDTH_LIGHT, None)
        assert factor == 1.0
        assert reasons == (REASON_EFFORT_UNKNOWN_NEUTRAL,)

    def test_invalid_bandwidth_raises(self) -> None:
        """Unrecognized bandwidth labels are rejected."""
        with pytest.raises(ValueError, match="Invalid bandwidth"):
            bandwidth_factor("extreme", 10.0)


class TestMomentumFactor:
    """Momentum intent factor behavior feeding the combination."""

    def test_recent_high_rating_receives_decaying_boost(self) -> None:
        """A fresh high rating produces a positive, capped factor."""
        signals = CandidateSignals(thread_id=1, last_rating=5.0, days_since_last_read=1.0)
        factor, reasons = momentum_factor(signals)
        decay = 0.5 ** (1.0 / 14.0)
        assert factor == pytest.approx(1.0 + _momentum_bonus(decay, 1.0))
        assert "recent_high_rating" in reasons
        assert factor <= MOMENTUM_FACTOR_CAP

    def test_momentum_decays_with_staleness(self) -> None:
        """Older reads lose their boost until fully stale."""
        fresh = momentum_factor(
            CandidateSignals(thread_id=1, last_rating=5.0, days_since_last_read=1.0)
        )[0]
        week = momentum_factor(
            CandidateSignals(thread_id=1, last_rating=5.0, days_since_last_read=7.0)
        )[0]
        stale = momentum_factor(
            CandidateSignals(thread_id=1, last_rating=5.0, days_since_last_read=60.0)
        )
        assert fresh > week > 1.0
        assert stale == (1.0, (REASON_STALE_RUN_DECAY,))

    def test_low_rated_recent_run_gets_no_boost_for_recency(self) -> None:
        """Recency alone cannot boost a low-rated run."""
        factor, reasons = momentum_factor(
            CandidateSignals(thread_id=1, last_rating=2.0, days_since_last_read=0.5)
        )
        assert factor == 1.0
        assert reasons == (REASON_LOW_RATING_NO_BOOST,)

    def test_streak_adds_capped_increment(self) -> None:
        """Streak depth adds a bounded increment beyond the base bonus."""
        base_signals = CandidateSignals(thread_id=1, last_rating=5.0, days_since_last_read=0.0)
        streaked = CandidateSignals(
            thread_id=1,
            last_rating=5.0,
            days_since_last_read=0.0,
            high_rated_streak=99,
        )
        base_factor = momentum_factor(base_signals)[0]
        streaked_factor, reasons = momentum_factor(streaked)
        assert streaked_factor > base_factor
        # 0.25 base + 4 * 0.05 streak = 0.45 total bonus, under the 0.5 cap room.
        assert streaked_factor == pytest.approx(1.45)
        assert streaked_factor <= MOMENTUM_FACTOR_CAP
        assert "high_rated_streak" in reasons

    def test_missing_history_is_neutral(self) -> None:
        """No rating or no recency evidence stays exactly neutral."""
        assert momentum_factor(CandidateSignals(thread_id=1)) == (1.0, ())
        assert momentum_factor(CandidateSignals(thread_id=1, last_rating=5.0)) == (1.0, ())
        assert momentum_factor(CandidateSignals(thread_id=1, days_since_last_read=1.0)) == (1.0, ())


class TestFamiliarFactor:
    """Familiar taste aggregation and its deliberate aggregate cap."""

    def test_confirmed_match_beats_sometimes(self) -> None:
        """Confirmed verdicts weigh more than qualified ones."""
        confirmed = familiar_factor(
            CandidateSignals(
                thread_id=1, matched_verdict_by_category={"creator": VERDICT_CONFIRMED}
            )
        )[0]
        sometimes = familiar_factor(
            CandidateSignals(
                thread_id=1, matched_verdict_by_category={"creator": VERDICT_SOMETIMES}
            )
        )[0]
        assert confirmed == pytest.approx(1.15)
        assert sometimes == pytest.approx(1.075)
        assert confirmed > sometimes > 1.0

    def test_rejected_signals_never_boost(self) -> None:
        """Rejected verdicts contribute nothing positive."""
        factor, reasons = familiar_factor(
            CandidateSignals(thread_id=1, matched_verdict_by_category={"creator": VERDICT_REJECTED})
        )
        assert factor == 1.0
        assert reasons == (REASON_TASTE_REJECTED_IGNORED,)

    def test_inferred_signals_never_boost(self) -> None:
        """Unconfirmed inferred evidence contributes nothing positive."""
        factor, _ = familiar_factor(
            CandidateSignals(thread_id=1, matched_verdict_by_category={"team": VERDICT_INFERRED})
        )
        assert factor == 1.0

    def test_correlated_metadata_aggregates_under_single_cap(self) -> None:
        """Many correlated confirmed matches stop at one aggregate cap."""
        all_confirmed = dict.fromkeys(
            ("creator", "character", "team", "publisher", "era"),
            VERDICT_CONFIRMED,
        )
        factor, _ = familiar_factor(
            CandidateSignals(thread_id=1, matched_verdict_by_category=all_confirmed)
        )
        # Additive aggregation hits exactly the aggregate cap, not 1.15^5.
        assert factor == pytest.approx(1.0 + FAMILIAR_AGGREGATE_BONUS_CAP)
        assert factor <= FAMILIAR_FACTOR_CAP

    def test_missing_metadata_is_neutral(self) -> None:
        """No matched verdicts stay exactly neutral."""
        assert familiar_factor(CandidateSignals(thread_id=1)) == (1.0, ())


class TestExploreFactor:
    """Explore novelty/adjacency behavior feeding the combination."""

    def test_unread_candidate_gets_novelty_bonus(self) -> None:
        """Unread candidates earn the largest bounded novelty bonus."""
        factor, reasons = explore_factor(CandidateSignals(thread_id=1))
        assert factor == pytest.approx(1.15)
        assert REASON_NOVEL_CANDIDATE in reasons

    def test_less_exposed_candidate_gets_partial_bonus(self) -> None:
        """Lightly-exposed candidates earn a smaller bonus."""
        factor, reasons = explore_factor(CandidateSignals(thread_id=1, prior_exposure_count=2))
        assert factor == pytest.approx(1.075)
        assert REASON_LESS_EXPOSED_CANDIDATE in reasons

    def test_known_candidates_stay_eligible_and_neutral(self) -> None:
        """Well-read candidates are neutral, never excluded or penalized."""
        factor, reasons = explore_factor(CandidateSignals(thread_id=1, prior_exposure_count=7))
        assert factor == 1.0
        assert reasons == (REASON_KNOWN_CANDIDATE_NEUTRAL,)

    def test_adjacency_bounded_by_anchor_cap(self) -> None:
        """Adjacency adds at most the capped anchor count."""
        anchored = CandidateSignals(
            thread_id=1,
            adjacent_anchor_categories=("creator", "publisher", "era"),
        )
        factor, reasons = explore_factor(anchored)
        assert factor == pytest.approx(1.0 + 0.15 + 2 * 0.05)
        assert REASON_TASTE_ADJACENT in reasons
        assert factor <= EXPLORE_FACTOR_CAP


class TestCombinationContract:
    """The central bandwidth x intent combination contract (#1761)."""

    def test_light_momentum_combines_predictably_within_caps(self) -> None:
        """Light + Momentum multiply once into a predictable capped weight."""
        signals = CandidateSignals(
            thread_id=42,
            effort_minutes=8.0,
            last_rating=5.0,
            days_since_last_read=1.0,
            high_rated_streak=2,
        )
        result = weight_candidate(BANDWIDTH_LIGHT, INTENT_MOMENTUM, signals)
        decay = 0.5 ** (1.0 / 14.0)
        expected_intent = 1.0 + _momentum_bonus(decay, 1.0, streak=2)
        assert result.bandwidth_factor == 1.10
        assert result.intent_factor == pytest.approx(expected_intent)
        assert result.final_weight == pytest.approx(round(1.10 * expected_intent, 6))
        assert FINAL_WEIGHT_FLOOR <= result.final_weight <= FINAL_WEIGHT_CAP
        assert result.reasons[0] == "bandwidth_effort_aligned"
        assert result.thread_id == 42

    def test_deep_explore_combination_remains_valid(self) -> None:
        """Deep + Explore composes into a valid bounded weight."""
        signals = CandidateSignals(
            thread_id=7,
            effort_minutes=25.0,
            prior_exposure_count=0,
            adjacent_anchor_categories=("creator",),
        )
        result = weight_candidate(BANDWIDTH_DEEP, INTENT_EXPLORE, signals)
        assert result.bandwidth_factor == 1.10
        assert result.intent_factor == pytest.approx(1.20)
        assert result.final_weight == pytest.approx(round(1.10 * 1.20, 6))
        assert FINAL_WEIGHT_FLOOR <= result.final_weight <= FINAL_WEIGHT_CAP

    @pytest.mark.parametrize("bandwidth", [BANDWIDTH_LIGHT, BANDWIDTH_BALANCED, BANDWIDTH_DEEP])
    @pytest.mark.parametrize(
        "intent",
        [INTENT_BALANCED, INTENT_MOMENTUM, INTENT_FAMILIAR, INTENT_EXPLORE],
    )
    def test_every_combination_stays_inside_final_caps(self, bandwidth: str, intent: str) -> None:
        """All bandwidth/intent pairs produce weights strictly inside the caps."""
        signals = CandidateSignals(
            thread_id=1,
            effort_minutes=9.0,
            last_rating=5.0,
            days_since_last_read=0.0,
            high_rated_streak=4,
            matched_verdict_by_category={
                "creator": VERDICT_CONFIRMED,
                "character": VERDICT_CONFIRMED,
                "team": VERDICT_CONFIRMED,
                "publisher": VERDICT_CONFIRMED,
                "era": VERDICT_CONFIRMED,
            },
            prior_exposure_count=0,
            adjacent_anchor_categories=("creator", "publisher", "era"),
        )
        result = weight_candidate(bandwidth, intent, signals)
        assert FINAL_WEIGHT_FLOOR <= result.final_weight <= FINAL_WEIGHT_CAP
        assert result.bandwidth_factor <= 1.0 + BANDWIDTH_DEVIATION_CAP
        assert result.intent_factor <= max(
            MOMENTUM_FACTOR_CAP, FAMILIAR_FACTOR_CAP, EXPLORE_FACTOR_CAP
        )

    def test_maximum_contextual_pressure_cannot_escape_final_cap(self) -> None:
        """Even maximal aligned factors remain under the central ceiling."""
        ceiling = combine_factors(
            1,
            1.0 + BANDWIDTH_DEVIATION_CAP,
            max(MOMENTUM_FACTOR_CAP, FAMILIAR_FACTOR_CAP, EXPLORE_FACTOR_CAP),
            (),
        )
        assert ceiling.final_weight <= FINAL_WEIGHT_CAP

    def test_combine_factors_clamps_out_of_range_inputs(self) -> None:
        """The central clamp is the last line of defense with an audit reason."""
        above = combine_factors(1, 2.0, 2.0, ())
        assert above.final_weight == FINAL_WEIGHT_CAP
        assert REASON_FINAL_WEIGHT_CLAMPED in above.reasons

        below = combine_factors(1, 0.9, 0.5, ())
        assert below.final_weight == FINAL_WEIGHT_FLOOR
        assert REASON_FINAL_WEIGHT_CLAMPED in below.reasons

    def test_combine_factors_rejects_non_positive_factors(self) -> None:
        """Non-finite or non-positive factors are rejected outright."""
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError, match="finite and positive"):
                combine_factors(1, bad, 1.0, ())


class TestBalancedNeutrality:
    """Balanced intent must add no hidden bias."""

    def test_balanced_intent_is_exactly_neutral_with_marker(self) -> None:
        """Balanced intent returns exactly 1.0 plus an explicit marker reason."""
        rich = CandidateSignals(
            thread_id=1,
            effort_minutes=8.0,
            last_rating=5.0,
            days_since_last_read=0.0,
            high_rated_streak=4,
            matched_verdict_by_category={"creator": VERDICT_CONFIRMED},
            prior_exposure_count=0,
            adjacent_anchor_categories=("creator",),
        )
        intent_result = intent_factor(INTENT_BALANCED, rich)
        assert intent_result == (1.0, (REASON_INTENT_BALANCED_NEUTRAL,))

    def test_balanced_intent_gives_identical_weights_regardless_of_signals(
        self,
    ) -> None:
        """Intent-side evidence cannot move any weight under balanced intent."""
        # Same effort evidence, wildly different taste/momentum/exposure evidence.
        plain = CandidateSignals(thread_id=1, effort_minutes=8.0)
        rich = CandidateSignals(
            thread_id=2,
            effort_minutes=8.0,
            last_rating=5.0,
            days_since_last_read=0.0,
            high_rated_streak=4,
            matched_verdict_by_category={"creator": VERDICT_CONFIRMED},
            prior_exposure_count=0,
            adjacent_anchor_categories=("creator",),
        )
        plain_weight = weight_candidate(BANDWIDTH_DEEP, INTENT_BALANCED, plain)
        rich_weight = weight_candidate(BANDWIDTH_DEEP, INTENT_BALANCED, rich)
        assert plain_weight.final_weight == rich_weight.final_weight == 0.90
        assert plain_weight.intent_factor == rich_weight.intent_factor == 1.0
        assert REASON_INTENT_BALANCED_NEUTRAL in plain_weight.reasons
        assert REASON_INTENT_BALANCED_NEUTRAL in rich_weight.reasons


class TestRandomBypass:
    """Random intent remains an exact contextual bypass."""

    def test_random_pool_produces_bypass_record_without_weights(self) -> None:
        """Random returns an explicit bypass record with no candidate weights."""
        signals = [
            CandidateSignals(thread_id=1, effort_minutes=8.0),
            CandidateSignals(thread_id=2, last_rating=5.0),
        ]
        weighting = weight_pool(BANDWIDTH_LIGHT, INTENT_RANDOM, signals)
        assert weighting.mode == "bypassed"
        assert weighting.contextual_bypass is True
        assert weighting.candidates == ()

    def test_random_selection_is_uniform_legacy_behavior(self) -> None:
        """Bypassed selection reproduces rng.randrange exactly."""
        weighting = weight_pool(BANDWIDTH_LIGHT, INTENT_RANDOM, [])
        legacy_rng = random.Random(20260822)
        bypass_rng = random.Random(20260822)
        for pool_size in range(1, 12):
            expected = legacy_rng.randrange(pool_size)
            actual = select_candidate_index(pool_size, weighting, bypass_rng)
            assert actual == expected
            assert 0 <= actual < pool_size

    def test_random_intent_has_no_per_candidate_factor(self) -> None:
        """Asking for random per-candidate factors is a hard error."""
        with pytest.raises(ValueError, match="bypass"):
            weight_candidate(BANDWIDTH_LIGHT, INTENT_RANDOM, CandidateSignals(thread_id=1))
        with pytest.raises(ValueError, match="no per-candidate intent factor"):
            intent_factor(INTENT_RANDOM, CandidateSignals(thread_id=1))

    def test_invalid_labels_are_rejected(self) -> None:
        """Unknown bandwidth or intent labels never silently pass through."""
        with pytest.raises(ValueError, match="Invalid bandwidth"):
            weight_pool("huge", INTENT_BALANCED, [])
        with pytest.raises(ValueError, match="Invalid intent"):
            weight_pool(BANDWIDTH_LIGHT, "chaos", [])


class TestEligibilityPreservation:
    """Taste/metadata pressure can never overpower die-pool eligibility."""

    def test_all_weights_strictly_positive_under_max_taste_pressure(self) -> None:
        """Every candidate keeps positive weight, so none leaves the pool."""
        saturated = CandidateSignals(
            thread_id=1,
            effort_minutes=100.0,
            matched_verdict_by_category=dict.fromkeys(
                ("creator", "character", "team", "publisher", "era"),
                VERDICT_CONFIRMED,
            ),
        )
        weighting = weight_pool(BANDWIDTH_LIGHT, INTENT_FAMILIAR, [saturated])
        assert len(weighting.candidates) == 1
        assert weighting.candidates[0].final_weight > 0.0
        assert weighting.candidates[0].intent_factor <= FAMILIAR_FACTOR_CAP

    def test_weighted_selection_can_reach_every_index(self) -> None:
        """Weighted roulette keeps every eligible candidate reachable."""
        signals = [CandidateSignals(thread_id=index, prior_exposure_count=0) for index in range(6)]
        weighting = weight_pool(BANDWIDTH_BALANCED, INTENT_EXPLORE, signals)
        rng = random.Random(1761)
        seen = {select_candidate_index(len(signals), weighting, rng) for _ in range(4000)}
        assert seen == set(range(6))

    def test_weighted_selection_respects_relative_weights(self) -> None:
        """Heavier candidates are chosen proportionally more often."""
        boosted = CandidateSignals(thread_id=0, prior_exposure_count=0)
        neutral = CandidateSignals(thread_id=1, prior_exposure_count=99)
        weighting = weight_pool(BANDWIDTH_BALANCED, INTENT_EXPLORE, [boosted, neutral])
        rng = random.Random(53)
        picks = [select_candidate_index(2, weighting, rng) for _ in range(6000)]
        boosted_share = picks.count(0) / len(picks)
        expected = weighting.candidates[0].final_weight / (
            weighting.candidates[0].final_weight + weighting.candidates[1].final_weight
        )
        assert math.isclose(boosted_share, expected, abs_tol=0.03)

    def test_select_rejects_inconsistent_inputs(self) -> None:
        """Selection validates pool size and bypass consistency."""
        weighting = weight_pool(
            BANDWIDTH_BALANCED, INTENT_BALANCED, [CandidateSignals(thread_id=1)]
        )
        with pytest.raises(ValueError, match="empty pool"):
            select_candidate_index(0, weighting, random.Random(1))
        with pytest.raises(ValueError, match="pool has"):
            select_candidate_index(3, weighting, random.Random(1))


class TestMissingMetadataSafety:
    """Missing metadata across intents fails safe and neutral."""

    def test_fully_unknown_candidate_weights_neutrally(self) -> None:
        """A candidate with zero evidence keeps neutral momentum/familiar."""
        for intent in (INTENT_MOMENTUM, INTENT_FAMILIAR):
            result = weight_candidate(BANDWIDTH_LIGHT, intent, CandidateSignals(thread_id=9))
            assert result.bandwidth_factor == 1.0
            assert result.intent_factor == 1.0
            assert result.final_weight == 1.0
            assert REASON_EFFORT_UNKNOWN_NEUTRAL in result.reasons

    def test_explicitly_unread_candidate_is_known_novel_for_explore(self) -> None:
        """Explore treats explicit zero exposure as novel; anchors stay neutral."""
        result = weight_candidate(BANDWIDTH_LIGHT, INTENT_EXPLORE, CandidateSignals(thread_id=9))
        assert result.intent_factor == pytest.approx(1.0 + EXPLORE_NOVEL_BONUS)
        assert REASON_NOVEL_CANDIDATE in result.reasons
        assert FINAL_WEIGHT_FLOOR <= result.final_weight <= FINAL_WEIGHT_CAP

    def test_partial_metadata_uses_only_present_evidence(self) -> None:
        """Present evidence scores while absent dimensions stay neutral."""
        signals = CandidateSignals(
            thread_id=1,
            effort_minutes=8.0,
            matched_verdict_by_category={"creator": VERDICT_SOMETIMES},
        )
        result = weight_candidate(BANDWIDTH_LIGHT, INTENT_FAMILIAR, signals)
        assert result.bandwidth_factor == 1.10
        assert result.intent_factor == pytest.approx(1.075)
        assert result.final_weight == pytest.approx(round(1.10 * 1.075, 6))

    def test_breakdown_preserves_reason_order_across_sides(self) -> None:
        """Breakdown lists bandwidth reasons before intent reasons."""
        signals = CandidateSignals(
            thread_id=1,
            effort_minutes=None,
            matched_verdict_by_category={"creator": VERDICT_CONFIRMED},
        )
        result = weight_candidate(BANDWIDTH_DEEP, INTENT_FAMILIAR, signals)
        assert result.reasons == (
            REASON_EFFORT_UNKNOWN_NEUTRAL,
            "taste_confirmed",
        )
