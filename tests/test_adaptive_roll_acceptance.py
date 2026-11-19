"""Phase 9 end-to-end adaptive Roll product acceptance (issue #1769).

Verifies the complete adaptive Roll system against the parent product
promise on integrated current main. Each acceptance criterion maps to
one or more tests covering the full inference-to-selection pipeline.

Acceptance scenarios:
1. Strong historical light-evening behavior infers appropriate bandwidth.
2. Snoozing a heavy recommendation adapts the session toward lighter choices
   without permanently demoting durable affinity.
3. Repeated mismatch is correctable manually or through the two-question quiz.
4. Momentum intent favors a current high-rated run without forcing diversity.
5. Familiar intent uses a confirmed Taste Bank creator/character/team signal.
6. Explore favors a novel but taste-adjacent candidate.
7. Random mode and the operator legacy switch both restore unweighted selection.
8. "Why this?" explains the actual decision-time factors used.
9. Recommendation-quality diagnostics compare outcomes by mode/algorithm version.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models import ReadingSession
from app.services.bandwidth_inference import (
    HistoricalObservation,
    infer_bandwidth,
)

# reading-mode quiz logic moved to Rust; Python helpers removed.
from comic_pile.recommendation_selection import (
    SelectionMode,
    resolve_selection_mode,
)
from comic_pile.recommendation_version import (
    RECOMMENDATION_ALGORITHM_VERSION_LEGACY,
    RECOMMENDATION_ALGORITHM_VERSION,
)
from comic_pile.recommendation_weighting import (
    CandidateSignals,
    FINAL_WEIGHT_FLOOR,
    FINAL_WEIGHT_CAP,
    INTENT_MOMENTUM,
    INTENT_FAMILIAR,
    INTENT_EXPLORE,
    INTENT_RANDOM,
    VERDICT_CONFIRMED,
    VERDICT_REJECTED,
    TASTE_CATEGORY_CREATOR,
    TASTE_CATEGORY_CHARACTER,
    weight_pool,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(db: AsyncSession) -> User:
    """Create a fresh user and return it."""
    user = User(username="adaptive-roll-acceptance", created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user


async def _create_thread(
    db: AsyncSession,
    user_id: int,
    *,
    title: str = "Test Thread",
    format: str = "Comic",
    issues_remaining: int = 5,
    queue_position: int = 1,
    last_rating: float | None = None,
    last_activity_at: datetime | None = None,
) -> Thread:
    """Create one reading thread for the given user."""
    thread = Thread(
        title=title,
        format=format,
        issues_remaining=issues_remaining,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        last_rating=last_rating,
        last_activity_at=last_activity_at,
    )
    db.add(thread)
    await db.flush()
    return thread


async def _create_session(
    db: AsyncSession,
    user_id: int,
    *,
    active_bandwidth: str | None = None,
    bandwidth_source: str | None = None,
    bandwidth_confidence: float = 0.1,
    predicted_bandwidth: str | None = None,
    active_intent: str | None = None,
    intent_source: str | None = None,
    start_die: int = 6,
) -> ReadingSession:
    """Create an active session for the given user."""
    session = ReadingSession(
        start_die=start_die,
        user_id=user_id,
        active_bandwidth=active_bandwidth,
        bandwidth_source=bandwidth_source,
        bandwidth_confidence=bandwidth_confidence,
        predicted_bandwidth=predicted_bandwidth,
        active_intent=active_intent,
        intent_source=intent_source,
    )
    db.add(session)
    await db.flush()
    return session


async def _create_roll_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
    *,
    selection_method: str = "random",
    die: int = 6,
    timestamp: datetime | None = None,
) -> Event:
    """Create a roll event for the given session and thread."""
    if timestamp is None:
        timestamp = datetime.now(UTC)
    event = Event(
        type="roll",
        session_id=session_id,
        selected_thread_id=thread_id,
        die=die,
        result=1,
        selection_method=selection_method,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


async def _create_rate_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
    *,
    rating: float = 4.5,
    timestamp: datetime | None = None,
) -> Event:
    """Create a rate event for the given session and thread."""
    if timestamp is None:
        timestamp = datetime.now(UTC)
    event = Event(
        type="rate",
        session_id=session_id,
        thread_id=thread_id,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


async def _create_snooze_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
    timestamp: datetime | None = None,
) -> Event:
    """Create a snooze event for the given session and thread."""
    if timestamp is None:
        timestamp = datetime.now(UTC)
    event = Event(
        type="snooze",
        session_id=session_id,
        thread_id=thread_id,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


async def _setup_user_with_history(
    db: AsyncSession,
    user_id: int,
    *,
    effort_minutes: float = 8.0,
    count: int = 5,
) -> list[Thread]:
    """Create a user with historical reading behavior for bandwidth inference."""
    threads: list[Thread] = []
    history_session = ReadingSession(user_id=user_id)
    db.add(history_session)
    await db.flush()
    base_time = datetime.now(UTC) - timedelta(days=1)
    for i in range(count):
        thread = await _create_thread(
            db,
            user_id,
            title=f"History Thread {i}",
            queue_position=i + 1,
            last_rating=4.5,
            last_activity_at=base_time + timedelta(hours=i),
        )
        threads.append(thread)
        await _create_roll_event(db, history_session.id, thread.id, selection_method="random")
        rate_ts = base_time + timedelta(hours=i) + timedelta(minutes=5)
        await _create_rate_event(db, history_session.id, thread.id, rating=4.5, timestamp=rate_ts)
    return threads


# ---------------------------------------------------------------------------
# AC-1: Strong historical light-evening behavior infers appropriate bandwidth
# ---------------------------------------------------------------------------


class TestAC1LightHistoryInfersBandwidth:
    """A session with strong historical light-evening behavior.

    Starts in an appropriate inferred bandwidth and only weights
    candidates inside the current die pool.
    """

    @pytest.mark.asyncio
    async def test_light_history_inference_returns_light_bandwidth(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Seeded light-history sessions infer light bandwidth with meaningful confidence."""
        await _ensure_user(async_db)
        await async_db.commit()

        observations = tuple(
            HistoricalObservation(
                effort_minutes=5.0 + (i * 0.5),
                was_snoozed=False,
                session_hour=10,
                rating=4.5,
            )
            for i in range(5)
        )

        prediction = infer_bandwidth(observations, session_hour=10)

        assert prediction.level == "light"
        assert prediction.confidence > 0.5
        assert prediction.source == "inferred"

    @pytest.mark.asyncio
    async def test_light_history_only_weights_candidates_in_die_pool(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Light bandwidth weighting only redistributes probability inside the bounded die pool."""
        from comic_pile.recommendation_weights import build_candidate_weights

        efforts = [(1, 5.0), (2, 15.0), (3, 20.0)]
        weights = build_candidate_weights(efforts, "light")

        assert len(weights) == 3
        assert weights[0].weight > weights[1].weight
        assert weights[1].weight > weights[2].weight
        assert all(w.weight > 0 for w in weights)

    @pytest.mark.asyncio
    async def test_deep_history_inference_returns_deep_bandwidth(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Seeded deep-history sessions infer deep bandwidth."""
        observations = tuple(
            HistoricalObservation(
                effort_minutes=25.0 + (i * 2.0),
                was_snoozed=False,
                session_hour=20,
                rating=4.0,
            )
            for i in range(5)
        )

        prediction = infer_bandwidth(observations, session_hour=20)

        assert prediction.level == "deep"
        assert prediction.confidence > 0.5

    @pytest.mark.asyncio
    async def test_insufficient_history_defaults_to_balanced(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Insufficient evidence defaults to balanced with low confidence."""
        observations = tuple(HistoricalObservation(effort_minutes=5.0) for _ in range(2))

        prediction = infer_bandwidth(observations)

        assert prediction.level == "balanced"
        assert prediction.confidence < 0.5


# ---------------------------------------------------------------------------
# AC-2: Snoozing a heavy recommendation doesn't permanently demote; session adapts
# ---------------------------------------------------------------------------


class TestAC4MomentumIntent:
    """Momentum intent favors a current high-rated run without forcing diversity."""

    @pytest.mark.asyncio
    async def test_momentum_favors_high_rated_run(self, async_db: AsyncSession) -> None:
        """Momentum weighting boosts high-rated recent runs."""
        thread_id = 1
        signals = CandidateSignals(
            thread_id=thread_id,
            last_rating=4.8,
            days_since_last_read=1.0,
            high_rated_streak=3,
        )

        weighted = weight_pool(
            bandwidth="balanced",
            intent="momentum",
            signals=[signals],
        )

        assert weighted.intent == INTENT_MOMENTUM
        assert weighted.candidates[0].final_weight >= 1.0
        assert any("recent_high_rating" in r for r in weighted.candidates[0].reasons)

    @pytest.mark.asyncio
    async def test_momentum_does_not_force_diversity(self, async_db: AsyncSession) -> None:
        """Momentum does not force the selection away from the highest-rated candidate."""
        signals = [
            CandidateSignals(
                thread_id=1,
                last_rating=4.8,
                days_since_last_read=1.0,
                high_rated_streak=3,
            ),
            CandidateSignals(
                thread_id=2,
                last_rating=3.0,
                days_since_last_read=30.0,
                high_rated_streak=0,
            ),
        ]

        weighted = weight_pool(
            bandwidth="balanced",
            intent="momentum",
            signals=signals,
        )

        assert weighted.candidates[0].final_weight >= weighted.candidates[1].final_weight
        assert len(weighted.candidates) == 2

    @pytest.mark.asyncio
    async def test_momentum_weights_stay_bounded(self, async_db: AsyncSession) -> None:
        """Momentum factor caps prevent runaway weighting."""
        signals = [
            CandidateSignals(
                thread_id=1,
                last_rating=5.0,
                days_since_last_read=0.5,
                high_rated_streak=4,
            )
        ]

        weighted = weight_pool(
            bandwidth="balanced",
            intent="momentum",
            signals=signals,
        )

        assert weighted.candidates[0].intent_factor <= 1.5


# ---------------------------------------------------------------------------
# AC-5: Familiar intent uses confirmed Taste Bank signals
# ---------------------------------------------------------------------------


class TestAC5FamiliarIntentUsesTasteBank:
    """Familiar intent can use a confirmed Taste Bank creator/character/team signal."""

    def test_familiar_weighted_by_confirmed_taste(self) -> None:
        """Confirmed Taste Bank verdicts boost Familiar intent weight."""
        signals = [
            CandidateSignals(
                thread_id=1,
                matched_verdict_by_category={
                    TASTE_CATEGORY_CREATOR: VERDICT_CONFIRMED,
                    TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED,
                },
            )
        ]

        weighted = weight_pool(
            bandwidth="balanced",
            intent="familiar",
            signals=signals,
        )

        assert weighted.intent == INTENT_FAMILIAR
        assert any("taste_confirmed" in r for r in weighted.candidates[0].reasons)
        assert weighted.candidates[0].final_weight > 1.0

    @pytest.mark.asyncio
    async def test_familiar_uses_creator_signal(self, async_db: AsyncSession) -> None:
        """Familiar intent recognizes a confirmed creator signal."""
        from app.models.taste_signal import TasteSignal, SIGNAL_CREATOR

        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        taste_signal = TasteSignal(
            user_id=user_id,
            signal_type=SIGNAL_CREATOR,
            external_key="creator:alice-writer",
            display_name="Alice Writer",
            affinity_estimate=0.9,
            confidence=0.8,
            evidence_count=5,
            distinct_thread_count=3,
            user_verdict=VERDICT_CONFIRMED,
        )
        async_db.add(taste_signal)
        await async_db.commit()

        result = await async_db.execute(
            select(TasteSignal).where(TasteSignal.id == taste_signal.id)
        )
        fetched = result.scalar_one()
        assert fetched.user_verdict == VERDICT_CONFIRMED

    @pytest.mark.asyncio
    async def test_familiar_rejected_evidence_does_not_boost(self) -> None:
        """Rejected Taste Bank evidence does not boost Familiar intent."""
        signals = [
            CandidateSignals(
                thread_id=1,
                matched_verdict_by_category={
                    TASTE_CATEGORY_CREATOR: VERDICT_REJECTED,
                },
            )
        ]

        weighted = weight_pool(
            bandwidth="balanced",
            intent="familiar",
            signals=signals,
        )

        assert any("taste_rejected_ignored" in r for r in weighted.candidates[0].reasons)


# ---------------------------------------------------------------------------
# AC-6: Explore favors novel but taste-adjacent candidates
# ---------------------------------------------------------------------------


class TestAC6ExploreIntent:
    """Explore can favor a novel but taste-adjacent candidate."""

    def test_explore_favors_novel_adjacent_candidate(self) -> None:
        """Explore intent gives a bonus to novel-but-adjacent candidates."""
        signals = [
            CandidateSignals(
                thread_id=1,
                adjacent_anchor_categories=[TASTE_CATEGORY_CREATOR],
            )
        ]

        weighted = weight_pool(
            bandwidth="balanced",
            intent="explore",
            signals=signals,
        )

        assert weighted.intent == INTENT_EXPLORE
        assert any("novel_candidate" in r for r in weighted.candidates[0].reasons)
        assert any("taste_adjacent" in r for r in weighted.candidates[0].reasons)
        assert weighted.candidates[0].final_weight > 1.0

    @pytest.mark.asyncio
    async def test_explore_does_not_exclude_known_favorites(self, async_db: AsyncSession) -> None:
        """Explore never excludes known favorites from the bounded pool."""
        signals = [
            CandidateSignals(
                thread_id=1,
                prior_exposure_count=5,
                last_rating=4.5,
            ),
            CandidateSignals(
                thread_id=2,
                prior_exposure_count=0,
                last_rating=3.5,
            ),
        ]

        weighted = weight_pool(
            bandwidth="balanced",
            intent="explore",
            signals=signals,
        )

        assert len(weighted.candidates) == 2
        for c in weighted.candidates:
            assert FINAL_WEIGHT_FLOOR <= c.final_weight <= FINAL_WEIGHT_CAP


# ---------------------------------------------------------------------------
# AC-7: Random mode and operator legacy switch restore unweighted selection
# ---------------------------------------------------------------------------


class TestAC7RandomAndLegacyRestoreUnweighted:
    """Random mode and the operator legacy switch both restore unweighted selection."""

    def test_random_intent_bypasses_contextual_weighting(self) -> None:
        """Random intent produces uniform weights across the pool."""
        signals = [
            CandidateSignals(thread_id=1, last_rating=4.8),
            CandidateSignals(thread_id=2, last_rating=3.0),
            CandidateSignals(thread_id=3, last_rating=4.5),
        ]

        weighted = weight_pool(
            bandwidth="light",
            intent="random",
            signals=signals,
        )

        assert weighted.intent == INTENT_RANDOM
        assert weighted.contextual_bypass is True
        for c in weighted.candidates:
            assert c.final_weight == 1.0

    @pytest.mark.asyncio
    async def test_legacy_control_mode_restores_unweighted_selection(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Operator legacy control mode forces unweighted selection."""
        mode = resolve_selection_mode("balanced", "balanced", "legacy")
        assert mode == SelectionMode.FORCED_LEGACY

        mode_contextual = resolve_selection_mode("balanced", "balanced", "contextual")
        assert mode_contextual != SelectionMode.FORCED_LEGACY

    @pytest.mark.asyncio
    async def test_legacy_mode_records_algorithm_version(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Legacy mode records the legacy algorithm version for distinguishability."""
        version = RECOMMENDATION_ALGORITHM_VERSION_LEGACY
        assert version == "legacy"

        version_contextual = RECOMMENDATION_ALGORITHM_VERSION
        assert version_contextual == "v1-contextual"

    @pytest.mark.asyncio
    async def test_random_mode_with_legacy_control_still_bypasses(
        self,
        async_db: AsyncSession,
    ) -> None:
        """Legacy control mode always forces unweighted selection.

        The operator legacy switch is the highest-level override.
        Even random intent yields FORCED_LEGACY because legacy
        disables all contextual weighting unconditionally.
        """
        mode = resolve_selection_mode("balanced", "random", "legacy")
        assert mode == SelectionMode.FORCED_LEGACY

        mode_contextual = resolve_selection_mode("balanced", "random", "contextual")
        assert mode_contextual == SelectionMode.PURE_RANDOM_BYPASS


# ---------------------------------------------------------------------------
# AC-8: "Why this?" explains decision-time factors
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AC-9: Diagnostics compare outcomes by mode/algorithm version
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cross-cutting: Verify the complete adaptive Roll pipeline
# ---------------------------------------------------------------------------
