"""Cautious Taste Bank inference from reading history (issue #1745).

Derives per-feature affinity and confidence from a reader's confirmed
ratings instead of silently equating one good comic with a permanent creator
preference. Every function here is pure and deterministic: given the same
evidence it always produces the same metrics, so the Taste Bank stays
rebuildable from raw rating history.

Design goals from the issue contract:

- **Baseline-relative affinity**: A feature's affinity is measured against the
  reader's own average rating, in normalized effect units, so a middling 3/5
  is not mistaken for a positive signal for a reader whose baseline is also 3.
- **Sparse evidence stays weak**: Confidence grows slowly with distinct issue
  evidence and is further discounted for single-thread clusters, so one or two
  isolated issues remain low-confidence.
- **No intra-issue double counting**: Each distinct issue contributes at most
  one observation per feature, even when highly correlated metadata points to
  the same underlying person or team.
- **Verdicts are authoritative**: Recomputation updates only inferred columns;
  an explicit user verdict is never overwritten.

The prompt-eligibility engine (``app.services.prompt_eligibility``) decides
whether an inferred metric is strong enough to ask about. This module only
produces the metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.taste_signal import TasteSignal

# Confidence curve: effective-sample smoothing so sparse evidence stays weak
# while repeated evidence trends toward 1.0.
_CONFIDENCE_SMOOTHING = 2.0

# Diversity weight: how much an additional distinct thread boosts the
# effective sample relative to reading more issues from the same thread.
_DIVERSITY_BOOST = 0.25


class InferenceError(ValueError):
    """Raised when inference input is malformed (e.g. empty evidence)."""


@dataclass(frozen=True)
class RatingEvidence:
    """One rating observation for a feature from a single read.

    Attributes:
        rating: The reader's rating for the read (scale-relative).
        thread_id: Database id of the reading-project thread for the read.
        issue_key: Stable key identifying one distinct issue within a thread,
            used to prevent intra-issue double counting.
    """

    rating: float
    thread_id: int
    issue_key: str


@dataclass(frozen=True)
class SignalMetrics:
    """Inferred metrics for one taste signal.

    Attributes:
        affinity: Baseline-relative effect size normalized to ``[-1, 1]``;
            positive means the reader rated the feature above their own
            baseline.
        confidence: Statistical confidence in the affinity estimate in
            ``[0, 1]``, growing with evidence count and diversity.
        evidence_count: Number of distinct issues contributing evidence.
        distinct_thread_count: Number of distinct threads contributing.
    """

    affinity: float
    confidence: float
    evidence_count: int
    distinct_thread_count: int


def _mean(values: list[float]) -> float:
    """Return the arithmetic mean of ``values``.

    Args:
        values: Non-empty list of numbers.

    Returns:
        The mean.

    Raises:
        InferenceError: When ``values`` is empty.
    """
    if not values:
        raise InferenceError("cannot compute a mean over empty evidence")
    return sum(values) / len(values)


def baseline_rating(all_ratings: list[float]) -> float:
    """Return a reader's overall baseline rating across confirmed reads.

    Args:
        all_ratings: Every confirmed rating the reader has given, across all
            features and threads.

    Returns:
        The reader's average baseline rating.

    Raises:
        InferenceError: When ``all_ratings`` is empty.
    """
    return _mean(list(all_ratings))


def _dedupe_evidence(evidence: list[RatingEvidence]) -> list[RatingEvidence]:
    """Drop repeat observations of the same distinct issue for one feature.

    One issue contributes a single rating observation per feature; any extra
    observations carry no independent signal and would double-count correlated
    metadata.

    Args:
        evidence: Raw per-read observations for one feature.

    Returns:
        One observation per distinct ``issue_key``, preserving first-seen
        order.
    """
    seen: set[str] = set()
    deduped: list[RatingEvidence] = []
    for observation in evidence:
        if observation.issue_key in seen:
            continue
        seen.add(observation.issue_key)
        deduped.append(observation)
    return deduped


def compute_confidence(evidence_count: int, distinct_thread_count: int) -> float:
    """Compute a confidence score from evidence count and diversity.

    Uses a Laplace-style effective-sample smoothing: confidence equals
    ``effective / (effective + smoothing)``. The effective sample grows with
    evidence count and is boosted modestly by evidence drawn from more distinct
    threads, so a single-thread cluster stays less confident than a spread of
    reads.

    Args:
        evidence_count: Distinct issues contributing evidence.
        distinct_thread_count: Distinct threads contributing evidence.

    Returns:
        A confidence value in ``[0, 1]``.
    """
    if evidence_count <= 0:
        return 0.0
    boost = max(0, distinct_thread_count - 1) * _DIVERSITY_BOOST
    effective = evidence_count * (1.0 + boost)
    raw = effective / (effective + _CONFIDENCE_SMOOTHING)
    return max(0.0, min(1.0, raw))


def compute_signal_metrics(
    evidence: list[RatingEvidence],
    *,
    baseline: float,
    rating_span: float = 4.0,
) -> SignalMetrics:
    """Infer affinity, confidence, and evidence metadata for one feature.

    Args:
        evidence: Per-read rating observations for the feature. May contain
            duplicates for the same distinct issue; they are deduplicated.
        baseline: The reader's global average rating from
            :func:`baseline_rating`.
        rating_span: Width of the rating scale (max minus min) used to
            normalize affinity. Defaults to 4 for a 1-5 star scale.

    Returns:
        The inferred :class:`SignalMetrics`.

    Raises:
        InferenceError: When ``evidence`` is empty after deduplication, or
            ``rating_span`` is not positive.

    Examples:
        Repeated above-baseline evidence yields a confident, positive signal::

            >>> compute_signal_metrics(
            ...     [RatingEvidence(4, 1, "a"), RatingEvidence(4, 2, "b"),
            ...      RatingEvidence(4, 3, "c")],
            ...     baseline=3.0,
            ... ).confidence > 0.6
            True

        A single isolated above-baseline read stays low-confidence::

            >>> compute_signal_metrics(
            ...     [RatingEvidence(4, 1, "a")],
            ...     baseline=3.0,
            ... ).confidence < 0.6
            True
    """
    if rating_span <= 0:
        raise InferenceError("rating_span must be positive")

    deduped = _dedupe_evidence(evidence)
    if not deduped:
        raise InferenceError("cannot infer metrics from empty evidence")

    feature_mean = _mean([observation.rating for observation in deduped])
    raw_affinity = (feature_mean - baseline) / rating_span
    affinity = max(-1.0, min(1.0, raw_affinity))

    evidence_count = len(deduped)
    distinct_thread_count = len({observation.thread_id for observation in deduped})

    return SignalMetrics(
        affinity=affinity,
        confidence=compute_confidence(evidence_count, distinct_thread_count),
        evidence_count=evidence_count,
        distinct_thread_count=distinct_thread_count,
    )


def merge_inferred_into(
    signal: TasteSignal,
    metrics: SignalMetrics,
    *,
    now: datetime,
) -> TasteSignal:
    """Merge freshly inferred metrics onto a durable signal row.

    Only the inferred columns (``affinity_estimate``, ``confidence``,
    ``evidence_count``, ``distinct_thread_count``) and observation timestamps
    are updated. An explicit ``user_verdict`` is authoritative and is never
    overwritten by recomputation.

    Args:
        signal: The durable ORM signal to update in place.
        metrics: Freshly computed inference metrics.
        now: Timezone-aware UTC timestamp recording the recomputation.

    Returns:
        The updated signal (the same object, mutated in place).
    """
    signal.affinity_estimate = metrics.affinity
    signal.confidence = metrics.confidence
    signal.evidence_count = metrics.evidence_count
    signal.distinct_thread_count = metrics.distinct_thread_count
    if signal.first_observed_at is None:
        signal.first_observed_at = now
    signal.last_observed_at = now
    return signal


__all__ = [
    "InferenceError",
    "RatingEvidence",
    "SignalMetrics",
    "baseline_rating",
    "compute_confidence",
    "compute_signal_metrics",
    "merge_inferred_into",
]
