"""Pure contextual bandwidth weighting for Roll selection.

Phase 3 of the personalized-Roll architecture (issue #1685). These helpers
compute recommendation weights for candidates that are already inside the
die-bounded pool. They never change pool membership: eligibility is decided
upstream, and weighting only redistributes selection probability inside the
existing pool boundary.

Modes:

- ``light``: favor lower-effort candidates for low-bandwidth moments.
- ``deep``: favor higher-effort candidates while never excluding light reads.
- ``balanced`` (and any unknown/absent mode): neutral; callers should keep the
  exact legacy uniform selection path.

Effort bands follow the documented evidence bands from issue #1685:
light reads take under 12 minutes, medium reads 12-18 minutes, and heavy
reads 18 minutes or more. Candidates without a usable effort estimate are
neutral (weight 1.0) so unknown data can never distort selection.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

BANDWIDTH_LIGHT = "light"
BANDWIDTH_BALANCED = "balanced"
BANDWIDTH_DEEP = "deep"

EFFORT_BAND_LIGHT = "light"
EFFORT_BAND_MEDIUM = "medium"
EFFORT_BAND_HEAVY = "heavy"

#: Upper bound (minutes, inclusive) of the light effort band.
LIGHT_EFFORT_MAX_MINUTES = 12.0
#: Lower bound (minutes) of the heavy effort band.
HEAVY_EFFORT_MIN_MINUTES = 18.0

NEUTRAL_WEIGHT = 1.0

REASON_UNKNOWN_EFFORT = "effort_unknown_neutral"
REASON_WEIGHTED_TEMPLATE = "{mode}_mode_{band}_effort"

#: Documented weight table per bandwidth mode and effort band. Every cell is
#: strictly positive so no candidate inside the pool can ever be excluded.
WEIGHTS_BY_MODE_AND_BAND: dict[str, dict[str, float]] = {
    BANDWIDTH_LIGHT: {
        EFFORT_BAND_LIGHT: 3.0,
        EFFORT_BAND_MEDIUM: 2.0,
        EFFORT_BAND_HEAVY: 1.0,
    },
    BANDWIDTH_BALANCED: {
        EFFORT_BAND_LIGHT: 1.0,
        EFFORT_BAND_MEDIUM: 1.0,
        EFFORT_BAND_HEAVY: 1.0,
    },
    BANDWIDTH_DEEP: {
        EFFORT_BAND_LIGHT: 1.0,
        EFFORT_BAND_MEDIUM: 2.0,
        EFFORT_BAND_HEAVY: 3.0,
    },
}


@dataclass(frozen=True)
class WeightedCandidate:
    """One bounded-pool candidate's weight and reason code."""

    position: int
    thread_id: int
    effort_minutes: float | None
    band: str | None
    weight: float
    reason: str


def classify_effort_band(effort_minutes: float | None) -> str | None:
    """Classify an effort estimate into its documented band.

    Args:
        effort_minutes: Estimated reading effort in minutes, or None when unknown.

    Returns:
        One of ``light``, ``medium``, or ``heavy``; None when the estimate is
        missing or invalid so the candidate stays neutral.
    """
    if effort_minutes is None or effort_minutes < 0:
        return None
    if effort_minutes < LIGHT_EFFORT_MAX_MINUTES:
        return EFFORT_BAND_LIGHT
    if effort_minutes < HEAVY_EFFORT_MIN_MINUTES:
        return EFFORT_BAND_MEDIUM
    return EFFORT_BAND_HEAVY


def normalize_bandwidth(bandwidth: str | None) -> str:
    """Normalize a raw bandwidth input to a supported mode.

    Args:
        bandwidth: Raw bandwidth value from session state or API input.

    Returns:
        The unchanged supported value, or ``balanced`` for anything absent or
        unrecognized so unknown modes stay neutral by default.
    """
    if bandwidth in (BANDWIDTH_LIGHT, BANDWIDTH_DEEP):
        return bandwidth
    return BANDWIDTH_BALANCED


def build_candidate_weights(
    efforts: Sequence[tuple[int, float | None]],
    bandwidth: str | None,
) -> list[WeightedCandidate]:
    """Build one weight and reason per bounded-pool candidate.

    Args:
        efforts: Ordered ``(thread_id, effort_minutes)`` pairs for every
            candidate inside the die-bounded pool, in pool order.
        bandwidth: Requested bandwidth mode. ``light`` and ``deep`` weight by
            effort band; anything else yields neutral weights.

    Returns:
        A :class:`WeightedCandidate` per input entry, preserving order.
    """
    mode = normalize_bandwidth(bandwidth)
    table = WEIGHTS_BY_MODE_AND_BAND[mode]

    candidates: list[WeightedCandidate] = []
    for position, (thread_id, effort_minutes) in enumerate(efforts):
        band = classify_effort_band(effort_minutes)
        if band is None:
            candidates.append(
                WeightedCandidate(
                    position=position,
                    thread_id=thread_id,
                    effort_minutes=effort_minutes,
                    band=None,
                    weight=NEUTRAL_WEIGHT,
                    reason=REASON_UNKNOWN_EFFORT,
                )
            )
            continue

        candidates.append(
            WeightedCandidate(
                position=position,
                thread_id=thread_id,
                effort_minutes=effort_minutes,
                band=band,
                weight=table[band],
                reason=REASON_WEIGHTED_TEMPLATE.format(mode=mode, band=band),
            )
        )
    return candidates


def choose_weighted_index(weights: Sequence[float], rng: random.Random) -> int:
    """Select one index with probability proportional to its weight.

    Args:
        weights: Positive weights, one per bounded-pool candidate.
        rng: Seeded random source used for reproducible regression tests.

    Returns:
        The selected candidate index inside ``range(len(weights))``.

    Raises:
        ValueError: If weights are empty or their sum is not positive.
    """
    if not weights:
        raise ValueError("Cannot select from an empty candidate list")

    total = sum(weights)
    if total <= 0:
        raise ValueError("Candidate weights must sum to a positive value")

    point = rng.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if point < cumulative:
            return index
    return len(weights) - 1
