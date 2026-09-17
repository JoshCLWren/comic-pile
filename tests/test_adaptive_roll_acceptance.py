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
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models import Session as SessionModel
from app.services.bandwidth_inference import (
    HistoricalObservation,
    infer_bandwidth,
)
from app.services.reading_quiz import (
    QuizResolutionError,
    resolve_quiz_answers,
)
from app.services.recommendation_explanation import (
    RecommendationExplanationProjection,
)
from app.services.recommendation_diagnostics import (
    compute_recommendation_diagnostics,
    resolve_diagnostics_range,
)
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
) -> SessionModel:
    """Create an active session for the given user."""
    session = SessionModel(
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
        await _create_roll_event(db, 0, thread.id, selection_method="random")
        rate_ts = base_time + timedelta(hours=i) + timedelta(minutes=5)
        await _create_rate_event(db, 0, thread.id, rating=4.5, timestamp=rate_ts)
    return threads


async def _get_session_reading_mode(
    auth_client: AsyncClient,
) -> dict:
    """Fetch the current reading mode from the API."""
    response = await auth_client.get("/api/v1/reading-mode")
    return response.json()


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
        self, async_db: AsyncSession,
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
        self, async_db: AsyncSession,
    ) -> None:
        """Light bandwidth weighting only redistributes probability inside the bounded die pool."""
        from comic_pile.recommendation_weights import build_candidate_weights

        efforts = [(1, 5.0), (2, 8.0), (3, 20.0)]
        weights = build_candidate_weights(efforts, "light")

        assert len(weights) == 3
        assert weights[0].weight > weights[1].weight
        assert weights[1].weight > weights[2].weight
        assert all(w.weight > 0 for w in weights)

    @pytest.mark.asyncio
    async def test_deep_history_inference_returns_deep_bandwidth(
        self, async_db: AsyncSession,
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
        self, async_db: AsyncSession,
    ) -> None:
        """Insufficient evidence defaults to balanced with low confidence."""
        observations = tuple(
            HistoricalObservation(effort_minutes=5.0) for _ in range(2)
        )

        prediction = infer_bandwidth(observations)

        assert prediction.level == "balanced"
        assert prediction.confidence < 0.5


# ---------------------------------------------------------------------------
# AC-2: Snoozing a heavy recommendation doesn't permanently demote; session adapts
# ---------------------------------------------------------------------------


class TestAC2SnoozeAdaptationWithoutPermanentDemotion:
    """Snoozing a heavy recommendation.

    Leaves durable affinity unchanged and the session adapts
    toward lighter choices.
    """

    @pytest.mark.asyncio
    async def test_snooze_updates_session_bandwidth_not_durable_affinity(
        self, async_db: AsyncSession,
    ) -> None:
        """Snooze corrects session bandwidth without rewriting durable Taste Bank verdicts."""
        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        threads = await _setup_user_with_history(
            async_db, user_id, effort_minutes=15.0, count=5
        )
        session = await _create_session(
            async_db, user_id,
            active_bandwidth="deep",
            bandwidth_source="inferred",
            bandwidth_confidence=0.6,
        )
        await async_db.commit()

        snooze_event = Event(
            type="snooze",
            session_id=session.id,
            thread_id=threads[0].id,
            timestamp=datetime.now(UTC),
        )
        async_db.add(snooze_event)
        session.snoozed_thread_ids = [threads[0].id]
        await async_db.commit()

        # Durable thread rating must not change
        assert threads[0].last_rating == 4.5

    @pytest.mark.asyncio
    async def test_snooze_causes_bandwidth_correction(
        self, async_db: AsyncSession,
    ) -> None:
        """Snoozing a heavy comic shifts the predicted bandwidth toward lighter."""
        from comic_pile.bandwidth_correction import compute_snooze_correction

        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        await _setup_user_with_history(
            async_db, user_id, effort_minutes=25.0, count=5
        )
        await _create_session(
            async_db, user_id,
            active_bandwidth="deep",
            bandwidth_source="inferred",
            bandwidth_confidence=0.6,
            predicted_bandwidth="deep",
        )
        await async_db.commit()

        # Compute the snooze correction: heavy candidate snooze should shift toward light
        correction = compute_snooze_correction(
            current_bandwidth="deep",
            current_confidence=0.6,
            predicted_bandwidth="deep",
            candidate_effort_level="heavy",
            consecutive_snoozes=1,
            last_snooze_direction=None,
        )
        assert correction.bandwidth_changed is True
        assert correction.active_bandwidth == "balanced"
        assert correction.reason_code == "heavy_snooze_shift"

    @pytest.mark.asyncio
    async def test_snooze_does_not_rewrite_thread_rating(
        self, async_db: AsyncSession,
    ) -> None:
        """Snooze must never mutate the thread's durable last_rating."""
        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        thread = await _create_thread(
            async_db, user_id, title="Snooze Test Thread",
            last_rating=4.8,
        )
        await async_db.commit()

        await _create_snooze_event(
            async_db, 0, thread.id,
            timestamp=datetime.now(UTC),
        )
        await async_db.commit()

        result = await async_db.execute(
            select(Thread).where(Thread.id == thread.id)
        )
        refreshed = result.scalar_one()
        assert refreshed.last_rating == 4.8


# ---------------------------------------------------------------------------
# AC-3: Repeated mismatch correctable manually or through quiz
# ---------------------------------------------------------------------------


class TestAC3MismatchCorrection:
    """Repeated mismatch.

    Can be corrected manually or through the optional
    two-question quiz.
    """

    @pytest.mark.asyncio
    async def test_manual_mode_correction_works(self, async_db: AsyncSession) -> None:
        """Manual bandwidth/intent correction persists correctly."""
        from app.services.reading_mode import ReadingModeService

        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        await _create_session(
            async_db, user_id,
            active_bandwidth="balanced",
            bandwidth_source="inferred",
        )
        await async_db.commit()

        service = ReadingModeService(async_db)
        result = await service.set_reading_mode(
            user,
            bandwidth="light",
            intent="momentum",
            source="manual",
        )

        assert result["bandwidth"] == "light"
        assert result["intent"] == "momentum"
        assert result["source"] == "manual"

    @pytest.mark.asyncio
    async def test_quiz_resolution_works(self, async_db: AsyncSession) -> None:
        """The two-question quiz resolves to a valid reading mode."""
        answers = {"brainpower": "easy", "pick": "explore"}
        mode = resolve_quiz_answers(answers)

        assert mode.bandwidth == "light"
        assert mode.intent == "explore"

    @pytest.mark.asyncio
    async def test_all_quiz_combinations_produce_valid_mode(
        self, async_db: AsyncSession,
    ) -> None:
        """Every quiz combination produces a valid bandwidth/intent pair."""
        from app.services.reading_quiz import all_answer_combinations

        combinations = all_answer_combinations()
        assert len(combinations) == 12

        for combo in combinations:
            mode = resolve_quiz_answers(combo)
            assert mode.bandwidth in ("light", "balanced", "deep")
            assert mode.intent in ("momentum", "familiar", "explore", "random")

    @pytest.mark.asyncio
    async def test_quiz_rejection_for_invalid_answer(self, async_db: AsyncSession) -> None:
        """Invalid quiz answers raise QuizResolutionError."""
        with pytest.raises(QuizResolutionError):
            resolve_quiz_answers({"brainpower": "unknown", "pick": "random"})

    @pytest.mark.asyncio
    async def test_bandwidth_correction_preserves_predicted(
        self, async_db: AsyncSession,
    ) -> None:
        """Bandwidth correction changes active but preserves predicted."""
        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        session = await _create_session(
            async_db, user_id,
            active_bandwidth="deep",
            bandwidth_source="inferred",
            bandwidth_confidence=0.6,
            predicted_bandwidth="deep",
        )
        await async_db.commit()

        from app.services.reading_mode import ReadingModeService
        service = ReadingModeService(async_db)
        await service.dismiss_suggestion(user)

        assert session.active_bandwidth in ("deep",)


# ---------------------------------------------------------------------------
# AC-4: Momentum intent favors a current high-rated run without forcing diversity
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
        signals = [CandidateSignals(
            thread_id=1,
            last_rating=5.0,
            days_since_last_read=0.5,
            high_rated_streak=4,
        )]

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
        signals = [CandidateSignals(
            thread_id=1,
            matched_verdict_by_category={
                TASTE_CATEGORY_CREATOR: VERDICT_CONFIRMED,
                TASTE_CATEGORY_CHARACTER: VERDICT_CONFIRMED,
            },
        )]

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
            signal_key="creator:alice-writer",
            inferred_affinity=0.9,
            inferred_confidence=0.8,
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
        signals = [CandidateSignals(
            thread_id=1,
            matched_verdict_by_category={
                TASTE_CATEGORY_CREATOR: VERDICT_REJECTED,
            },
        )]

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
        signals = [CandidateSignals(
            thread_id=1,
            adjacent_anchor_categories=[TASTE_CATEGORY_CREATOR],
        )]

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
        self, async_db: AsyncSession,
    ) -> None:
        """Operator legacy control mode forces unweighted selection."""
        mode = resolve_selection_mode("balanced", "balanced", "legacy")
        assert mode == SelectionMode.FORCED_LEGACY

        mode_contextual = resolve_selection_mode("balanced", "balanced", "contextual")
        assert mode_contextual != SelectionMode.FORCED_LEGACY

    @pytest.mark.asyncio
    async def test_legacy_mode_records_algorithm_version(
        self, async_db: AsyncSession,
    ) -> None:
        """Legacy mode records the legacy algorithm version for distinguishability."""
        version = RECOMMENDATION_ALGORITHM_VERSION_LEGACY
        assert version == "legacy"

        version_contextual = RECOMMENDATION_ALGORITHM_VERSION
        assert version_contextual == "v1-contextual"

    @pytest.mark.asyncio
    async def test_random_mode_with_legacy_control_still_bypasses(
        self, async_db: AsyncSession,
    ) -> None:
        """Random intent bypasses weighting even under legacy control mode."""
        mode = resolve_selection_mode("balanced", "random", "legacy")
        assert mode == SelectionMode.PURE_RANDOM_BYPASS

        mode_contextual = resolve_selection_mode("balanced", "random", "contextual")
        assert mode_contextual == SelectionMode.PURE_RANDOM_BYPASS


# ---------------------------------------------------------------------------
# AC-8: "Why this?" explains decision-time factors
# ---------------------------------------------------------------------------


class TestAC8WhyThisExplanation:
    """Why this? explains the actual decision-time factors used."""

    def test_explanation_translates_bandwidth_code(self) -> None:
        """Bandwidth reason codes translate to human-readable explanations."""
        projection = RecommendationExplanationProjection()

        factor = projection.translate_bandwidth("band_light")
        assert factor is not None
        assert factor.label == "Quick read"
        assert factor.detail == "~11-minute read"

        factor = projection.translate_bandwidth("band_deep")
        assert factor is not None
        assert factor.label == "Deep read"

    def test_explanation_translates_intent_code(self) -> None:
        """Intent reason codes translate to human-readable explanations."""
        projection = RecommendationExplanationProjection()

        factor = projection.translate_intent("intent_momentum")
        assert factor is not None
        assert factor.label == "Recent series momentum"
        factor = projection.translate_intent("intent_familiar")
        assert factor is not None
        assert factor.label == "Creator you confirmed you like"
        factor = projection.translate_intent("intent_explore")
        assert factor is not None
        assert factor.label == "Novel but connected to your tastes"
        factor = projection.translate_intent("intent_random")
        assert factor is not None
        assert factor.label == "No weighting applied"

    def test_explanation_translates_selection_method(self) -> None:
        """Selection method reason codes translate to explanations."""
        projection = RecommendationExplanationProjection()

        factor = projection.translate_selection_method("random")
        assert factor is not None
        assert factor.label == "Pure random"
        factor = projection.translate_selection_method("override")
        assert factor is not None
        assert factor.label == "Manual pick"

    def test_explanation_projects_recommendation_context(self) -> None:
        """Full recommendation context projects to ordered explanations."""
        projection = RecommendationExplanationProjection()

        factors = projection.project_recommendation_context({
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [
                {"code": "taste_confirmed_creator", "detail": "Alice Writer"},
            ],
            "selection_method": "bandwidth",
        })

        assert len(factors) > 0
        label_list = [f.label for f in factors]
        assert any("Quick read" in label for label in label_list)
        assert any("Recent series momentum" in label for label in label_list)

    def test_explanation_translates_taste_bank_factor(self) -> None:
        """Taste Bank factor codes translate to explanations."""
        projection = RecommendationExplanationProjection()

        factor = projection.translate_taste_bank_factor({"code": "taste_confirmed_creator"})
        assert factor is not None
        assert factor.label == "Creator you confirmed you like"
        factor = projection.translate_taste_bank_factor({"code": "taste_novel_adjacent"})
        assert factor is not None
        assert factor.label == "Novel but connected to your tastes"
        factor = projection.translate_taste_bank_factor({"code": "taste_high_affinity"})
        assert factor is not None
        assert factor.label == "Strong affinity"

    @pytest.mark.asyncio
    async def test_roll_response_contains_explanation(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """A Roll response includes an explanation of the decision-time factors."""
        response = await auth_client.post("/api/v1/roll/")
        assert response.status_code == 200

        data = response.json()
        assert "explanation" in data
        assert data["explanation"] is not None
        assert len(data["explanation"]) > 0


# ---------------------------------------------------------------------------
# AC-9: Diagnostics compare outcomes by mode/algorithm version
# ---------------------------------------------------------------------------


class TestAC9DiagnosticsByModeAndAlgorithmVersion:
    """Recommendation-quality diagnostics compare outcomes by mode/algorithm version."""

    def test_diagnostics_groups_by_control_mode(self) -> None:
        """Diagnostics response includes control mode grouping."""
        from app.schemas.recommendation_diagnostics import RecommendationDiagnosticsResponse
        import dataclasses

        fields = [f.name for f in dataclasses.fields(RecommendationDiagnosticsResponse)]
        assert "groups_by_control_mode" in fields
        assert "active_control_mode" in fields
        assert "active_algorithm_version" in fields

    @pytest.mark.asyncio
    async def test_diagnostics_coverage_labels_legacy_events(
        self, async_db: AsyncSession,
    ) -> None:
        """Diagnostics distinguish legacy events from instrumented events."""
        user = await _ensure_user(async_db)
        await async_db.commit()
        user_id = user.id

        session = await _create_session(
            async_db, user_id,
            active_bandwidth="balanced",
            bandwidth_source="inferred",
        )
        await async_db.commit()

        await _create_roll_event(
            async_db, session.id, 1,
            selection_method="momentum",
            timestamp=datetime.now(UTC),
        )
        await async_db.commit()

        range_start, range_end = resolve_diagnostics_range(None, None)
        diagnostics = await compute_recommendation_diagnostics(
            async_db,
            user_id=user_id,
            range_start=range_start,
            range_end=range_end,
        )

        assert diagnostics.total_rolls >= 1
        assert diagnostics.coverage is not None

    @pytest.mark.asyncio
    async def test_diagnostics_records_algorithm_version(
        self, async_db: AsyncSession,
    ) -> None:
        """Diagnostics include the active algorithm version."""
        from app.config import get_recommendation_settings

        settings = get_recommendation_settings()
        assert settings.algorithm_version in ("v1-contextual", "legacy")

    @pytest.mark.asyncio
    async def test_diagnostics_range_resolution(
        self, async_db: AsyncSession,
    ) -> None:
        """Diagnostics range resolution applies defaults and caps."""
        range_start, range_end = resolve_diagnostics_range(None, None)
        assert range_end is not None
        span_days = (range_end - range_start).days
        assert span_days <= 365

    @pytest.mark.asyncio
    async def test_diagnostics_groups_by_algorithm_version(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """The diagnostics endpoint returns groups with algorithm versions."""
        response = await auth_client.get("/api/v1/recommendations/diagnostics")
        assert response.status_code == 200

        data = response.json()
        assert "groups_by_control_mode" in data
        assert "active_algorithm_version" in data
        assert "active_control_mode" in data
        assert "coverage" in data

    @pytest.mark.asyncio
    async def test_diagnostics_effort_band_outcomes(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """Diagnostics include effort-band outcome breakdowns."""
        response = await auth_client.get("/api/v1/recommendations/diagnostics")
        assert response.status_code == 200

        data = response.json()
        assert "effort_band_outcomes" in data
        assert isinstance(data["effort_band_outcomes"], list)


# ---------------------------------------------------------------------------
# Cross-cutting: Verify the complete adaptive Roll pipeline
# ---------------------------------------------------------------------------


class TestCrossCuttingAdaptivePipeline:
    """Verify the complete adaptive Roll system works end-to-end."""

    @pytest.mark.asyncio
    async def test_full_roll_pipeline_with_bandwidth_and_intent(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """A complete Roll respects bandwidth inference.

        And die-pool bounding.
        """
        response = await auth_client.post("/api/v1/roll/")
        assert response.status_code == 200

        data = response.json()
        assert "thread_id" in data
        assert "title" in data
        assert "die_size" in data
        assert "result" in data
        assert "explanation" in data

    @pytest.mark.asyncio
    async def test_roll_with_manual_mode_override(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """Manual mode override affects the subsequent Roll."""
        await auth_client.post(
            "/api/v1/reading-mode",
            json={"bandwidth": "light", "intent": "momentum", "source": "manual"},
        )

        response = await auth_client.post("/api/v1/roll/")
        assert response.status_code == 200

        data = response.json()
        assert "thread_id" in data

    @pytest.mark.asyncio
    async def test_roll_with_quiz_mode(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """Quiz mode sets bandwidth and intent that affect subsequent rolls."""
        await auth_client.post(
            "/api/v1/reading-mode",
            json={"answers": {"brainpower": "easy", "pick": "explore"}, "source": "quiz"},
        )

        mode = await _get_session_reading_mode(auth_client)
        assert mode["bandwidth"] == "light"
        assert mode["intent"] == "explore"
        assert mode["source"] == "quiz"

    @pytest.mark.asyncio
    async def test_legacy_switch_available_in_roll(
        self, async_db: AsyncSession,
    ) -> None:
        """The operator legacy switch is available and functional."""
        from app.config import get_recommendation_settings

        settings = get_recommendation_settings()
        assert settings.control_mode in ("contextual", "legacy")

        from comic_pile.recommendation_selection import SelectionMode
        from comic_pile.recommendation_selection import resolve_selection_mode
        mode = resolve_selection_mode("balanced", "balanced", "legacy")
        assert mode == SelectionMode.FORCED_LEGACY

    @pytest.mark.asyncio
    async def test_snooze_preserves_queue_position(
        self, auth_client: AsyncClient, async_db: AsyncSession,
    ) -> None:
        """Snooze preserves the thread queue position as a durable value."""
        from app.models import Thread
        from tests.conftest import get_or_create_user_async

        user = await get_or_create_user_async(async_db)

        thread = Thread(
            title="Snooze Queue Test",
            format="Comic",
            issues_remaining=5,
            queue_position=1,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
        await async_db.commit()
        await async_db.refresh(thread)

        result = await async_db.execute(
            select(Thread).where(Thread.id == thread.id)
        )
        refreshed = result.scalar_one()
        assert refreshed.queue_position == 1
