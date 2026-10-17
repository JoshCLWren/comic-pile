"""Pure bandwidth recommendation weighting for Roll candidates.

Phase 3 of the personalized-Roll architecture (issue #1685, ticket #1712).
This module converts the active session bandwidth plus per-candidate
reading-effort estimates into transparent, bounded recommendation weights.

Contract:

- Pure and deterministic: no database, clock, randomness, or I/O. The same
  inputs always produce identical outputs.
- Inputs are only candidate facts (``thread_id`` plus an optional effort
  estimate in minutes) and the session bandwidth label.
- ``balanced`` (and any absent/unrecognized bandwidth) returns neutral,
  equal weighting so the legacy unweighted selection path is preserved.
- Unknown or invalid effort estimates stay exactly neutral so missing data
  can never distort selection.
- ``light`` favors lower-effort candidates monotonically; ``deep`` mildly
  favors higher-effort candidates while never excluding light reads.
- Weight ranges/caps live in one centralized table and are strictly
  positive, so contextual weighting redistributes probability only inside
  the existing die-bounded pool and can never erase the affinity/die model.

Effort bands follow the documented evidence bands from issue #1685: light
reads take under 12 minutes, medium reads 12-18 minutes, and heavy reads
18 minutes or more.

No endpoint consumes these weights yet; selection integration arrives with
the later Phase 3 tickets (#1714, #1715, #1717, #1718).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

BANDWIDTH_LIGHT = "light"
BANDWIDTH_BALANCED = "balanced"
BANDWIDTH_DEEP = "deep"

#: Every supported bandwidth label, in canonical order.
ALL_BANDWIDTHS: tuple[str, ...] = (BANDWIDTH_LIGHT, BANDWIDTH_BALANCED, BANDWIDTH_DEEP)

EFFORT_BAND_LIGHT = "light"
EFFORT_BAND_MEDIUM = "medium"
EFFORT_BAND_HEAVY = "heavy"

#: Exclusive upper bound (minutes) of the light effort band.
LIGHT_EFFORT_MAX_MINUTES = 12.0
#: Inclusive lower bound (minutes) of the heavy effort band.
HEAVY_EFFORT_MIN_MINUTES = 18.0

#: Weight assigned to neutral candidates; also the balanced-mode weight.
NEUTRAL_WEIGHT = 1.0

#: Reason code for candidates without a usable effort estimate.
REASON_UNKNOWN_EFFORT = "effort_unknown_neutral"
#: Reason code for every candidate under balanced (or unrecognized) bandwidth.
REASON_BALANCED_NEUTRAL = "bandwidth_balanced_neutral"
REASON_LIGHT_FAVORS_LOW_EFFORT = "bandwidth_light_favors_low_effort"
REASON_LIGHT_MEDIUM_NEUTRAL = "bandwidth_light_medium_effort_neutral"
REASON_LIGHT_DAMPENS_HIGH_EFFORT = "bandwidth_light_dampens_high_effort"
REASON_DEEP_DAMPENS_LOW_EFFORT = "bandwidth_deep_dampens_low_effort"
REASON_DEEP_MEDIUM_NEUTRAL = "bandwidth_deep_medium_effort_neutral"
REASON_DEEP_PERMITS_HIGH_EFFORT = "bandwidth_deep_permits_high_effort"

#: Centralized weight caps per bandwidth mode and effort band. Every cell is
#: strictly positive so no candidate inside the die pool is ever excluded,
#: and the maximum spread stays modest (2x for light mode, ~1.4x for deep)
#: so context can never erase the existing affinity/die model. Light mode
#: decreases monotonically with effort; deep mode increases monotonically
#: but gently, because deep bandwidth permits high effort rather than
#: demanding it.
WEIGHTS_BY_MODE_AND_BAND: dict[str, dict[str, float]] = {
    BANDWIDTH_LIGHT: {
        EFFORT_BAND_LIGHT: 1.5,
        EFFORT_BAND_MEDIUM: NEUTRAL_WEIGHT,
        EFFORT_BAND_HEAVY: 0.75,
    },
    BANDWIDTH_BALANCED: {
        EFFORT_BAND_LIGHT: NEUTRAL_WEIGHT,
        EFFORT_BAND_MEDIUM: NEUTRAL_WEIGHT,
        EFFORT_BAND_HEAVY: NEUTRAL_WEIGHT,
    },
    BANDWIDTH_DEEP: {
        EFFORT_BAND_LIGHT: 0.9,
        EFFORT_BAND_MEDIUM: NEUTRAL_WEIGHT,
        EFFORT_BAND_HEAVY: 1.25,
    },
}

#: Reason codes aligned cell-for-cell with :data:`WEIGHTS_BY_MODE_AND_BAND`
#: so every applied weight carries an explanation for later snapshots.
REASONS_BY_MODE_AND_BAND: dict[str, dict[str, str]] = {
    BANDWIDTH_LIGHT: {
        EFFORT_BAND_LIGHT: REASON_LIGHT_FAVORS_LOW_EFFORT,
        EFFORT_BAND_MEDIUM: REASON_LIGHT_MEDIUM_NEUTRAL,
        EFFORT_BAND_HEAVY: REASON_LIGHT_DAMPENS_HIGH_EFFORT,
    },
    BANDWIDTH_BALANCED: {
        EFFORT_BAND_LIGHT: REASON_BALANCED_NEUTRAL,
        EFFORT_BAND_MEDIUM: REASON_BALANCED_NEUTRAL,
        EFFORT_BAND_HEAVY: REASON_BALANCED_NEUTRAL,
    },
    BANDWIDTH_DEEP: {
        EFFORT_BAND_LIGHT: REASON_DEEP_DAMPENS_LOW_EFFORT,
        EFFORT_BAND_MEDIUM: REASON_DEEP_MEDIUM_NEUTRAL,
        EFFORT_BAND_HEAVY: REASON_DEEP_PERMITS_HIGH_EFFORT,
    },
}


@dataclass(frozen=True)
class WeightedCandidate:
    """One die-bounded candidate's recommendation weight and reason code.

    Attributes:
        position: Candidate index inside the bounded pool, preserving input order.
        thread_id: Identifier of the candidate thread.
        effort_minutes: Estimated reading effort in minutes, or None when unknown.
        band: Classified effort band, or None when the estimate is unusable.
        weight: Positive recommendation weight used for in-pool redistribution.
        reasons: Reason codes explaining why the weight was applied.
    """

    position: int
    thread_id: int
    effort_minutes: float | None
    band: str | None
    weight: float
    reasons: tuple[str, ...]


def classify_effort_band(effort_minutes: float | None) -> str | None:
    """Classify a reading-effort estimate into its documented band.

    Args:
        effort_minutes: Estimated reading effort in minutes, or None when unknown.

    Returns:
        One of ``light``, ``medium``, or ``heavy``, or None when the estimate is
        missing or invalid (negative or non-finite) so the candidate stays neutral.
    """
    if effort_minutes is None or not math.isfinite(effort_minutes) or effort_minutes < 0:
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
        unrecognized, so unknown modes default to neutral legacy weighting.
    """
    if bandwidth in (BANDWIDTH_LIGHT, BANDWIDTH_DEEP, BANDWIDTH_BALANCED):
        return bandwidth
    return BANDWIDTH_BALANCED


def build_candidate_weights(
    efforts: Sequence[tuple[int, float | None]],
    bandwidth: str | None,
) -> list[WeightedCandidate]:
    """Build one bounded weight and reason per die-pool candidate.

    Args:
        efforts: Ordered ``(thread_id, effort_minutes)`` pairs for every
            candidate inside the die-bounded pool, in pool order.
        bandwidth: Active session bandwidth label. ``light`` and ``deep``
            weight candidates by effort band; anything else yields neutral
            weights. Unknown or invalid effort estimates always stay neutral.

    Returns:
        A :class:`WeightedCandidate` per input entry, preserving input order.
    """
    mode = normalize_bandwidth(bandwidth)
    weights = WEIGHTS_BY_MODE_AND_BAND[mode]
    reasons = REASONS_BY_MODE_AND_BAND[mode]

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
                    reasons=(REASON_UNKNOWN_EFFORT,),
                )
            )
            continue

        candidates.append(
            WeightedCandidate(
                position=position,
                thread_id=thread_id,
                effort_minutes=effort_minutes,
                band=band,
                weight=weights[band],
                reasons=(reasons[band],),
            )
        )
    return candidates
