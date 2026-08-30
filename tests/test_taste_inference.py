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

from app.repositories.taste_signal import merge_metrics_into_signal
from app.services.taste_inference import (
    RatingEvidence,
    SignalMetrics,
    baseline_rating,
    compute_confidence,
    compute_signal_metrics,
)


def test_strong_repeated_above_baseline_creates_high_confidence_signal() -> None:
    """A sustained above-baseline pattern raises affinity and confidence."""
    baseline = 3.0
    evidence = [
        RatingEvidence(rating=baseline + 1.5, thread_id=t, issue_key=f"t{t}-i1")
        for t in range(1, 11)
    ]
    result = compute_signal_metrics(evidence, baseline=baseline)

    assert result.affinity > 0
    assert result.evidence_count == 10
    assert result.distinct_thread_count == 10
    assert result.confidence >= 0.6


def test_one_isolated_issue_stays_low_confidence() -> None:
    """A single isolated above-baseline issue stays low-confidence."""
    baseline = 3.0
    evidence = [RatingEvidence(rating=baseline + 1.5, thread_id=1, issue_key="t1-i1")]
    result = compute_signal_metrics(evidence, baseline=baseline)
    assert result.affinity > 0
    assert result.evidence_count == 1
    assert result.confidence < 0.6


def test_two_isolated_issues_stay_low_confidence() -> None:
    """Two isolated issues still stay below the prompt threshold."""
    baseline = 3.0
    evidence = [
        RatingEvidence(rating=baseline + 1.5, thread_id=1, issue_key="t1-i1"),
        RatingEvidence(rating=baseline + 1.5, thread_id=2, issue_key="t2-i1"),
    ]
    result = compute_signal_metrics(evidence, baseline=baseline)
    assert result.affinity > 0
    assert result.evidence_count == 2
    assert result.confidence < 0.6


def test_evidence_diversity_raises_confidence_over_single_run_cluster() -> None:
    """Spreading evidence across threads beats one clustered run."""
    baseline = 3.0
    single_run = [
        RatingEvidence(rating=baseline + 1.5, thread_id=1, issue_key=f"t1-i{i}")
        for i in range(1, 7)
    ]
    spread = [
        RatingEvidence(rating=baseline + 1.5, thread_id=t, issue_key=f"t{t}-i1")
        for t in range(1, 7)
    ]

    single = compute_signal_metrics(single_run, baseline=baseline)
    diverse = compute_signal_metrics(spread, baseline=baseline)

    assert single.distinct_thread_count == 1
    assert diverse.distinct_thread_count == 6
    assert diverse.confidence > single.confidence


def test_neutral_evidence_stays_near_zero_affinity() -> None:
    """At-baseline ratings produce a near-zero affinity."""
    baseline = 3.0
    evidence = [
        RatingEvidence(rating=baseline, thread_id=t, issue_key=f"t{t}-i1")
        for t in range(1, 9)
    ]
    result = compute_signal_metrics(evidence, baseline=baseline)

    assert abs(result.affinity) < 1e-9
    assert result.evidence_count == 8
    assert result.distinct_thread_count == 8


def test_negative_evidence_produces_negative_affinity() -> None:
    """Sustained below-baseline ratings produce a negative affinity."""
    baseline = 3.0
    evidence = [
        RatingEvidence(rating=baseline - 1.5, thread_id=t, issue_key=f"t{t}-i1")
        for t in range(1, 9)
    ]
    result = compute_signal_metrics(evidence, baseline=baseline)

    assert result.affinity < 0
    assert result.evidence_count == 8
    assert result.confidence >= 0.6


def test_sparse_negative_evidence_stays_low_confidence() -> None:
    """A single below-baseline issue stays low-confidence."""
    baseline = 3.0
    evidence = [RatingEvidence(rating=baseline - 1.5, thread_id=1, issue_key="t1-i1")]
    result = compute_signal_metrics(evidence, baseline=baseline)
    assert result.affinity < 0
    assert result.confidence < 0.6


def test_correlated_metadata_from_one_issue_does_not_double_count() -> None:
    """Duplicated credits on one issue count as one piece of evidence.

    ``compute_signal_metrics`` deduplicates by ``issue_key``, so two
    ``RatingEvidence`` objects for the same issue_key collapse to one.
    """
    baseline = 3.0
    evidence = [
        RatingEvidence(rating=baseline + 1.5, thread_id=1, issue_key="t1-i1"),
        RatingEvidence(rating=baseline + 1.5, thread_id=1, issue_key="t1-i1"),
    ]
    result = compute_signal_metrics(evidence, baseline=baseline)
    assert result.evidence_count == 1
    assert result.confidence < 0.6


def test_merge_metrics_into_signal_preserves_verdict_columns() -> None:
    """Column updates never include the verdict columns."""
    metrics = SignalMetrics(
        affinity=0.8,
        confidence=0.7,
        evidence_count=5,
        distinct_thread_count=4,
    )
    now = datetime.now(UTC)
    updates = merge_metrics_into_signal(metrics, "Alan Moore", now, is_new=False)

    assert "user_verdict" not in updates
    assert "verdict_at" not in updates
    assert updates["affinity_estimate"] == 0.8
    assert updates["confidence"] == 0.7
    assert updates["evidence_count"] == 5
    assert updates["last_observed_at"] == now


def test_merge_metrics_into_signal_sets_first_observed_only_when_new() -> None:
    """first_observed_at is only set on newly created rows."""
    metrics = SignalMetrics(
        affinity=0.5,
        confidence=0.5,
        evidence_count=2,
        distinct_thread_count=2,
    )
    now = datetime.now(UTC)
    new_updates = merge_metrics_into_signal(metrics, "X", now, is_new=True)
    existing_updates = merge_metrics_into_signal(metrics, "X", now, is_new=False)

    assert "first_observed_at" in new_updates
    assert "first_observed_at" not in existing_updates


def test_mixed_sign_evidence_lowers_confidence() -> None:
    """Opposing evidence directions lower confidence."""
    baseline = 3.0
    evidence = [
        RatingEvidence(rating=baseline + 1.5, thread_id=1, issue_key="t1-i1"),
        RatingEvidence(rating=baseline + 1.5, thread_id=2, issue_key="t2-i1"),
        RatingEvidence(rating=baseline - 1.5, thread_id=3, issue_key="t3-i1"),
        RatingEvidence(rating=baseline - 1.5, thread_id=4, issue_key="t4-i1"),
    ]
    result = compute_signal_metrics(evidence, baseline=baseline)
    assert abs(result.affinity) < 1e-9
    assert result.confidence < 0.6


def test_baseline_rating_function() -> None:
    """baseline_rating computes the arithmetic mean."""
    assert baseline_rating([4.0, 4.0, 3.0, 5.0]) == 4.0


def test_compute_confidence_with_diversity() -> None:
    """Evidence spread across more threads gets higher confidence."""
    low_diversity = compute_confidence(evidence_count=5, distinct_thread_count=1)
    high_diversity = compute_confidence(evidence_count=5, distinct_thread_count=5)
    assert high_diversity > low_diversity


def test_compute_confidence_zero_evidence() -> None:
    """Zero evidence yields zero confidence."""
    assert compute_confidence(evidence_count=0, distinct_thread_count=0) == 0.0
