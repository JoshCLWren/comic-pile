"""Robust reading-effort estimation over validated linked duration observations.

Phase 1 of the reading-effort model (issue #1702). This module is pure and
read-only: it consumes already-validated roll-to-rate duration observations
(the output contract of the latency derivation in #1700 and the observation
validity rules in #1701) and derives deterministic per-thread and per-issue
median effort estimates suitable for later Roll weighting.

Design guarantees:

- Medians only. Arithmetic means are deliberately avoided so a single extreme
  duration cannot dominate an estimate.
- Determinism. Identical observation multisets always produce identical
  estimates regardless of iteration order.
- Honest confidence. Every estimate exposes its sample count, its source pool,
  and whether it met the documented minimum sample size. Sparse history never
  masquerades as trusted knowledge.
- Safe fallback. Issue-specific estimates are preferred once they have enough
  evidence; otherwise thread-level history is used. Neither level invents
  certainty the underlying observations cannot support.

Outliers excluded by the observation rules (#1701) never reach this module, so
they cannot affect any estimate by construction. This module never mutates
events, never queries the database, and never influences candidate selection.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

DEFAULT_MIN_TRUSTED_SAMPLE_COUNT = 3
"""Minimum observations required before an estimate may be labeled observed.

Three independent readings are the smallest pool where a median reflects a
central tendency instead of echoing a single session. Callers may override the
threshold explicitly, but the default is the documented product gate.
"""


class EffortSource(StrEnum):
    """Which history pool produced an effort estimate."""

    ISSUE = "issue"
    THREAD = "thread"


@dataclass(frozen=True, slots=True)
class EffortObservation:
    """One validated reading-effort duration observation.

    Instances represent trustworthy roll-to-rate durations only. Observations
    rejected by the Phase 1 validity rules must be excluded upstream; passing
    them here violates the input contract this module is built on.

    Attributes:
        thread_id: Identifier of the thread (series) that was read.
        issue_id: Identifier of the specific issue that was read, or ``None``
            for legacy observations recorded before issue linkage existed.
        duration_seconds: Elapsed seconds between the originating roll event
            and its linked rate event. Must be finite and non-negative.
    """

    thread_id: int
    issue_id: int | None
    duration_seconds: float

    def __post_init__(self) -> None:
        """Reject identifiers and durations that cannot describe a real read.

        Raises:
            ValueError: If identifiers are not positive or the duration is
                negative or non-finite.
        """
        if self.thread_id <= 0:
            raise ValueError(f"thread_id must be positive, got {self.thread_id}")
        if self.issue_id is not None and self.issue_id <= 0:
            raise ValueError(f"issue_id must be positive, got {self.issue_id}")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError(
                f"duration_seconds must be finite and non-negative, got {self.duration_seconds}"
            )


@dataclass(frozen=True, slots=True)
class EffortEstimate:
    """A robust median reading-effort estimate for one aggregation pool.

    Attributes:
        median_seconds: Deterministic median duration of the pool in seconds.
        sample_count: Number of observations behind the median.
        source: Which history pool produced the estimate.
        trusted: Whether ``sample_count`` met the documented minimum sample
            size. Untrusted estimates are reported for transparency only and
            must not be treated as established reading effort.
    """

    median_seconds: float
    sample_count: int
    source: EffortSource
    trusted: bool

    @property
    def confidence(self) -> Literal["observed", "sparse"]:
        """Label the estimate ``observed`` or ``sparse`` based on sample size."""
        return "observed" if self.trusted else "sparse"


@dataclass(frozen=True, slots=True)
class EffortSummary:
    """Per-thread and per-issue robust effort aggregates for one dataset.

    Attributes:
        threads: Median effort estimate per thread identifier, keyed in sorted
            order. Includes sparse pools so callers can inspect evidence size.
        issues: Median effort estimate per issue identifier, keyed in sorted
            order. Observations without issue linkage contribute only to the
            thread pools.
    """

    threads: dict[int, EffortEstimate]
    issues: dict[int, EffortEstimate]


def median(values: Sequence[float]) -> float:
    """Return the deterministic median of the given durations.

    Odd-sized inputs return the middle value; even-sized inputs average the
    two middle values. Input order never affects the result.

    Args:
        values: Duration samples in seconds. Must contain at least one value.

    Returns:
        The median duration in seconds.

    Raises:
        ValueError: If ``values`` is empty.
    """
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        raise ValueError("median requires at least one value")
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _estimate_pool(
    samples: Sequence[float],
    *,
    source: EffortSource,
    min_trusted_sample_count: int,
) -> EffortEstimate:
    """Build one pool estimate with honest confidence labeling.

    Args:
        samples: Duration samples belonging to a single pool.
        source: Which history pool the samples came from.
        min_trusted_sample_count: Minimum sample size for a trusted label.

    Returns:
        The median estimate for the pool.
    """
    return EffortEstimate(
        median_seconds=median(samples),
        sample_count=len(samples),
        source=source,
        trusted=len(samples) >= min_trusted_sample_count,
    )


def aggregate_efforts(
    observations: Iterable[EffortObservation],
    *,
    min_trusted_sample_count: int = DEFAULT_MIN_TRUSTED_SAMPLE_COUNT,
) -> EffortSummary:
    """Aggregate validated observations into robust per-thread/per-issue pools.

    Each pool is summarized independently with a median, its sample count, and
    whether it reached the documented minimum sample size. Repeated valid reads
    of the same issue are intentional evidence and all participate.

    Args:
        observations: Validated effort observations. Iteration order does not
            affect any resulting estimate.
        min_trusted_sample_count: Minimum observations required before a pool
            is labeled trusted.

    Returns:
        Thread-keyed and issue-keyed estimate indexes. Both are empty when no
        observations are supplied.

    Raises:
        ValueError: If ``min_trusted_sample_count`` is below one.
    """
    if min_trusted_sample_count < 1:
        raise ValueError(
            f"min_trusted_sample_count must be at least 1, got {min_trusted_sample_count}"
        )

    thread_samples: dict[int, list[float]] = {}
    issue_samples: dict[int, list[float]] = {}
    for observation in observations:
        thread_samples.setdefault(observation.thread_id, []).append(
            observation.duration_seconds
        )
        if observation.issue_id is not None:
            issue_samples.setdefault(observation.issue_id, []).append(
                observation.duration_seconds
            )

    return EffortSummary(
        threads={
            thread_id: _estimate_pool(
                samples,
                source=EffortSource.THREAD,
                min_trusted_sample_count=min_trusted_sample_count,
            )
            for thread_id, samples in sorted(thread_samples.items())
        },
        issues={
            issue_id: _estimate_pool(
                samples,
                source=EffortSource.ISSUE,
                min_trusted_sample_count=min_trusted_sample_count,
            )
            for issue_id, samples in sorted(issue_samples.items())
        },
    )


def resolve_issue_effort(
    *,
    summary: EffortSummary,
    issue_id: int,
    thread_id: int,
) -> EffortEstimate | None:
    """Resolve the best available effort estimate for one specific issue.

    Preference order:

    1. A trusted issue-specific estimate (enough evidence for this exact
       issue).
    2. A trusted thread-level estimate (the safe fallback when issue history
       is sparse but the series history is established).
    3. The sparse issue-specific pool, when it holds any evidence at all,
       because readings of this exact issue remain the most relevant signal.
    4. The sparse thread-level pool.
    5. ``None`` when neither history contains anything usable.

    Steps 3 and 4 return untrusted estimates so downstream consumers can see
    the evidence without mistaking sparse history for certainty.

    Args:
        summary: Aggregated effort indexes for the dataset.
        issue_id: Identifier of the target issue.
        thread_id: Identifier of the thread containing the target issue.

    Returns:
        The resolved estimate, or ``None`` when no related history exists.
    """
    issue_estimate = summary.issues.get(issue_id)
    thread_estimate = summary.threads.get(thread_id)

    if issue_estimate is not None and issue_estimate.trusted:
        return issue_estimate
    if thread_estimate is not None and thread_estimate.trusted:
        return thread_estimate
    if issue_estimate is not None:
        return issue_estimate
    if thread_estimate is not None:
        return thread_estimate
    return None


def estimate_issue_effort(
    observations: Iterable[EffortObservation],
    *,
    issue_id: int,
    thread_id: int,
    min_trusted_sample_count: int = DEFAULT_MIN_TRUSTED_SAMPLE_COUNT,
) -> EffortEstimate | None:
    """Estimate reading effort for one issue using the full preference chain.

    Convenience entry point combining :func:`aggregate_efforts` and
    :func:`resolve_issue_effort` for callers that hold a flat observation set.

    Args:
        observations: Validated effort observations.
        issue_id: Identifier of the target issue.
        thread_id: Identifier of the thread containing the target issue.
        min_trusted_sample_count: Minimum observations required before a pool
            is labeled trusted.

    Returns:
        The resolved estimate, or ``None`` when no related history exists.
    """
    return resolve_issue_effort(
        summary=aggregate_efforts(
            observations,
            min_trusted_sample_count=min_trusted_sample_count,
        ),
        issue_id=issue_id,
        thread_id=thread_id,
    )
