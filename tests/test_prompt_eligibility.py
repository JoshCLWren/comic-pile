"""Tests for taste-signal prompt eligibility (issue #1746).

Covers all acceptance criteria:
    - Sparse/weak patterns do not become prompts.
    - Strong, diverse repeated patterns can become eligible.
    - Recently prompted and rejected signals are suppressed correctly.
    - Eligibility rules are centralized and deterministic.
    - Creator-role-specific prompts are preferred when evidence supports it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.taste import (
    PromptCandidate,
    PromptEligibilityConfig,
    PromptEligibilityResult,
    SignalType,
    TasteSignal,
    Verdict,
)
from app.services.prompt_eligibility import (
    DEFAULT_CONFIG,
    _compute_score,
    _is_below_threshold,
    _is_cooldown_active,
    _is_rejection_suppressed,
    _prefer_creator_role_specific,
    evaluate_prompt_eligibility,
)


def _make_signal(**overrides: object) -> TasteSignal:
    """Create a TasteSignal with strong defaults that pass all gates.

    Args:
        **overrides: Field values to override from the strong defaults.

    Returns:
        A TasteSignal that passes all eligibility thresholds by default.
    """
    defaults: dict[str, object] = {
        "user_id": 1,
        "signal_type": SignalType.CREATOR,
        "stable_key": "creator:alan-moore",
        "display_name": "Alan Moore",
        "affinity": 0.8,
        "confidence": 0.85,
        "evidence_count": 5,
        "evidence_diversity": 4,
        "verdict": None,
        "last_prompted_at": None,
        "last_rejected_at": None,
        "is_creator_role": False,
    }
    defaults.update(overrides)
    return TasteSignal(**defaults)


# ---------------------------------------------------------------------------
# Threshold gate tests — sparse/weak patterns must not become prompts
# ---------------------------------------------------------------------------


class TestThresholdGates:
    """Verify that signals below any threshold are rejected."""

    def test_insufficient_evidence_count(self) -> None:
        """Signals with too few evidence observations are ineligible."""
        signal = _make_signal(evidence_count=1, confidence=0.9, affinity=0.5, evidence_diversity=4)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0
        assert len(result.ineligible) == 1
        assert result.ineligible[0].stable_key == "creator:alan-moore"

    def test_insufficient_confidence(self) -> None:
        """Signals with low confidence are ineligible."""
        signal = _make_signal(evidence_count=5, confidence=0.2, affinity=0.5, evidence_diversity=4)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0
        assert len(result.ineligible) == 1

    def test_insufficient_affinity(self) -> None:
        """Signals with weak affinity effect are ineligible."""
        signal = _make_signal(evidence_count=5, confidence=0.8, affinity=0.1, evidence_diversity=4)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0
        assert len(result.ineligible) == 1

    def test_insufficient_diversity(self) -> None:
        """Signals with low evidence diversity are ineligible."""
        signal = _make_signal(evidence_count=5, confidence=0.8, affinity=0.5, evidence_diversity=1)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0
        assert len(result.ineligible) == 1

    def test_zero_affinity_is_ineligible(self) -> None:
        """A signal with exactly zero affinity is below the default threshold."""
        signal = _make_signal(affinity=0.0)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0

    def test_negative_affinity_eligible_when_strong(self) -> None:
        """Negative affinity (dislike) can be eligible when strong enough."""
        signal = _make_signal(affinity=-0.5)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_at_threshold_values_eligible(self) -> None:
        """Signals exactly at threshold values should be eligible."""
        config = PromptEligibilityConfig(
            min_evidence_count=3,
            min_confidence=0.6,
            min_affinity=0.3,
            min_diversity=2,
        )
        signal = _make_signal(
            evidence_count=3,
            confidence=0.6,
            affinity=0.3,
            evidence_diversity=2,
        )
        result = evaluate_prompt_eligibility([signal], config=config)
        assert len(result.candidates) == 1
        assert len(result.ineligible) == 0

    def test_below_threshold_custom_config(self) -> None:
        """Custom config thresholds are respected."""
        config = PromptEligibilityConfig(
            min_evidence_count=10,
            min_confidence=0.9,
            min_affinity=1.0,
            min_diversity=5,
        )
        signal = _make_signal(
            evidence_count=5,
            confidence=0.8,
            affinity=0.5,
            evidence_diversity=3,
        )
        result = evaluate_prompt_eligibility([signal], config=config)
        assert len(result.candidates) == 0
        assert len(result.ineligible) == 1


# ---------------------------------------------------------------------------
# Strong, diverse patterns can become eligible
# ---------------------------------------------------------------------------


class TestStrongPatternsEligible:
    """Verify that strong, diverse signals pass all gates."""

    def test_strong_creator_signal_eligible(self) -> None:
        """A strong creator signal with diverse evidence becomes a candidate."""
        signal = _make_signal()
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1
        assert result.candidates[0].signal.stable_key == "creator:alan-moore"
        assert result.candidates[0].rank == 1

    def test_strong_character_signal_eligible(self) -> None:
        """A strong character signal becomes a candidate."""
        signal = _make_signal(
            signal_type=SignalType.CHARACTER,
            stable_key="character:spider-man",
            display_name="Spider-Man",
        )
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1
        assert result.candidates[0].signal.signal_type == SignalType.CHARACTER

    def test_strong_team_signal_eligible(self) -> None:
        """A strong team signal becomes a candidate."""
        signal = _make_signal(
            signal_type=SignalType.TEAM,
            stable_key="team:x-men",
            display_name="X-Men",
        )
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_strong_publisher_signal_eligible(self) -> None:
        """A strong publisher signal becomes a candidate."""
        signal = _make_signal(
            signal_type=SignalType.PUBLISHER,
            stable_key="publisher:dc-comics",
            display_name="DC Comics",
        )
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_strong_era_signal_eligible(self) -> None:
        """A strong era signal becomes a candidate."""
        signal = _make_signal(
            signal_type=SignalType.ERA,
            stable_key="era:1980s",
            display_name="1980s",
        )
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_multiple_strong_signals_ranked(self) -> None:
        """Multiple strong signals are ranked by composite score."""
        signals = [
            _make_signal(stable_key="creator:a", display_name="A", affinity=0.9, confidence=0.95),
            _make_signal(stable_key="creator:b", display_name="B", affinity=0.5, confidence=0.7),
            _make_signal(stable_key="creator:c", display_name="C", affinity=0.7, confidence=0.8),
        ]
        result = evaluate_prompt_eligibility(signals)
        assert len(result.candidates) == 3
        # Strongest first
        assert result.candidates[0].signal.stable_key == "creator:a"
        assert result.candidates[0].rank == 1
        assert result.candidates[1].rank == 2
        assert result.candidates[2].rank == 3
        # Scores should be strictly ordered
        assert result.candidates[0].score >= result.candidates[1].score
        assert result.candidates[1].score >= result.candidates[2].score

    def test_max_candidates_cap(self) -> None:
        """Only up to max_candidates are returned."""
        config = PromptEligibilityConfig(max_candidates=2)
        signals = [
            _make_signal(stable_key=f"creator:{chr(65 + i)}", display_name=chr(65 + i))
            for i in range(5)
        ]
        result = evaluate_prompt_eligibility(signals, config=config)
        assert len(result.candidates) == 2
        assert result.candidates[0].rank == 1
        assert result.candidates[1].rank == 2


# ---------------------------------------------------------------------------
# Cooldown suppression tests
# ---------------------------------------------------------------------------


class TestCooldownSuppression:
    """Verify recently prompted signals are suppressed."""

    def test_recently_prompted_within_cooldown(self) -> None:
        """A signal prompted within the cooldown window is suppressed."""
        now = datetime(2025, 6, 15, tzinfo=UTC)
        last_prompted = now - timedelta(days=7)  # 7 days ago, cooldown is 14
        signal = _make_signal(last_prompted_at=last_prompted)
        result = evaluate_prompt_eligibility([signal], now=now)
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 1

    def test_prompted_outside_cooldown(self) -> None:
        """A signal prompted outside the cooldown window is eligible."""
        now = datetime(2025, 6, 15, tzinfo=UTC)
        last_prompted = now - timedelta(days=20)  # 20 days ago, cooldown is 14
        signal = _make_signal(last_prompted_at=last_prompted)
        result = evaluate_prompt_eligibility([signal], now=now)
        assert len(result.candidates) == 1
        assert len(result.suppressed) == 0

    def test_exactly_at_cooldown_boundary_eligible(self) -> None:
        """A signal exactly at the cooldown boundary is eligible."""
        now = datetime(2025, 6, 15, tzinfo=UTC)
        last_prompted = now - timedelta(days=14)  # exactly at cooldown
        signal = _make_signal(last_prompted_at=last_prompted)
        result = evaluate_prompt_eligibility([signal], now=now)
        assert len(result.candidates) == 1

    def test_never_prompted_always_eligible(self) -> None:
        """A signal that was never prompted has no cooldown."""
        signal = _make_signal(last_prompted_at=None)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_custom_cooldown_respected(self) -> None:
        """Custom cooldown period is respected."""
        config = PromptEligibilityConfig(cooldown_days=7)
        now = datetime(2025, 6, 15, tzinfo=UTC)
        last_prompted = now - timedelta(days=5)  # within 7-day cooldown
        signal = _make_signal(last_prompted_at=last_prompted)
        result = evaluate_prompt_eligibility([signal], config=config, now=now)
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 1


# ---------------------------------------------------------------------------
# Rejection suppression tests
# ---------------------------------------------------------------------------


class TestRejectionSuppression:
    """Verify rejected signals are permanently suppressed."""

    def test_rejected_signal_suppressed_permanently(self) -> None:
        """A rejected signal is never re-prompted (default: infinite suppression)."""
        signal = _make_signal(verdict=Verdict.REJECTED, last_rejected_at=datetime(2020, 1, 1, tzinfo=UTC))
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 1

    def test_rejected_signal_suppressed_recently(self) -> None:
        """A recently rejected signal is suppressed."""
        now = datetime(2025, 6, 15, tzinfo=UTC)
        signal = _make_signal(verdict=Verdict.REJECTED, last_rejected_at=now - timedelta(days=30))
        result = evaluate_prompt_eligibility([signal], now=now)
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 1

    def test_confirmed_signal_not_suppressed(self) -> None:
        """A confirmed signal is not suppressed by rejection logic."""
        signal = _make_signal(verdict=Verdict.CONFIRMED)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_sometimes_verdict_not_suppressed(self) -> None:
        """A 'sometimes' verdict does not trigger rejection suppression."""
        signal = _make_signal(verdict=Verdict.SOMETIMES)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 1

    def test_rejection_suppress_days_finite(self) -> None:
        """With finite suppression days, a rejected signal becomes eligible after the window."""
        config = PromptEligibilityConfig(rejection_suppress_days=30)
        now = datetime(2025, 6, 15, tzinfo=UTC)
        # Rejected 40 days ago — outside 30-day suppression window
        signal = _make_signal(
            verdict=Verdict.REJECTED,
            last_rejected_at=now - timedelta(days=40),
        )
        result = evaluate_prompt_eligibility([signal], config=config, now=now)
        assert len(result.candidates) == 1

    def test_rejection_suppress_days_not_yet_expired(self) -> None:
        """With finite suppression days, a recently rejected signal is still suppressed."""
        config = PromptEligibilityConfig(rejection_suppress_days=30)
        now = datetime(2025, 6, 15, tzinfo=UTC)
        # Rejected 10 days ago — within 30-day suppression window
        signal = _make_signal(
            verdict=Verdict.REJECTED,
            last_rejected_at=now - timedelta(days=10),
        )
        result = evaluate_prompt_eligibility([signal], config=config, now=now)
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 1

    def test_rejected_without_timestamp_still_suppressed(self) -> None:
        """A rejected signal without a rejection timestamp is still suppressed."""
        signal = _make_signal(verdict=Verdict.REJECTED, last_rejected_at=None)
        result = evaluate_prompt_eligibility([signal])
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 1


# ---------------------------------------------------------------------------
# Creator-role preference tests
# ---------------------------------------------------------------------------


class TestCreatorRolePreference:
    """Verify creator-role-specific prompts are preferred."""

    def test_role_specific_preferred_over_generic(self) -> None:
        """When both generic and role-specific signals exist, only role-specific survives."""
        generic = _make_signal(
            stable_key="creator:alan-moore",
            display_name="Alan Moore",
            is_creator_role=False,
        )
        role_specific = _make_signal(
            stable_key="creator:writer:alan-moore",
            display_name="Alan Moore (Writer)",
            is_creator_role=True,
        )
        result = evaluate_prompt_eligibility([generic, role_specific])
        assert len(result.candidates) == 1
        assert result.candidates[0].signal.is_creator_role is True
        assert result.candidates[0].signal.stable_key == "creator:writer:alan-moore"

    def test_generic_creator_survives_without_role_variant(self) -> None:
        """A generic creator signal survives when no role-specific variant exists."""
        generic = _make_signal(
            stable_key="creator:alan-moore",
            display_name="Alan Moore",
            is_creator_role=False,
        )
        result = evaluate_prompt_eligibility([generic])
        assert len(result.candidates) == 1
        assert result.candidates[0].signal.is_creator_role is False

    def test_role_specific_survives_without_generic(self) -> None:
        """A role-specific signal survives when no generic variant exists."""
        role_specific = _make_signal(
            stable_key="creator:writer:alan-moore",
            display_name="Alan Moore (Writer)",
            is_creator_role=True,
        )
        result = evaluate_prompt_eligibility([role_specific])
        assert len(result.candidates) == 1
        assert result.candidates[0].signal.is_creator_role is True

    def test_role_bonus_in_scoring(self) -> None:
        """Creator-role signals receive a scoring bonus."""
        role_signal = _make_signal(
            stable_key="creator:writer:alan-moore",
            is_creator_role=True,
            affinity=0.5,
            confidence=0.7,
            evidence_count=3,
            evidence_diversity=2,
        )
        generic_signal = _make_signal(
            stable_key="creator:alan-moore",
            is_creator_role=False,
            affinity=0.5,
            confidence=0.7,
            evidence_count=3,
            evidence_diversity=2,
        )
        role_score = _compute_score(role_signal, DEFAULT_CONFIG)
        generic_score = _compute_score(generic_signal, DEFAULT_CONFIG)
        assert role_score > generic_score

    def test_different_creators_both_survive(self) -> None:
        """Two different generic creator signals (different names) both survive."""
        signal_a = _make_signal(
            stable_key="creator:alan-moore",
            display_name="Alan Moore",
            is_creator_role=False,
        )
        signal_b = _make_signal(
            stable_key="creator:frank-miller",
            display_name="Frank Miller",
            is_creator_role=False,
        )
        result = evaluate_prompt_eligibility([signal_a, signal_b])
        assert len(result.candidates) == 2

    def test_multiple_role_variants_same_creator(self) -> None:
        """Multiple role variants for the same creator all survive (writer + artist)."""
        writer = _make_signal(
            stable_key="creator:writer:alan-moore",
            display_name="Alan Moore (Writer)",
            is_creator_role=True,
        )
        artist = _make_signal(
            stable_key="creator:artist:alan-moore",
            display_name="Alan Moore (Artist)",
            is_creator_role=True,
        )
        result = evaluate_prompt_eligibility([writer, artist])
        assert len(result.candidates) == 2


# ---------------------------------------------------------------------------
# Determinism and centralization tests
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Verify eligibility rules are centralized and deterministic."""

    def test_deterministic_output(self) -> None:
        """Identical inputs always produce identical outputs."""
        signals = [
            _make_signal(stable_key="creator:a", affinity=0.8, confidence=0.9),
            _make_signal(stable_key="creator:b", affinity=0.5, confidence=0.7),
        ]
        result_a = evaluate_prompt_eligibility(signals)
        result_b = evaluate_prompt_eligibility(signals)
        assert result_a.candidates == result_b.candidates
        assert result_a.suppressed == result_b.suppressed
        assert result_a.ineligible == result_b.ineligible

    def test_empty_signals_returns_empty(self) -> None:
        """No signals produces an empty result."""
        result = evaluate_prompt_eligibility([])
        assert len(result.candidates) == 0
        assert len(result.suppressed) == 0
        assert len(result.ineligible) == 0

    def test_all_ineligible_when_all_weak(self) -> None:
        """All signals below thresholds land in ineligible."""
        signals = [
            _make_signal(stable_key="creator:a", evidence_count=1, affinity=0.1),
            _make_signal(stable_key="creator:b", confidence=0.2),
        ]
        result = evaluate_prompt_eligibility(signals)
        assert len(result.candidates) == 0
        assert len(result.ineligible) == 2

    def test_mixed_signals_correctly_partitioned(self) -> None:
        """A mix of strong, weak, and suppressed signals are correctly partitioned."""
        now = datetime(2025, 6, 15, tzinfo=UTC)
        strong = _make_signal(stable_key="creator:strong", affinity=0.8, confidence=0.9)
        weak = _make_signal(
            stable_key="creator:weak",
            evidence_count=1,
            confidence=0.3,
            affinity=0.1,
            evidence_diversity=1,
        )
        cooldown = _make_signal(
            stable_key="creator:cooldown",
            last_prompted_at=now - timedelta(days=5),
        )
        rejected = _make_signal(
            stable_key="creator:rejected",
            verdict=Verdict.REJECTED,
            last_rejected_at=now - timedelta(days=100),
        )
        result = evaluate_prompt_eligibility(
            [strong, weak, cooldown, rejected], now=now
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].signal.stable_key == "creator:strong"
        assert len(result.ineligible) == 1
        assert result.ineligible[0].stable_key == "creator:weak"
        assert len(result.suppressed) == 2
        suppressed_keys = {s.stable_key for s in result.suppressed}
        assert "creator:cooldown" in suppressed_keys
        assert "creator:rejected" in suppressed_keys

    def test_config_isolation(self) -> None:
        """Different config instances produce independent results."""
        config_a = PromptEligibilityConfig(min_evidence_count=2)
        config_b = PromptEligibilityConfig(min_evidence_count=10)
        signal = _make_signal(evidence_count=5)
        result_a = evaluate_prompt_eligibility([signal], config=config_a)
        result_b = evaluate_prompt_eligibility([signal], config=config_b)
        assert len(result_a.candidates) == 1
        assert len(result_b.candidates) == 0


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


class TestScoring:
    """Verify composite scoring behavior."""

    def test_higher_affinity_scores_higher(self) -> None:
        """Higher affinity produces a higher score, all else equal."""
        low = _make_signal(stable_key="a", affinity=0.4, confidence=0.8, evidence_count=5, evidence_diversity=4)
        high = _make_signal(stable_key="b", affinity=0.9, confidence=0.8, evidence_count=5, evidence_diversity=4)
        score_low = _compute_score(low, DEFAULT_CONFIG)
        score_high = _compute_score(high, DEFAULT_CONFIG)
        assert score_high > score_low

    def test_higher_confidence_scores_higher(self) -> None:
        """Higher confidence produces a higher score, all else equal."""
        low = _make_signal(stable_key="a", confidence=0.6, evidence_count=5, evidence_diversity=4)
        high = _make_signal(stable_key="b", confidence=0.95, evidence_count=5, evidence_diversity=4)
        score_low = _compute_score(low, DEFAULT_CONFIG)
        score_high = _compute_score(high, DEFAULT_CONFIG)
        assert score_high > score_low

    def test_higher_diversity_scores_higher(self) -> None:
        """Higher diversity produces a higher score, all else equal."""
        low = _make_signal(stable_key="a", evidence_diversity=2)
        high = _make_signal(stable_key="b", evidence_diversity=8)
        score_low = _compute_score(low, DEFAULT_CONFIG)
        score_high = _compute_score(high, DEFAULT_CONFIG)
        assert score_high > score_low

    def test_score_is_bounded(self) -> None:
        """Composite score stays within [0, 1]."""
        signal = _make_signal(affinity=1.0, confidence=1.0, evidence_count=100, evidence_diversity=50, is_creator_role=True)
        score = _compute_score(signal, DEFAULT_CONFIG)
        assert 0.0 <= score <= 1.0

    def test_tiebreak_by_stable_key(self) -> None:
        """Signals with equal scores are tiebroken by stable_key alphabetically."""
        signal_a = _make_signal(stable_key="creator:zzz", affinity=0.5, confidence=0.7, evidence_count=3, evidence_diversity=2)
        signal_b = _make_signal(stable_key="creator:aaa", affinity=0.5, confidence=0.7, evidence_count=3, evidence_diversity=2)
        result = evaluate_prompt_eligibility([signal_a, signal_b])
        assert len(result.candidates) == 2
        # Alphabetically earlier key comes first when scores are equal
        assert result.candidates[0].signal.stable_key == "creator:aaa"
        assert result.candidates[1].signal.stable_key == "creator:zzz"


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Verify Pydantic schema constraints."""

    def test_taste_signal_rejects_negative_evidence_count(self) -> None:
        """TasteSignal rejects negative evidence_count."""
        with pytest.raises(Exception):
            TasteSignal(
                user_id=1,
                signal_type=SignalType.CREATOR,
                stable_key="creator:test",
                display_name="Test",
                affinity=0.5,
                confidence=0.5,
                evidence_count=-1,
                evidence_diversity=1,
            )

    def test_taste_signal_rejects_confidence_out_of_range(self) -> None:
        """TasteSignal rejects confidence outside [0, 1]."""
        with pytest.raises(Exception):
            TasteSignal(
                user_id=1,
                signal_type=SignalType.CREATOR,
                stable_key="creator:test",
                display_name="Test",
                affinity=0.5,
                confidence=1.5,
                evidence_count=3,
                evidence_diversity=2,
            )

    def test_config_rejects_zero_min_evidence(self) -> None:
        """PromptEligibilityConfig rejects min_evidence_count < 1."""
        with pytest.raises(Exception):
            PromptEligibilityConfig(min_evidence_count=0)

    def test_config_rejects_negative_cooldown(self) -> None:
        """PromptEligibilityConfig rejects negative cooldown_days."""
        with pytest.raises(Exception):
            PromptEligibilityConfig(cooldown_days=-1)

    def test_frozen_models(self) -> None:
        """TasteSignal and PromptEligibilityConfig are immutable."""
        signal = _make_signal()
        with pytest.raises(Exception):
            signal.affinity = 1.0  # type: ignore[misc]
        config = PromptEligibilityConfig()
        with pytest.raises(Exception):
            config.min_evidence_count = 10  # type: ignore[misc]
