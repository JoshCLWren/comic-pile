"""Pure validator/classifier for reading-effort duration observations.

This is the Phase 1 observation-rules module for issue #1701.  It defines
conservative, centralized thresholds for deciding which roll → rate
elapsed-duration observations are trustworthy enough to feed into later
effort-estimate aggregation.

Key design constraints (from the issue contract):
- Filtering is applied to derived observations only; raw event history is
  never rewritten or deleted.
- Thresholds are centralized and configurable, not scattered through query
  code.
- Every excluded observation carries a documented reason code so analysis
  remains explainable.
- No recommendation behavior is changed by this module.

Usage example:
    from comic_pile.reading_effort_observation_rules import (
        classify_reading_effort_observation,
        DurationObservation,
    )

    result = classify_reading_effort_observation(
        DurationObservation(duration_seconds=5.0)
    )
    assert result.included is False
    assert result.reason_code == "too_short"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Centralized, configurable thresholds
# ---------------------------------------------------------------------------

DEFAULT_MIN_DURATION_SECONDS: float = 30.0  # suspiciously short / instant-marking reads
DEFAULT_MAX_DURATION_SECONDS: float = 14400.0  # extreme abandoned-tab durations (4 hours)


@dataclass(frozen=True, slots=True)
class ObservationThresholds:
    """Centralized threshold configuration for valid reading-effort observations.

    All defaults are conservative and documented so they are not scattered
    through query or aggregation code.

    Attributes:
        min_duration_seconds: Shortest trustworthy elapsed duration (exclusive
            lower bound for exclusion; observations exactly at this value are
            still considered valid because the boundary is inclusive).
        max_duration_seconds: Longest trustworthy elapsed duration (inclusive
            upper bound; observations above this value are excluded as extreme
            outliers / abandoned tabs).
    """

    min_duration_seconds: float = DEFAULT_MIN_DURATION_SECONDS
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS


# ---------------------------------------------------------------------------
# Observation model (pure data, no DB dependency)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DurationObservation:
    """One elapsed-duration observation derived from a linked roll → rate pair.

    This is a derived-model structure: it carries the measured duration plus
    optional provenance fields so that exclusions remain explainable without
    re-opening raw event records.

    Attributes:
        duration_seconds: Elapsed time between the originating roll event and
            its linked rate event, in seconds.
        roll_event_id: Optional provenance reference to the originating roll.
        rate_event_id: Optional provenance reference to the linked rate.
        thread_id: Optional thread reference for explainability.
    """

    duration_seconds: float
    roll_event_id: int | None = None
    rate_event_id: int | None = None
    thread_id: int | None = None


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

ReasonCode = Literal[
    "too_short",
    "too_long",
]


@dataclass(frozen=True, slots=True)
class ObservationResult:
    """Result of classifying a single duration observation.

    Attributes:
        observation: The original observation passed to the classifier (never
            mutated or rewritten).
        included: ``True`` when the observation passes conservative filters and
            should be retained for effort-estimate aggregation.
        reason_code: A documented exclusion reason when ``included`` is
            ``False``; always ``None`` when ``included`` is ``True``.
    """

    observation: DurationObservation
    included: bool
    reason_code: ReasonCode | None = None


# ---------------------------------------------------------------------------
# Pure classifier
# ---------------------------------------------------------------------------


def classify_reading_effort_observation(
    observation: DurationObservation,
    thresholds: ObservationThresholds | None = None,
) -> ObservationResult:
    """Classify a single elapsed-duration observation against conservative rules.

    The classifier does not rewrite, delete, or alter the underlying event
    records; it only produces a derived ``ObservationResult`` that downstream
    aggregation can use to decide whether to include the observation.

    Boundary behavior:
    - ``duration_seconds < thresholds.min_duration_seconds`` → excluded,
      reason ``"too_short"``.
    - ``duration_seconds > thresholds.max_duration_seconds`` → excluded,
      reason ``"too_long"``.
    - Otherwise → included, ``reason_code=None``.

    Args:
        observation: The derived duration observation to evaluate.
        thresholds: Optional override of the default conservative bounds.  When
            ``None``, ``ObservationThresholds()`` defaults are used.

    Returns:
        An ``ObservationResult`` describing whether the observation is valid
        and, if excluded, the reason code.
    """
    if thresholds is None:
        thresholds = ObservationThresholds()

    if observation.duration_seconds < thresholds.min_duration_seconds:
        return ObservationResult(
            observation=observation,
            included=False,
            reason_code="too_short",
        )

    if observation.duration_seconds > thresholds.max_duration_seconds:
        return ObservationResult(
            observation=observation,
            included=False,
            reason_code="too_long",
        )

    return ObservationResult(
        observation=observation,
        included=True,
        reason_code=None,
    )


def classify_reading_effort_observations(
    observations: list[DurationObservation],
    thresholds: ObservationThresholds | None = None,
) -> list[ObservationResult]:
    """Classify multiple observations independently.

    This is a pure mapping: no side effects, no mutation of input observations,
    and no database interaction.  Each result retains a reference to its
    original observation so that explainability remains intact.

    Args:
        observations: A list of derived duration observations.
        thresholds: Optional threshold override.

    Returns:
        A list of ``ObservationResult`` values in the same order as the input.
    """
    return [
        classify_reading_effort_observation(obs, thresholds) for obs in observations
    ]
