"""Pure Snooze-to-bandwidth correction logic.

Deterministic, side-effect-free service that interprets a Snooze as evidence
about the reader's current session bandwidth. The correction result is applied
by the Snooze endpoint to ephemeral session state; this module never touches
durable queue affinity.

Issue: #1723 (pure correction contract), consumed by #1724.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class BandwidthLevel(StrEnum):
    """Session bandwidth levels ordered from least to most mentally demanding."""

    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"


class CorrectionReason(StrEnum):
    """Compact reason codes explaining why a correction did or did not apply."""

    HEAVY_SNOOZE_SHIFT = "heavy_snooze_shift"
    LIGHT_SNOOZE_DEFLATE = "light_snooze_deflate"
    CONFIDENCE_DEGRADE = "confidence_degrade"
    CLARIFICATION_NEEDED = "clarification_needed"


_BANDWIDTH_ORDER: dict[str, int] = {
    BandwidthLevel.LIGHT.value: 0,
    BandwidthLevel.BALANCED.value: 1,
    BandwidthLevel.DEEP.value: 2,
}

# Confidence adjustments per outcome. Mode shifts confirm the signal slightly;
# ambiguous or contradictory evidence increases uncertainty instead.
_SHIFT_CONFIDENCE_BUMP = 0.05
_LIGHT_SNOOZE_PENALTY = 0.10
_AMBIGUOUS_PENALTY = 0.05
_CONTRADICTION_PENALTY = 0.15

# Consecutive snoozes (including the current one) after which a direction flip
# is treated as contradictory evidence that should request clarification.
_CONTRADICTION_MIN_SNOOZES = 3

_VALID_DIRECTIONS = frozenset({"heavier", "lighter"})


@dataclass(frozen=True, slots=True)
class SnoozeCorrectionResult:
    """Proposed bandwidth transition plus compact reason codes.

    Attributes:
        active_bandwidth: Proposed active bandwidth after the correction.
        active_confidence: Confidence in the proposed bandwidth (0.0-1.0).
        bandwidth_changed: Whether the bandwidth level changed level.
        reason_code: Compact reason code explaining the proposal.
        suggest_clarification: Whether repeated contradictory snoozes indicate
            the reader should be asked to clarify their mode.
        applies: Whether the caller should write any session state. When False
            the proposal is an exact no-op and the caller must leave the
            session untouched.
        direction: Evidence direction of this snooze relative to the active
            bandwidth ("heavier", "lighter", or None when equal or unknown).
    """

    active_bandwidth: str
    active_confidence: float
    bandwidth_changed: bool
    reason_code: str
    suggest_clarification: bool
    applies: bool
    direction: str | None


def normalize_bandwidth(level: str | None) -> str:
    """Return a valid bandwidth level, defaulting unknown values to balanced.

    Args:
        level: Raw bandwidth value from session state, or None.

    Returns:
        One of the canonical BandwidthLevel string values.
    """
    if level in _BANDWIDTH_ORDER:
        return level
    return BandwidthLevel.BALANCED.value


def classify_candidate_effort(
    effort_source: str | None,
    effort_minutes: float | None,
) -> str | None:
    """Classify a snoozed candidate's effort into a bandwidth level.

    Intentionally coarse mapping so richer Phase 1 effort modeling can replace
    the inputs without changing this contract.

    Args:
        effort_source: Provenance of the estimate ("observed",
            "publication_era"), or None/"none" when no evidence exists.
        effort_minutes: Estimated reading time in minutes, or None.

    Returns:
        "light" (under 12 minutes), "balanced" (12-19), "deep" (20+), or None
        when no usable evidence is available.
    """
    if effort_source is None or effort_source == "none" or effort_minutes is None:
        return None
    if not math.isfinite(effort_minutes) or effort_minutes < 0:
        return None
    if effort_minutes < 12:
        return BandwidthLevel.LIGHT.value
    if effort_minutes < 20:
        return BandwidthLevel.BALANCED.value
    return BandwidthLevel.DEEP.value


def _clamp_confidence(value: float) -> float:
    """Clamp a confidence value to the valid 0.0-1.0 range."""
    if not math.isfinite(value):
        return 0.5
    return min(max(value, 0.0), 1.0)


def compute_snooze_correction(
    *,
    current_bandwidth: str | None,
    current_confidence: float | None,
    candidate_effort_level: str | None,
    consecutive_snoozes: int,
    last_snooze_direction: str | None,
) -> SnoozeCorrectionResult:
    """Compute the proposed bandwidth correction for one Snooze event.

    Conservative rules:

    - Snoozing a clearly heavy (``deep`` effort) candidate shifts one step
      lighter unless already at ``light``.
    - Snoozing a light candidate never invents extra demand; it only lowers
      confidence.
    - Equal-effort or unknown-effort snoozes lower confidence without forcing
      a mode change.
    - Repeated contradictory snoozes increase uncertainty and request
      clarification rather than oscillating the mode forever.

    Args:
        current_bandwidth: Active session bandwidth, or None for unset state.
        current_confidence: Confidence in the active bandwidth (0.0-1.0), or
            None for unset state.
        candidate_effort_level: Classified effort of the snoozed candidate
            ("light"/"balanced"/"deep"), or None when unknown.
        consecutive_snoozes: Snoozes in this run including the current one.
        last_snooze_direction: Direction of the previous snooze in this run
            ("heavier"/"lighter"), or None when this is the first.

    Returns:
        A deterministic SnoozeCorrectionResult proposal.
    """
    active = normalize_bandwidth(current_bandwidth)
    confidence = _clamp_confidence(current_confidence if current_confidence is not None else 0.5)
    active_idx = _BANDWIDTH_ORDER[active]
    candidate_idx = _BANDWIDTH_ORDER.get(candidate_effort_level or "", active_idx)

    if candidate_effort_level is None or candidate_idx == active_idx:
        direction: str | None = None
    elif candidate_idx > active_idx:
        direction = "heavier"
    else:
        direction = "lighter"

    def _result(
        *,
        bandwidth: str,
        conf: float,
        changed: bool,
        reason: str,
        clarification: bool,
    ) -> SnoozeCorrectionResult:
        applies = changed or not math.isclose(conf, confidence)
        return SnoozeCorrectionResult(
            active_bandwidth=bandwidth,
            active_confidence=_clamp_confidence(conf),
            bandwidth_changed=changed,
            reason_code=reason,
            suggest_clarification=clarification,
            applies=applies,
            direction=direction,
        )

    contradicts_last = (
        direction is not None
        and last_snooze_direction in _VALID_DIRECTIONS
        and direction != last_snooze_direction
    )
    if contradicts_last and consecutive_snoozes >= _CONTRADICTION_MIN_SNOOZES:
        # Alternating rejections: stop inferring and ask instead of oscillating.
        return _result(
            bandwidth=active,
            conf=confidence - _CONTRADICTION_PENALTY,
            changed=False,
            reason=CorrectionReason.CLARIFICATION_NEEDED.value,
            clarification=True,
        )

    # Clearly heavy recommendation rejected: trust it and go one step lighter.
    if candidate_effort_level == BandwidthLevel.DEEP.value and active != BandwidthLevel.LIGHT.value:
        shifted = (
            BandwidthLevel.BALANCED.value
            if active == BandwidthLevel.DEEP.value
            else BandwidthLevel.LIGHT.value
        )
        return _result(
            bandwidth=shifted,
            conf=confidence + _SHIFT_CONFIDENCE_BUMP,
            changed=True,
            reason=CorrectionReason.HEAVY_SNOOZE_SHIFT.value,
            clarification=False,
        )

    if direction == "lighter":
        # Light candidate rejected: ambiguous evidence, never force a mode.
        return _result(
            bandwidth=active,
            conf=confidence - _LIGHT_SNOOZE_PENALTY,
            changed=False,
            reason=CorrectionReason.LIGHT_SNOOZE_DEFLATE.value,
            clarification=False,
        )

    if direction == "heavier":
        # Heavier-than-active but not clearly deep (e.g. light mode rejecting a
        # balanced comic): cannot go lighter, so deflate confidence only.
        return _result(
            bandwidth=active,
            conf=confidence - _LIGHT_SNOOZE_PENALTY,
            changed=False,
            reason=CorrectionReason.LIGHT_SNOOZE_DEFLATE.value,
            clarification=False,
        )

    return _result(
        bandwidth=active,
        conf=confidence - _AMBIGUOUS_PENALTY,
        changed=False,
        reason=CorrectionReason.CONFIDENCE_DEGRADE.value,
        clarification=False,
    )
