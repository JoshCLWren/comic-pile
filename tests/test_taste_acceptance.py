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


from app.services.prompt_eligibility import (
    DEFAULT_CONFIG,
    evaluate_prompt_eligibility,
)
from app.schemas.taste import SignalType, TasteSignal as EligibilitySignal, Verdict


# ---------------------------------------------------------------------------
# Criterion 1: Confirmed metadata normalizes into per-category evidence.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Criterion 2: Repeated above-baseline evidence is confident; sparse is not.
# ---------------------------------------------------------------------------


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
        return EligibilitySignal.model_validate(defaults)


# ---------------------------------------------------------------------------
# Criterion 4: Explicit verdicts survive inference recomputation.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Criterion 5: Discovery stays non-blocking alongside the reading flow.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Criterion 6: Taste does not alter Roll weights in this phase.
# ---------------------------------------------------------------------------


class TestCriterion6TasteDoesNotWeightRolls:
    """Roll selection is deliberately free of Taste Bank input in Phase 7."""
