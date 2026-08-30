"""Phase 8 acceptance regression for intent-weighted recommendation (#1763).

This is the acceptance regression that closes Phase 8 of the personalized-Roll
architecture (#1685, tickets #1755, #1757, #1760, #1761, #1762). It proves the
complete intent-weighted recommendation contract end to end and mirrors the
Phase 1 acceptance regression in ``test_reading_effort_acceptance.py``.

The goal (per issue #1763): Momentum, Familiar, and Explore intents alter only
contextual ranking *inside* the existing die pool and remain explainable. Each
test below is anchored to one acceptance criterion:

1. Momentum favors recent high-rated runs and decays with staleness.
2. Familiar favors confirmed/qualified Taste Bank matches with capped effects.
3. Explore favors novel-but-adjacent candidates without excluding known
   favorites.
4. Bandwidth and intent combine within documented caps.
5. Balanced stays neutral and Random bypasses all contextual factors.
6. No candidate outside the bounded die pool can be selected.
7. Persisted recommendation context matches the final factors/weights used.

Criteria 1-6 exercise the pure ``comic_pile.recommendation_weighting`` module -
the canonical bounded bandwidth x intent combination - which is dependency-free
and deterministic. Criterion 7 exercises the live Roll endpoint against the test
database and verifies that the persisted ``recommendation_contexts`` snapshot
reproduces exactly the factors/weights the chooser used for the selected
candidate. Together they prove the full Phase 8 contract.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from comic_pile.recommendation_weighting import (
    ALL_BANDWIDTHS,
    ALL_INTENTS,
    BANDWIDTH_BALANCED,
    BANDWIDTH_DEEP,
    BANDWIDTH_DEVIATION_CAP,
    BANDWIDTH_LIGHT,
    EXPLORE_ADJACENCY_BONUS_PER_ANCHOR,
    EXPLORE_ADJACENCY_MAX_ANCHORS,
    EXPLORE_FACTOR_CAP,
    EXPLORE_KNOWN_EXPOSURE_COUNT,
    EXPLORE_LESS_EXPOSED_BONUS,
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
    MOMENTUM_BASE_BONUS,
    MOMENTUM_FACTOR_CAP,
    MOMENTUM_HIGH_RATING_THRESHOLD,
    MOMENTUM_MIN_POSITIVE_RATING,
    MOMENTUM_RECENCY_DECAY_HALF_LIFE_DAYS,
    MOMENTUM_STALENESS_DAYS,
    REASON_FINAL_WEIGHT_CLAMPED,
    REASON_INTENT_BALANCED_NEUTRAL,
    REASON_KNOWN_CANDIDATE_NEUTRAL,
    REASON_LESS_EXPOSED_CANDIDATE,
    REASON_LOW_RATING_NO_BOOST,
    REASON_NOVEL_CANDIDATE,
    REASON_STALE_RUN_DECAY,
    REASON_TASTE_ADJACENT,
    REASON_TASTE_REJECTED_IGNORED,
    TASTE_CATEGORY_CHARACTER,
    TASTE_CATEGORY_CREATOR,
    TASTE_CATEGORY_TEAM,
    VERDICT_CONFIRMED,
    VERDICT_REJECTED,
    VERDICT_SOMETIMES,
    CandidateSignals,
    combine_factors,
    select_candidate_index,
    weight_candidate,
    weight_pool,
)

# ---------------------------------------------------------------------------
# Shared signal builders and numeric helpers
# ---------------------------------------------------------------------------


def _momentum_signal(
    thread_id: int,
    *,
    days_since_last_read: float,
    last_rating: float,
    high_rated_streak: int = 0,
    effort_minutes: float | None = None,
) -> CandidateSignals:
    """Build a candidate signal with momentum-relevant fields populated."""
    return CandidateSignals(
        thread_id=thread_id,
        effort_minutes=effort_minutes,
        last_rating=last_rating,
        days_since_last_read=days_since_last_read,
        high_rated_streak=high_rated_streak,
    )


def _familiar_signal(
    thread_id: int,
    matched_verdict_by_category: dict[str, str],
    effort_minutes: float | None = None,
) -> CandidateSignals:
    """Build a candidate signal with Taste Bank matches populated."""
    return CandidateSignals(
        thread_id=thread_id,
        effort_minutes=effort_minutes,
        matched_verdict_by_category=matched_verdict_by_category,
    )


def _explore_signal(
    thread_id: int,
    *,
    prior_exposure_count: int,
    adjacent_anchor_categories: list[str] | tuple[str, ...] = (),
    effort_minutes: float | None = None,
) -> CandidateSignals:
    """Build a candidate signal with Explore exposure/adjacency populated."""
    return CandidateSignals(
        thread_id=thread_id,
        effort_minutes=effort_minutes,
        prior_exposure_count=prior_exposure_count,
        adjacent_anchor_categories=adjacent_anchor_categories,
    )


def _momentum_decay(days_since_last_read: float) -> float:
    """Exponential recency decay used by the momentum rule."""
    return 0.5 ** (days_since_last_read / MOMENTUM_RECENCY_DECAY_HALF_LIFE_DAYS)


def _momentum_strength(rating: float) -> float:
    """Normalized rating strength in ``[0, 1]`` for the momentum rule."""
    span = MOMENTUM_HIGH_RATING_THRESHOLD - MOMENTUM_MIN_POSITIVE_RATING
    return min(1.0, max(0.0, (rating - MOMENTUM_MIN_POSITIVE_RATING) / span))


def _expected_momentum_factor(
    days_since_last_read: float,
    last_rating: float,
    streak: int = 0,
) -> float:
    """Compute the expected momentum factor for the given signals."""
    from comic_pile.recommendation_weighting import MOMENTUM_STREAK_BONUS_PER_READ

    if days_since_last_read >= MOMENTUM_STALENESS_DAYS:
        return 1.0
    decay = _momentum_decay(days_since_last_read)
    if last_rating < MOMENTUM_MIN_POSITIVE_RATING:
        return 1.0
    bonus_base = MOMENTUM_BASE_BONUS * decay * _momentum_strength(last_rating)
    bonus_streak = min(streak, 4) * MOMENTUM_STREAK_BONUS_PER_READ * decay
    return min(MOMENTUM_FACTOR_CAP, 1.0 + bonus_base + bonus_streak)


# ---------------------------------------------------------------------------
# Criterion 1: Momentum favors recent high-rated runs and decays with staleness
# ---------------------------------------------------------------------------


class TestMomentumAcceptance:
    """Acceptance criterion 1: Momentum alters ranking within documented caps."""

    def test_recent_high_rated_run_is_weighted_above_neutral(self) -> None:
        """A fresh high-rated run must receive a positive, decaying boost."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(1, days_since_last_read=2.0, last_rating=5.0),
        )
        assert factor.final_weight > 1.0
        assert "recent_high_rating" in factor.reasons
        expected = _expected_momentum_factor(2.0, 5.0)
        assert factor.intent_factor == pytest.approx(expected, rel=1e-6)

    def test_high_rating_beats_low_rating_at_same_recency(self) -> None:
        """At equal recency the higher-rated run must rank above the lower one."""
        hot = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(1, days_since_last_read=1.0, last_rating=5.0),
        ).final_weight
        mild = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(2, days_since_last_read=1.0, last_rating=3.5),
        ).final_weight
        assert hot > mild

    def test_momentum_decays_with_staleness(self) -> None:
        """Older high-rated runs must receive a strictly smaller boost."""
        fresh = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(1, days_since_last_read=2.0, last_rating=5.0, high_rated_streak=4),
        ).intent_factor
        stale = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(2, days_since_last_read=20.0, last_rating=5.0, high_rated_streak=4),
        ).intent_factor
        assert fresh > stale
        assert stale > 1.0

    def test_fully_stale_run_returns_to_neutral_with_reason(self) -> None:
        """Runs past the staleness threshold must decay fully to neutral."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(
                1,
                days_since_last_read=MOMENTUM_STALENESS_DAYS + 1.0,
                last_rating=5.0,
            ),
        )
        assert factor.final_weight == pytest.approx(1.0)
        assert REASON_STALE_RUN_DECAY in factor.reasons

    def test_low_rated_recent_run_gets_no_positive_boost(self) -> None:
        """A recent but low-rated run must not gain positive momentum for recency."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(1, days_since_last_read=1.0, last_rating=2.0),
        )
        assert factor.final_weight == pytest.approx(1.0)
        assert REASON_LOW_RATING_NO_BOOST in factor.reasons

    def test_momentum_factor_never_exceeds_cap(self) -> None:
        """Maximum recency, rating, and streak must stay within the cap."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            _momentum_signal(1, days_since_last_read=0.0, last_rating=5.0, high_rated_streak=100),
        ).intent_factor
        assert factor <= MOMENTUM_FACTOR_CAP
        assert factor > 1.0


# ---------------------------------------------------------------------------
# Criterion 2: Familiar favors confirmed/qualified Taste Bank matches, capped
# ---------------------------------------------------------------------------


class TestFamiliarAcceptance:
    """Acceptance criterion 2: Familiar favors taste matches with capped effects."""

    def test_confirmed_match_ranks_above_neutral(self) -> None:
        """A confirmed Taste Bank match must produce a positive factor."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, {TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED}),
        )
        assert factor.final_weight > 1.0
        assert factor.intent_factor == pytest.approx(1.0 + 0.15, rel=1e-6)
        assert "taste_confirmed" in factor.reasons

    def test_confirmed_ranks_above_sometimes(self) -> None:
        """A confirmed verdict must outrank a qualified (sometimes) verdict."""
        confirmed = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, {TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED}),
        ).intent_factor
        sometimes = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, {TASTE_CATEGORY_CHARACTER: VERDICT_SOMETIMES}),
        ).intent_factor
        assert confirmed > sometimes > 1.0

    def test_rejected_signals_never_boost(self) -> None:
        """A rejected taste match must not contribute any positive factor."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, {TASTE_CATEGORY_CREATOR: VERDICT_REJECTED}),
        )
        assert factor.final_weight == pytest.approx(1.0)
        assert REASON_TASTE_REJECTED_IGNORED in factor.reasons

    def test_correlated_matches_are_capped(self) -> None:
        """Many correlated matches must aggregate under the single taste cap."""
        many_matches = {
            TASTE_CATEGORY_CREATOR: VERDICT_CONFIRMED,
            TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED,
            TASTE_CATEGORY_TEAM: VERDICT_CONFIRMED,
        }
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, many_matches),
        ).intent_factor
        assert factor <= FAMILIAR_FACTOR_CAP
        assert factor == pytest.approx(1.0 + FAMILIAR_AGGREGATE_BONUS_CAP, rel=1e-6)
        assert "taste_aggregate_capped" in weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, many_matches),
        ).reasons

    def test_missing_metadata_fails_neutral(self) -> None:
        """No taste metadata must yield an exactly neutral familiar factor."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_FAMILIAR,
            _familiar_signal(1, {}),
        )
        assert factor.final_weight == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Criterion 3: Explore favors novel-but-adjacent candidates, never excludes
# ---------------------------------------------------------------------------


class TestExploreAcceptance:
    """Acceptance criterion 3: Explore favors novel candidates within bounds."""

    def test_novel_candidate_ranks_above_known(self) -> None:
        """An unread candidate must outrank a heavily-exposed one under Explore."""
        novel = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(1, prior_exposure_count=0),
        ).intent_factor
        known = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(2, prior_exposure_count=EXPLORE_KNOWN_EXPOSURE_COUNT),
        ).intent_factor
        assert novel > known
        assert novel == pytest.approx(1.0 + EXPLORE_NOVEL_BONUS, rel=1e-6)

    def test_lightly_exposed_candidate_gets_partial_bonus(self) -> None:
        """A lightly-exposed candidate must receive a smaller, marked bonus."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(2, prior_exposure_count=1),
        )
        assert factor.intent_factor == pytest.approx(1.0 + EXPLORE_LESS_EXPOSED_BONUS, rel=1e-6)
        assert REASON_LESS_EXPOSED_CANDIDATE in factor.reasons

    def test_novel_candidate_records_novel_reason(self) -> None:
        """A fully novel candidate must carry the explicit novelty reason."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(5, prior_exposure_count=0),
        )
        assert REASON_NOVEL_CANDIDATE in factor.reasons

    def test_known_candidate_stays_eligible_and_neutral(self) -> None:
        """A familiar favorite must not be excluded - it stays fully eligible."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(3, prior_exposure_count=EXPLORE_KNOWN_EXPOSURE_COUNT),
        )
        assert factor.final_weight == pytest.approx(1.0)
        assert REASON_KNOWN_CANDIDATE_NEUTRAL in factor.reasons

    def test_adjacent_anchor_boosts_novel_candidate(self) -> None:
        """A novel candidate sharing a confirmed anchor earns a taste bonus."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(
                1,
                prior_exposure_count=0,
                adjacent_anchor_categories=[TASTE_CATEGORY_CHARACTER],
            ),
        )
        assert factor.intent_factor == pytest.approx(
            1.0 + EXPLORE_NOVEL_BONUS + EXPLORE_ADJACENCY_BONUS_PER_ANCHOR,
            rel=1e-6,
        )
        assert REASON_TASTE_ADJACENT in factor.reasons

    def test_adjacency_anchor_boost_is_capped(self) -> None:
        """Adjacency bonuses must cap at the per-anchor maximum."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(
                1,
                prior_exposure_count=0,
                adjacent_anchor_categories=[
                    TASTE_CATEGORY_CREATOR,
                    TASTE_CATEGORY_CHARACTER,
                    TASTE_CATEGORY_TEAM,
                ],
            ),
        ).intent_factor
        assert factor <= EXPLORE_FACTOR_CAP
        expected_adjacency = EXPLORE_ADJACENCY_MAX_ANCHORS * EXPLORE_ADJACENCY_BONUS_PER_ANCHOR
        assert factor == pytest.approx(
            1.0 + EXPLORE_NOVEL_BONUS + expected_adjacency,
            rel=1e-6,
        )

    def test_known_candidate_with_anchor_stays_neutral(self) -> None:
        """Adjacency must not revive an already-known candidate under Explore."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_EXPLORE,
            _explore_signal(
                4,
                prior_exposure_count=EXPLORE_KNOWN_EXPOSURE_COUNT,
                adjacent_anchor_categories=[TASTE_CATEGORY_CHARACTER],
            ),
        )
        assert factor.final_weight == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Criterion 4: Bandwidth and intent combine within documented caps
# ---------------------------------------------------------------------------


class TestBandwidthIntentCombinationAcceptance:
    """Acceptance criterion 4: bandwidth x intent combine inside bounded caps."""

    def test_light_bandwidth_and_momentum_combine_multiplicatively(self) -> None:
        """Light bandwidth aligned with a low-effort momentum candidate stacks."""
        factor = weight_candidate(
            BANDWIDTH_LIGHT,
            INTENT_MOMENTUM,
            _momentum_signal(
                1,
                days_since_last_read=1.0,
                last_rating=5.0,
                effort_minutes=5.0,
            ),
        )
        assert factor.final_weight > factor.intent_factor
        assert factor.bandwidth_factor > 1.0
        assert factor.final_weight <= FINAL_WEIGHT_CAP
        assert factor.final_weight >= FINAL_WEIGHT_FLOOR

    def test_deep_bandwidth_dampens_light_effort_momentum(self) -> None:
        """Deep bandwidth must dampen a low-effort momentum run downward."""
        factor = weight_candidate(
            BANDWIDTH_DEEP,
            INTENT_MOMENTUM,
            _momentum_signal(
                1,
                days_since_last_read=1.0,
                last_rating=5.0,
                effort_minutes=5.0,
            ),
        )
        assert factor.bandwidth_factor < 1.0
        assert factor.final_weight >= FINAL_WEIGHT_FLOOR

    def test_every_bandwidth_intent_pair_stays_in_final_caps(self) -> None:
        """Every supported bandwidth x intent pair must respect central caps."""
        for bandwidth in ALL_BANDWIDTHS:
            for intent in ALL_INTENTS:
                if intent == INTENT_RANDOM:
                    continue
                factor = weight_candidate(
                    bandwidth,
                    intent,
                    CandidateSignals(
                        thread_id=1,
                        effort_minutes=5.0,
                        last_rating=5.0,
                        days_since_last_read=1.0,
                        high_rated_streak=4,
                        matched_verdict_by_category={
                            TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED,
                            TASTE_CATEGORY_CREATOR: VERDICT_CONFIRMED,
                        },
                        prior_exposure_count=0,
                        adjacent_anchor_categories=[TASTE_CATEGORY_CHARACTER],
                    ),
                )
                assert FINAL_WEIGHT_FLOOR <= factor.final_weight <= FINAL_WEIGHT_CAP
                assert 0.0 < factor.bandwidth_factor
                assert 0.0 < factor.intent_factor

    def test_bandwidth_deviation_is_capped(self) -> None:
        """Bandwidth deviations must never exceed the documented cap."""
        for bandwidth in (BANDWIDTH_LIGHT, BANDWIDTH_DEEP):
            heavy_effort = weight_candidate(
                bandwidth,
                INTENT_BALANCED,
                CandidateSignals(thread_id=1, effort_minutes=60.0),
            ).bandwidth_factor
            light_effort = weight_candidate(
                bandwidth,
                INTENT_BALANCED,
                CandidateSignals(thread_id=2, effort_minutes=5.0),
            ).bandwidth_factor
            for value in (heavy_effort, light_effort):
                assert abs(value - 1.0) <= BANDWIDTH_DEVIATION_CAP + 1e-9

    def test_out_of_range_combination_clamps_with_reason(self) -> None:
        """A rough product that exceeds the cap must clamp and report it."""
        combined = combine_factors(
            thread_id=1,
            bandwidth_part=FINAL_WEIGHT_CAP,
            intent_part=FINAL_WEIGHT_CAP,
            reasons=(),
        )
        assert combined.final_weight == pytest.approx(FINAL_WEIGHT_CAP)
        assert REASON_FINAL_WEIGHT_CLAMPED in combined.reasons


# ---------------------------------------------------------------------------
# Criterion 5: Balanced stays neutral and Random bypasses all context
# ---------------------------------------------------------------------------


class TestNeutralAndBypassAcceptance:
    """Acceptance criterion 5: neutral and explicit bypass behaviors."""

    def test_balanced_bandwidth_and_intent_are_neutral(self) -> None:
        """Balanced bandwidth with balanced intent must be exactly neutral."""
        factor = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_BALANCED,
            _momentum_signal(1, days_since_last_read=1.0, last_rating=5.0, effort_minutes=5.0),
        )
        assert factor.final_weight == pytest.approx(1.0)
        assert REASON_INTENT_BALANCED_NEUTRAL in factor.reasons

    def test_balanced_intent_stays_neutral_regardless_of_signals(self) -> None:
        """No reader signal may bias a balanced draw."""
        hot = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_BALANCED,
            _momentum_signal(1, days_since_last_read=1.0, last_rating=5.0, effort_minutes=5.0),
        ).final_weight
        cold = weight_candidate(
            BANDWIDTH_BALANCED,
            INTENT_BALANCED,
            _momentum_signal(2, days_since_last_read=99.0, last_rating=1.0, effort_minutes=60.0),
        ).final_weight
        assert hot == pytest.approx(1.0)
        assert cold == pytest.approx(1.0)

    def test_random_intent_bypasses_all_context(self) -> None:
        """The random intent must produce a bypass with no per-candidate weights."""
        weighting = weight_pool(
            BANDWIDTH_DEEP,
            INTENT_RANDOM,
            [
                _momentum_signal(1, days_since_last_read=1.0, last_rating=5.0),
                _momentum_signal(2, days_since_last_read=99.0, last_rating=1.0),
            ],
        )
        assert weighting.contextual_bypass is True
        assert weighting.mode == "bypassed"
        assert weighting.candidates == ()

    def test_random_bypass_selection_is_uniform(self) -> None:
        """Bypassed selection must reproduce legacy uniform selection exactly."""
        rng = random.Random(42)
        weighting = weight_pool(
            BANDWIDTH_LIGHT,
            INTENT_RANDOM,
            [_momentum_signal(i, days_since_last_read=1.0, last_rating=5.0) for i in range(1, 6)],
        )
        legacy = rng.randrange(5)
        weighted_index = select_candidate_index(5, weighting, rng)
        assert weighted_index == legacy


# ---------------------------------------------------------------------------
# Criterion 6: No candidate outside the bounded die pool can be selected
# ---------------------------------------------------------------------------


class TestBoundedPoolAcceptance:
    """Acceptance criterion 6: selection stays strictly inside the die pool."""

    def test_select_never_return_index_outside_pool(self) -> None:
        """Thousands of weighted draws must stay within ``[0, pool_size)``."""
        rng = random.Random(2024)
        signals = [
            CandidateSignals(
                thread_id=i,
                effort_minutes=5.0,
                last_rating=5.0,
                days_since_last_read=1.0,
                high_rated_streak=4,
                matched_verdict_by_category={TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED},
                prior_exposure_count=0,
                adjacent_anchor_categories=[TASTE_CATEGORY_CHARACTER],
            )
            for i in range(1, 9)
        ]
        weighting = weight_pool(BANDWIDTH_LIGHT, INTENT_MOMENTUM, signals)
        for _ in range(2000):
            index = select_candidate_index(len(signals), weighting, rng)
            assert 0 <= index < len(weighting.candidates)

    def test_pool_mismatch_is_rejected(self) -> None:
        """A weighting covering a different pool size must be rejected."""
        weighting = weight_pool(
            BANDWIDTH_BALANCED,
            INTENT_MOMENTUM,
            [_momentum_signal(1, days_since_last_read=1.0, last_rating=5.0)],
        )
        with pytest.raises(ValueError):
            select_candidate_index(3, weighting, random.Random(0))

    def test_empty_pool_is_rejected(self) -> None:
        """Selecting from an empty pool must raise rather than guess."""
        with pytest.raises(ValueError):
            select_candidate_index(0, None, random.Random(0))  # type: ignore[arg-type]

    def test_weighted_pool_covers_exactly_supplied_candidates(self) -> None:
        """Weighting must return exactly one entry per supplied candidate."""
        signals = [
            _momentum_signal(i, days_since_last_read=1.0, last_rating=5.0) for i in range(1, 5)
        ]
        weighting = weight_pool(BANDWIDTH_BALANCED, INTENT_EXPLORE, signals)
        assert {c.thread_id for c in weighting.candidates} == {1, 2, 3, 4}
        assert len(weighting.candidates) == 4


# ---------------------------------------------------------------------------
# Criterion 7: Persisted recommendation context matches final factors/weights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persisted_context_matches_chooser_factors_and_weights(
    auth_client, async_db, default_user
) -> None:
    """A momentum-weighted Roll must persist the exact factors/weights used."""
    from app.models import Event, RecommendationContext, Thread

    assert default_user.id is not None
    now = datetime.now(UTC)
    hot = Thread(
        title="Acceptance Hot",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        last_rating=5.0,
        last_activity_at=now - timedelta(hours=2),
        created_at=now,
    )
    cold = Thread(
        title="Acceptance Cold",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add_all([hot, cold])
    await async_db.commit()
    await async_db.refresh(hot)
    await async_db.refresh(cold)
    assert hot.id is not None and cold.id is not None

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()
    selected_thread_id = roll_data["thread_id"]
    assert selected_thread_id in (hot.id, cold.id)

    result = await async_db.execute(
        select(RecommendationContext)
        .join(Event, Event.id == RecommendationContext.event_id)
        .where(Event.type == "roll")
        .order_by(RecommendationContext.id.desc())
    )
    context = result.scalars().first()
    assert context is not None

    factors_by_candidate = {
        factor["candidate_id"]: factor for factor in (context.candidate_factors or [])
    }
    assert set(factors_by_candidate) == {hot.id, cold.id}

    hot_entry = factors_by_candidate[hot.id]
    assert "recent_high_rating" in hot_entry["factors"]
    assert hot_entry["weight"] > 1.0
    cold_entry = factors_by_candidate[cold.id]
    assert cold_entry["factors"] == []
    assert cold_entry["weight"] == pytest.approx(1.0)

    selected_entry = factors_by_candidate[selected_thread_id]
    assert context.final_weight == selected_entry["weight"]
    assert context.intent == "balanced"
    assert context.bandwidth == "balanced"
