"""Unit tests for inferred Taste Bank affinity/confidence (issue #1745).

These are pure, database-free tests covering the acceptance contract:

- Strong repeated above-baseline evidence creates a high-confidence signal.
- One or two isolated issues stay low-confidence.
- Evidence diversity raises confidence relative to a single-run cluster.
- Neutral evidence stays near-zero affinity.
- Negative evidence produces a negative affinity.
- Correlated evidence from one issue does not double-count.
- Explicit verdicts survive recomputation (verdict never written by merge).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.repositories.taste_signal import merge_inferred_into_signal
from app.services.taste_inference import (
    InferenceConfig,
    InferredSignal,
    TasteObservation,
    compute_inferred_signal,
    recompute_from_reading_history,
)


def _obs(thread_id: int, rating: float | None = None, accepted: bool | None = None) -> TasteObservation:
    return TasteObservation(thread_id=thread_id, rating=rating, accepted=accepted)


def test_strong_repeated_above_baseline_creates_high_confidence_signal() -> None:
    """A sustained above-baseline pattern raises affinity and confidence."""
    baseline = 3.0
    observations = [
        _obs(thread_id=t, rating=baseline + 1.5) for t in range(1, 11)
    ]
    result = compute_inferred_signal(observations, baseline_rating=baseline)

    assert result.affinity_estimate == 1.0
    assert result.evidence_count == 10
    assert result.distinct_thread_count == 10
    assert result.confidence >= 0.95


def test_one_isolated_issue_stays_low_confidence() -> None:
    """A single isolated above-baseline issue stays low-confidence."""
    baseline = 3.0
    result = compute_inferred_signal(
        [_obs(thread_id=1, rating=baseline + 1.5)], baseline_rating=baseline
    )
    assert result.affinity_estimate == 1.0
    assert result.evidence_count == 1
    assert result.confidence < 0.6  # below prompt-eligibility threshold


def test_two_isolated_issues_stay_low_confidence() -> None:
    """Two isolated issues still stay below the prompt threshold."""
    baseline = 3.0
    result = compute_inferred_signal(
        [_obs(thread_id=1, rating=baseline + 1.5), _obs(thread_id=2, rating=baseline + 1.5)],
        baseline_rating=baseline,
    )
    assert result.affinity_estimate == 1.0
    assert result.evidence_count == 2
    assert result.confidence < 0.6  # still below prompt-eligibility threshold


def test_evidence_diversity_raises_confidence_over_single_run_cluster() -> None:
    """Spreading evidence across threads beats one clustered run."""
    baseline = 3.0
    single_run = [_obs(thread_id=1, rating=baseline + 1.5) for _ in range(6)]
    spread = [_obs(thread_id=t, rating=baseline + 1.5) for t in range(1, 7)]

    single = compute_inferred_signal(single_run, baseline_rating=baseline)
    diverse = compute_inferred_signal(spread, baseline_rating=baseline)

    assert single.distinct_thread_count == 1
    assert diverse.distinct_thread_count == 6
    assert diverse.confidence > single.confidence
    # A single-run cluster cannot out-rank evidence spread across threads,
    # and the discovery layer's min_diversity gate still blocks single-thread
    # prompts even if confidence reaches the prompt threshold.
    assert diverse.confidence >= 0.6
    assert single.confidence < diverse.confidence


def test_neutral_evidence_stays_near_zero_affinity() -> None:
    """At-baseline ratings produce a near-zero affinity."""
    baseline = 3.0
    observations = [_obs(thread_id=t, rating=baseline) for t in range(1, 9)]
    result = compute_inferred_signal(observations, baseline_rating=baseline)

    assert abs(result.affinity_estimate) < 1e-9
    assert result.evidence_count == 8
    assert result.distinct_thread_count == 8


def test_negative_evidence_produces_negative_affinity() -> None:
    """Sustained below-baseline ratings produce a negative affinity."""
    baseline = 3.0
    observations = [_obs(thread_id=t, rating=baseline - 1.5) for t in range(1, 9)]
    result = compute_inferred_signal(observations, baseline_rating=baseline)

    assert result.affinity_estimate == -1.0
    assert result.evidence_count == 8
    assert result.confidence >= 0.9


def test_sparse_negative_evidence_stays_low_confidence() -> None:
    """A single below-baseline issue stays low-confidence."""
    baseline = 3.0
    result = compute_inferred_signal(
        [_obs(thread_id=1, rating=baseline - 1.5)], baseline_rating=baseline
    )
    assert result.affinity_estimate == -1.0
    assert result.confidence < 0.6


def test_correlated_metadata_from_one_issue_does_not_double_count() -> None:
    """Duplicated credits on one issue count as one piece of evidence."""
    # Same feature credited many times on one issue/thread must not inflate
    # evidence beyond a single occurrence; confidence stays low.
    baseline = 3.0
    issue_metadata = {
        "creator_credits": [
            {"id": 100, "name": "Alan Moore"},
            {"id": 100, "name": "Alan Moore"},  # duplicate, must dedup
            {"id": 100, "name": "Alan Moore", "role": "writer"},
        ],
        "characters": [{"id": 7, "name": "Swamp Thing"}],
        "cover_date": "1984-05-01",
    }
    rated_items = [
        {
            "thread_id": 1,
            "issue_id": 1,
            "rating": baseline + 1.5,
            "accepted": None,
            "issue_metadata": issue_metadata,
            "volume_metadata": None,
        }
        for _ in range(5)
    ]
    results = recompute_from_reading_history(baseline, rated_items)

    by_key = {r.external_key: r for r in results}
    # The duplicate "Alan Moore" (no role) collapses to one key; the
    # role-specific writer variant is a separate feature.
    assert "creator:100" in by_key
    assert by_key["creator:100"].inferred.evidence_count == 1
    # A single issue/thread cannot reach prompt-confident confidence.
    for feature in results:
        assert feature.inferred.confidence < 0.6


def test_recompute_spreads_features_across_threads_into_high_confidence() -> None:
    """The same feature across threads reaches prompt confidence."""
    baseline = 3.0
    issue_metadata = {
        "creator_credits": [{"id": 100, "name": "Alan Moore", "role": "writer"}],
        "characters": [{"id": 7, "name": "Swamp Thing"}],
        "cover_date": "1984-05-01",
    }
    rated_items = [
        {
            "thread_id": t,
            "issue_id": t,
            "rating": baseline + 1.5,
            "accepted": None,
            "issue_metadata": issue_metadata,
            "volume_metadata": None,
        }
        for t in range(1, 9)
    ]
    results = recompute_from_reading_history(baseline, rated_items)

    by_key = {r.external_key: r for r in results}
    assert by_key["creator:writer:100"].inferred.evidence_count == 8
    assert by_key["creator:writer:100"].inferred.distinct_thread_count == 8
    assert by_key["creator:writer:100"].inferred.confidence >= 0.6
    assert by_key["character:7"].inferred.confidence >= 0.6


def test_merge_inferred_into_signal_preserves_verdict_columns() -> None:
    """Column updates never include the verdict columns."""
    inferred = InferredSignal(
        affinity_estimate=0.8,
        confidence=0.7,
        evidence_count=5,
        distinct_thread_count=4,
    )
    now = datetime.now(UTC)
    updates = merge_inferred_into_signal(inferred, "Alan Moore", now, is_new=False)

    assert "user_verdict" not in updates
    assert "verdict_at" not in updates
    assert updates["affinity_estimate"] == 0.8
    assert updates["confidence"] == 0.7
    assert updates["evidence_count"] == 5
    assert updates["last_observed_at"] == now


def test_merge_inferred_into_signal_sets_first_observed_only_when_new() -> None:
    """first_observed_at is only set on newly created rows."""
    inferred = InferredSignal(
        affinity_estimate=0.5,
        confidence=0.5,
        evidence_count=2,
        distinct_thread_count=2,
    )
    now = datetime.now(UTC)
    new_updates = merge_inferred_into_signal(inferred, "X", now, is_new=True)
    existing_updates = merge_inferred_into_signal(inferred, "X", now, is_new=False)

    assert "first_observed_at" in new_updates
    assert "first_observed_at" not in existing_updates


def test_empty_history_yields_zero_signal() -> None:
    """No observations produce the zero signal."""
    result = compute_inferred_signal([], baseline_rating=3.0)
    assert result == InferredSignal(0.0, 0.0, 0, 0)


def test_mixed_sign_evidence_lowers_confidence() -> None:
    """Opposing evidence directions lower confidence."""
    baseline = 3.0
    # Half far above, half far below: net affinity ~0, low consistency.
    observations = [
        _obs(thread_id=1, rating=baseline + 1.5),
        _obs(thread_id=2, rating=baseline + 1.5),
        _obs(thread_id=3, rating=baseline - 1.5),
        _obs(thread_id=4, rating=baseline - 1.5),
    ]
    result = compute_inferred_signal(observations, baseline_rating=baseline)
    assert abs(result.affinity_estimate) < 1e-9
    assert result.confidence < 0.6


def test_acceptance_only_evidence_contributes_positive_signal() -> None:
    """Accepted rolls without ratings still contribute a positive lift."""
    baseline = 3.0
    observations = [
        _obs(thread_id=t, rating=None, accepted=True) for t in range(1, 9)
    ]
    result = compute_inferred_signal(observations, baseline_rating=baseline)
    assert result.affinity_estimate > 0.0
    assert result.evidence_count == 8
    assert result.distinct_thread_count == 8


def test_custom_config_is_honored() -> None:
    """Custom tuning constants are applied to the calculation."""
    config = InferenceConfig(evidence_ceil=3, diversity_ceil=2)
    baseline = 3.0
    observations = [_obs(thread_id=t, rating=baseline + 1.0) for t in range(1, 4)]
    result = compute_inferred_signal(observations, baseline_rating=baseline, config=config)
    assert result.evidence_count == 3
    assert result.distinct_thread_count == 3
    assert result.confidence >= 0.6  # saturated earlier under custom config
