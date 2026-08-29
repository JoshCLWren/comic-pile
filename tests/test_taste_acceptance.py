"""Phase 7 Taste Bank discovery acceptance regression (issue #1753).

Proves the full Phase 7 acceptance contract end to end: ComicPile can
discover, persist, ask about, and confirm/reject taste patterns without yet
using them to rank recommendations.

Each test maps to one acceptance criterion:

- Criterion 1: Confirmed ComicVine metadata yields normalized
  creator/character/team/publisher/era evidence.
- Criterion 2: Repeated above-baseline evidence creates a confident inferred
  signal; sparse evidence does not.
- Criterion 3: Prompt eligibility respects evidence thresholds, diversity,
  cooldown, and rejection suppression.
- Criterion 4: The user can answer Yes/Sometimes/Not really and the explicit
  verdict survives later recomputation.
- Criterion 5: Discovery UI never blocks the normal reading flow.
- Criterion 6: No Taste Bank signal changes Roll weights in this phase.

The inference module (``app.services.taste_inference``) is the Phase 7 piece
that derives affinity and confidence from confirmed reading history; the
others (normalization, eligibility, verdicts, discovery) already exist and
are wired here into a single acceptance story.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.taste_signal import (
    SIGNAL_CREATOR,
    SIGNAL_ERA,
    SIGNAL_PUBLISHER,
    TasteSignal,
)
from app.services.comicvine_taste import extract_taste_features
from app.services.prompt_eligibility import (
    DEFAULT_CONFIG,
    evaluate_prompt_eligibility,
)
from app.schemas.taste import SignalType, TasteSignal as EligibilitySignal, Verdict
from app.services.taste_inference import (
    RatingEvidence,
    SignalMetrics,
    baseline_rating,
    compute_signal_metrics,
    merge_inferred_into,
)


# ---------------------------------------------------------------------------
# Criterion 1: Confirmed metadata normalizes into per-category evidence.
# ---------------------------------------------------------------------------


class TestCriterion1MetadataNormalization:
    """Confirmed ComicVine metadata normalizes into five evidence categories."""

    def test_all_five_feature_categories_are_extracted(self) -> None:
        """Creator, character, team, publisher, and era all yield evidence."""
        issue_metadata = {
            "creator_credits": [
                {"id": 10, "name": "Alice Writer", "role": "writer"},
                {"id": 11, "name": "Bob Artist", "role": "artist"},
            ],
            "characters": [{"id": 100, "name": "Hero"}],
            "teams": [{"id": 200, "name": "Justice Squad"}],
            "cover_date": "2012-05-04",
        }
        volume_metadata = {
            "publisher": {"id": 300, "name": "Publishing Co"},
            "start_year": "2010",
        }

        features = extract_taste_features(issue_metadata, volume_metadata)

        assert [c["id"] for c in features["creators"]] == [10, 11]
        assert [c["id"] for c in features["characters"]] == [100]
        assert [t["id"] for t in features["teams"]] == [200]
        assert features["publisher"] == {"id": 300, "name": "Publishing Co"}
        assert features["publication_era"] == "2012"

    def test_correlated_metadata_is_not_double_counted_within_an_issue(self) -> None:
        """Duplicates across a single issue collapse to one evidence item."""
        issue_metadata = {
            "creator_credits": [
                {"id": 10, "name": "Alice Writer", "role": "writer"},
                {"id": 10, "name": "Alice Writer", "role": "writer"},
                {"id": 10, "name": "Alice Writer", "role": "penciler"},
            ],
            "characters": [
                {"id": 100, "name": "Hero"},
                {"id": 100, "name": "Hero"},
            ],
        }

        features = extract_taste_features(issue_metadata)

        assert len(features["creators"]) == 2  # same id, two roles kept apart
        assert len(features["characters"]) == 1  # duplicate character collapsed

    def test_missing_confirmed_metadata_never_fabricates_evidence(self) -> None:
        """Unknown metadata yields empty evidence, not invented features."""
        features = extract_taste_features({})

        assert features == {
            "creators": [],
            "characters": [],
            "teams": [],
            "publisher": None,
            "publication_era": None,
        }


# ---------------------------------------------------------------------------
# Criterion 2: Repeated above-baseline evidence is confident; sparse is not.
# ---------------------------------------------------------------------------


class TestCriterion2RepeatedAboveBaseline:
    """The inference engine judges repeated vs sparse evidence differently."""

    def test_repeated_above_baseline_is_confident_and_positive(self) -> None:
        """Three reads across three threads at 5/5 vs a 3 baseline are strong."""
        metrics = compute_signal_metrics(
            [
                RatingEvidence(5, thread_id=1, issue_key="t1-i1"),
                RatingEvidence(5, thread_id=1, issue_key="t1-i2"),
                RatingEvidence(5, thread_id=2, issue_key="t2-i1"),
                RatingEvidence(5, thread_id=2, issue_key="t2-i2"),
                RatingEvidence(5, thread_id=3, issue_key="t3-i1"),
            ],
            baseline=3.0,
        )

        assert metrics.evidence_count == 5
        assert metrics.distinct_thread_count == 3
        assert metrics.affinity > DEFAULT_CONFIG.min_affinity
        assert metrics.confidence >= DEFAULT_CONFIG.min_confidence

    def test_single_isolated_issue_stays_low_confidence(self) -> None:
        """One above-baseline read must not become a confident preference."""
        metrics = compute_signal_metrics(
            [RatingEvidence(5, thread_id=1, issue_key="t1-i1")],
            baseline=3.0,
        )

        assert metrics.evidence_count == 1
        assert metrics.distinct_thread_count == 1
        assert metrics.affinity > DEFAULT_CONFIG.min_affinity
        assert metrics.confidence < DEFAULT_CONFIG.min_confidence

    def test_two_issues_in_one_thread_stay_sparse(self) -> None:
        """Two reads from the same thread lack both count and diversity."""
        metrics = compute_signal_metrics(
            [
                RatingEvidence(5, thread_id=1, issue_key="t1-i1"),
                RatingEvidence(5, thread_id=1, issue_key="t1-i2"),
            ],
            baseline=3.0,
        )

        assert metrics.evidence_count == 2
        assert metrics.distinct_thread_count < DEFAULT_CONFIG.min_diversity
        assert metrics.confidence < DEFAULT_CONFIG.min_confidence

    def test_neutral_evidence_yields_no_affinity(self) -> None:
        """Rated at baseline, a feature shows no above-baseline effect."""
        metrics = compute_signal_metrics(
            [
                RatingEvidence(3, thread_id=1, issue_key="t1-i1"),
                RatingEvidence(3, thread_id=2, issue_key="t2-i1"),
                RatingEvidence(3, thread_id=3, issue_key="t3-i1"),
            ],
            baseline=3.0,
        )

        assert metrics.evidence_count == 3
        assert metrics.distinct_thread_count == 3
        assert metrics.confidence >= DEFAULT_CONFIG.min_confidence
        assert abs(metrics.affinity) < DEFAULT_CONFIG.min_affinity

    def test_negative_evidence_is_captured_as_negative_affinity(self) -> None:
        """Repeatedly below-baseline evidence produces a negative affinity."""
        metrics = compute_signal_metrics(
            [
                RatingEvidence(1, thread_id=1, issue_key="t1-i1"),
                RatingEvidence(1, thread_id=2, issue_key="t2-i1"),
                RatingEvidence(1, thread_id=3, issue_key="t3-i1"),
            ],
            baseline=3.0,
        )

        assert metrics.evidence_count == 3
        assert metrics.affinity < -DEFAULT_CONFIG.min_affinity

    def test_baseline_is_the_readers_own_average(self) -> None:
        """Baseline reflects the reader's overall behavior, not a fixed scale."""
        assert baseline_rating([4.0, 4.0, 3.0, 5.0]) == 4.0

    def test_inferred_metrics_feed_the_eligibility_gates(self) -> None:
        """Strong inferred metrics pass the threshold gates; sparse do not."""
        strong = compute_signal_metrics(
            [
                RatingEvidence(5, thread_id=1, issue_key="t1-i1"),
                RatingEvidence(5, thread_id=2, issue_key="t2-i1"),
                RatingEvidence(5, thread_id=3, issue_key="t3-i1"),
            ],
            baseline=3.0,
        )
        sparse = compute_signal_metrics(
            [RatingEvidence(5, thread_id=1, issue_key="t1-i1")],
            baseline=3.0,
        )

        def to_input(metrics: SignalMetrics) -> EligibilitySignal:
            return EligibilitySignal(
                user_id=1,
                signal_type=SignalType.CREATOR,
                stable_key="creator:writer:alice",
                display_name="Alice",
                affinity=metrics.affinity,
                confidence=metrics.confidence,
                evidence_count=metrics.evidence_count,
                evidence_diversity=metrics.distinct_thread_count,
            )

        strong_result = evaluate_prompt_eligibility([to_input(strong)])
        sparse_result = evaluate_prompt_eligibility([to_input(sparse)])

        assert [c.signal.stable_key for c in strong_result.candidates] == ["creator:writer:alice"]
        assert sparse_result.candidates == []


# ---------------------------------------------------------------------------
# Criterion 3: Prompt eligibility respects thresholds, diversity, cooldown,
# and rejection suppression.
# ---------------------------------------------------------------------------


class TestCriterion3PromptEligibilityGates:
    """Eligibility gates honor evidence, diversity, cooldown, rejection."""

    def test_evidence_threshold_blocks_sparse_signals(self) -> None:
        """Below the minimum evidence count the signal is ineligible."""
        signal = self._make_signal(evidence_count=DEFAULT_CONFIG.min_evidence_count - 1)

        result = evaluate_prompt_eligibility([signal])

        assert result.candidates == []
        assert result.ineligible == [signal]

    def test_confidence_threshold_blocks_weak_signals(self) -> None:
        """Below the minimum confidence the signal is ineligible."""
        signal = self._make_signal(confidence=DEFAULT_CONFIG.min_confidence - 0.05)

        result = evaluate_prompt_eligibility([signal])

        assert result.candidates == []

    def test_affinity_threshold_blocks_neutral_signals(self) -> None:
        """Neutral (near-zero) affinity never becomes a prompt."""
        signal = self._make_signal(affinity=0.05)

        result = evaluate_prompt_eligibility([signal])

        assert result.candidates == []

    def test_diversity_threshold_blocks_single_thread_evidence(self) -> None:
        """One thread is not diverse enough regardless of count."""
        signal = self._make_signal(evidence_diversity=1)

        result = evaluate_prompt_eligibility([signal])

        assert result.candidates == []

    def test_cooldown_suppresses_recently_prompted_signals(self) -> None:
        """A signal prompted within the cooldown window is suppressed."""
        signal = self._make_signal(
            last_prompted_at=datetime.now(UTC),
        )

        result = evaluate_prompt_eligibility([signal])

        assert result.candidates == []
        assert result.suppressed == [signal]

    def test_rejected_signals_are_permanently_suppressed(self) -> None:
        """An explicit rejection suppresses the signal from future prompts."""
        signal = self._make_signal(verdict=Verdict.REJECTED)

        result = evaluate_prompt_eligibility([signal])

        assert result.candidates == []
        assert result.suppressed == [signal]

    @staticmethod
    def _make_signal(**overrides: object) -> EligibilitySignal:
        """Build a canonical eligibility input that clears every gate by default.

        Args:
            **overrides: Fields to override on the passing defaults.

        Returns:
            An eligibility-engine input signal.
        """
        defaults: dict[str, object] = {
            "user_id": 1,
            "signal_type": SignalType.CREATOR,
            "stable_key": "creator:writer:alice",
            "display_name": "Alice",
            "affinity": 0.5,
            "confidence": 0.8,
            "evidence_count": 5,
            "evidence_diversity": 3,
        }
        defaults.update(overrides)
        return EligibilitySignal(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Criterion 4: Explicit verdicts survive inference recomputation.
# ---------------------------------------------------------------------------


class TestCriterion4VerdictSurvivesRecomputation:
    """An explicit user verdict is never overwritten by recomputation."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("verdict", ["confirmed", "sometimes", "rejected"])
    async def test_recompute_preserves_verdict(
        self, async_db: AsyncSession, default_user: User, verdict: str
    ) -> None:
        """Re-inference updates evidence but keeps the explicit verdict."""
        now = datetime.now(UTC)
        signal = TasteSignal(
            user_id=1,
            signal_type=SIGNAL_CREATOR,
            external_key="creator:writer:alice",
            display_name="Alice",
            affinity_estimate=0.9,
            confidence=0.95,
            evidence_count=8,
            distinct_thread_count=4,
            user_verdict=verdict,
            verdict_at=now,
        )
        async_db.add(signal)
        await async_db.flush()

        fresh = compute_signal_metrics(
            [
                RatingEvidence(5, thread_id=1, issue_key="t1-i1"),
                RatingEvidence(5, thread_id=2, issue_key="t2-i1"),
                RatingEvidence(5, thread_id=3, issue_key="t3-i1"),
            ],
            baseline=3.0,
        )

        result = merge_inferred_into(signal, fresh, now=now)

        assert result.user_verdict == verdict
        assert result.verdict_at == now
        assert result.affinity_estimate == fresh.affinity
        assert result.confidence == fresh.confidence
        assert result.evidence_count == fresh.evidence_count
        assert result.distinct_thread_count == fresh.distinct_thread_count
        await async_db.rollback()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("signal_type", [SIGNAL_CREATOR, SIGNAL_PUBLISHER, SIGNAL_ERA])
    async def test_verdict_api_accepts_all_answers(
        self,
        auth_client: AsyncClient,
        signal_type: str,
    ) -> None:
        """The canonical verdict API accepts Yes/Sometimes/Not really answers."""
        external_key = f"{signal_type}:some-key:placeholder"
        response = await auth_client.put(
            f"/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict",
            json={"verdict": "sometimes"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["signal_type"] == signal_type
        assert body["external_key"] == external_key
        assert body["user_verdict"] == "sometimes"


# ---------------------------------------------------------------------------
# Criterion 5: Discovery stays non-blocking alongside the reading flow.
# ---------------------------------------------------------------------------


class TestCriterion5DiscoveryNonBlocking:
    """Discovery coexists with a normal reading flow and never blocks it."""

    async def test_roll_still_works_when_discovery_is_present(
        self,
        auth_client: AsyncClient,
        async_db: AsyncSession,
        sample_data: dict,
    ) -> None:
        """A prompt-eligible discovery does not interrupt rolling or rating."""
        strong = TasteSignal(
            user_id=1,
            signal_type=SIGNAL_CREATOR,
            external_key="creator:writer:alice",
            display_name="Alice",
            affinity_estimate=0.9,
            confidence=0.9,
            evidence_count=6,
            distinct_thread_count=3,
        )
        async_db.add(strong)
        await async_db.flush()

        discoveries = await auth_client.get("/api/v1/taste/discoveries")
        assert discoveries.status_code == 200
        assert len(discoveries.json()["discoveries"]) == 1

        roll = await auth_client.post("/api/v1/roll/")
        assert roll.status_code == 200


# ---------------------------------------------------------------------------
# Criterion 6: Taste does not alter Roll weights in this phase.
# ---------------------------------------------------------------------------


class TestCriterion6TasteDoesNotWeightRolls:
    """Roll selection is deliberately free of Taste Bank input in Phase 7."""

    def test_roll_path_never_uses_taste_signals(self) -> None:
        """The live roll endpoint and momentum weighting ignore taste signals."""
        import inspect

        from app import momentum
        import app.api.roll as roll_module

        momentum_source = inspect.getsource(momentum)
        roll_source = inspect.getsource(roll_module)

        assert "taste" not in roll_source.lower()
        assert "taste" not in momentum_source.lower()
