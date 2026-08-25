"""Pure Snooze-to-bandwidth correction logic.

This module provides a deterministic, side-effect-free service that interprets
a Snooze as evidence about current session bandwidth without mutating durable
affinity. The correction result is used by the Snooze endpoint to update
ephemeral session state and return structured guidance to the client.

Issue: #1723 (pure logic) + #1726 (structured API contract).
"""

from __future__ import annotations

from enum import StrEnum


class BandwidthLevel(StrEnum):
    """Session bandwidth levels indicating mental demand."""

    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"


class CorrectionReason(StrEnum):
    """Compact reason codes for bandwidth corrections."""

    HEAVY_SNOOZE_SHIFT = "heavy_snooze_shift"
    LIGHT_SNOOZE_DEFLATE = "light_snooze_deflate"
    CONFIDENCE_DEGRADE = "confidence_degrade"
    NO_CORRECTION = "no_correction"
    CLARIFICATION_NEEDED = "clarification_needed"


# Bandwidth ordering for comparison (lower index = lighter)
_BANDWIDTH_ORDER: dict[str, int] = {
    BandwidthLevel.LIGHT: 0,
    BandwidthLevel.BALANCED: 1,
    BandwidthLevel.DEEP: 2,
}

# Confidence thresholds
_HIGH_CONFIDENCE = 0.7
_LOW_CONFIDENCE = 0.3

# Maximum consecutive contradictory snoozes before requesting clarification
_MAX_CONTRADICTORY_SNOOZES = 3


def _bandwidth_index(level: str) -> int:
    """Return numeric index for a bandwidth level.

    Args:
        level: Bandwidth level string.

    Returns:
        Numeric index (0=light, 1=balanced, 2=deep).
    """
    return _BANDWIDTH_ORDER.get(level, 1)


class SnoozeCorrectionResult:
    """Structured result of a Snooze bandwidth correction.

    Attributes:
        active_bandwidth: The proposed active bandwidth after correction.
        active_confidence: Confidence in the proposed bandwidth (0.0–1.0).
        bandwidth_changed: Whether the bandwidth level actually changed.
        reason_code: Compact reason code explaining the correction.
        suggest_clarification: Whether repeated contradictory snoozes
            indicate the user should be asked to clarify.
        predicted_bandwidth: The original launch prediction (unchanged).
    """

    __slots__ = (
        "active_bandwidth",
        "active_confidence",
        "bandwidth_changed",
        "reason_code",
        "suggest_clarification",
        "predicted_bandwidth",
    )

    def __init__(
        self,
        *,
        active_bandwidth: str,
        active_confidence: float,
        bandwidth_changed: bool,
        reason_code: str,
        suggest_clarification: bool,
        predicted_bandwidth: str,
    ) -> None:
        """Initialize a SnoozeCorrectionResult.

        Args:
            active_bandwidth: Proposed active bandwidth after correction.
            active_confidence: Confidence in the proposed bandwidth (0.0–1.0).
            bandwidth_changed: Whether the bandwidth level actually changed.
            reason_code: Compact reason code explaining the correction.
            suggest_clarification: Whether repeated contradictory snoozes
                indicate the user should be asked to clarify.
            predicted_bandwidth: The original launch prediction (unchanged).
        """
        self.active_bandwidth = active_bandwidth
        self.active_confidence = active_confidence
        self.bandwidth_changed = bandwidth_changed
        self.reason_code = reason_code
        self.suggest_clarification = suggest_clarification
        self.predicted_bandwidth = predicted_bandwidth


def classify_candidate_effort(
    effort_source: str | None,
    effort_minutes: float | None,
) -> str:
    """Classify a candidate's effort level from available evidence.

    Maps effort estimates to a coarse bandwidth level for correction
    comparison. This is intentionally simple; richer effort modeling
    lives in the reading-effort model (Phase 1).

    Args:
        effort_source: Source of the effort estimate (e.g., "observed",
            "publication_era", "none").
        effort_minutes: Estimated reading time in minutes, or None.

    Returns:
        One of "light", "balanced", or "deep".
    """
    if effort_minutes is None or effort_source is None or effort_source == "none":
        return BandwidthLevel.BALANCED

    if effort_minutes < 12:
        return BandwidthLevel.LIGHT
    if effort_minutes < 20:
        return BandwidthLevel.BALANCED
    return BandwidthLevel.DEEP


def compute_snooze_correction(
    *,
    current_bandwidth: str,
    current_confidence: float,
    predicted_bandwidth: str,
    candidate_effort_level: str,
    consecutive_snoozes: int,
    last_snooze_direction: str | None,
) -> SnoozeCorrectionResult:
    """Compute the bandwidth correction from a Snooze event.

    This is a pure, deterministic, side-effect-free function. It takes
    the current session bandwidth state and evidence about the snoozed
    candidate, and returns a proposed correction with reason codes.

    Rules:
        - Snoozing a clearly heavy recommendation may shift toward light.
        - Snoozing an already-light recommendation lowers confidence rather
          than inferring an impossible extra-light mode.
        - Repeated contradictory snoozes increase uncertainty and may
          request clarification.
        - When no evidence supports a correction, a neutral no-correction
          result is returned.

    Args:
        current_bandwidth: Current active bandwidth ("light", "balanced",
            "deep").
        current_confidence: Confidence in the current bandwidth (0.0–1.0).
        predicted_bandwidth: Original launch prediction (preserved).
        candidate_effort_level: Classified effort of the snoozed candidate.
        consecutive_snoozes: Number of consecutive snoozes in this session.
        last_snooze_direction: Direction of the last snooze relative to
            current bandwidth ("heavier", "lighter", or None if first snooze).

    Returns:
        A SnoozeCorrectionResult with proposed state and reason codes.
    """
    current_idx = _bandwidth_index(current_bandwidth)
    candidate_idx = _bandwidth_index(candidate_effort_level)

    # Check for contradictory snooze pattern
    if consecutive_snoozes >= _MAX_CONTRADICTORY_SNOOZES and last_snooze_direction is not None:
        if last_snooze_direction != "heavier" and candidate_idx >= current_idx:
            return SnoozeCorrectionResult(
                active_bandwidth=current_bandwidth,
                active_confidence=max(current_confidence - 0.15, 0.0),
                bandwidth_changed=False,
                reason_code=CorrectionReason.CLARIFICATION_NEEDED,
                suggest_clarification=True,
                predicted_bandwidth=predicted_bandwidth,
            )
        if last_snooze_direction != "lighter" and candidate_idx <= current_idx:
            return SnoozeCorrectionResult(
                active_bandwidth=current_bandwidth,
                active_confidence=max(current_confidence - 0.15, 0.0),
                bandwidth_changed=False,
                reason_code=CorrectionReason.CLARIFICATION_NEEDED,
                suggest_clarification=True,
                predicted_bandwidth=predicted_bandwidth,
            )

    # Heavy candidate snooze: shift toward lighter bandwidth
    if candidate_idx > current_idx:
        if current_bandwidth == BandwidthLevel.BALANCED:
            new_bandwidth = BandwidthLevel.LIGHT
            new_confidence = min(current_confidence + 0.1, 1.0)
        elif current_bandwidth == BandwidthLevel.DEEP:
            new_bandwidth = BandwidthLevel.BALANCED
            new_confidence = min(current_confidence + 0.05, 1.0)
        else:
            # Already light, cannot go lighter; degrade confidence
            new_bandwidth = current_bandwidth
            new_confidence = max(current_confidence - 0.1, 0.0)

        if new_bandwidth != current_bandwidth:
            return SnoozeCorrectionResult(
                active_bandwidth=new_bandwidth,
                active_confidence=new_confidence,
                bandwidth_changed=True,
                reason_code=CorrectionReason.HEAVY_SNOOZE_SHIFT,
                suggest_clarification=False,
                predicted_bandwidth=predicted_bandwidth,
            )
        return SnoozeCorrectionResult(
            active_bandwidth=new_bandwidth,
            active_confidence=new_confidence,
            bandwidth_changed=False,
            reason_code=CorrectionReason.LIGHT_SNOOZE_DEFLATE,
            suggest_clarification=False,
            predicted_bandwidth=predicted_bandwidth,
        )

    # Light candidate snooze: degrade confidence or shift toward deeper
    if candidate_idx < current_idx:
        if current_bandwidth == BandwidthLevel.BALANCED:
            new_bandwidth = BandwidthLevel.DEEP
            new_confidence = min(current_confidence + 0.05, 1.0)
        elif current_bandwidth == BandwidthLevel.LIGHT:
            new_bandwidth = BandwidthLevel.BALANCED
            new_confidence = min(current_confidence + 0.05, 1.0)
        else:
            # Already deep, cannot go deeper; degrade confidence
            new_bandwidth = current_bandwidth
            new_confidence = max(current_confidence - 0.1, 0.0)

        if new_bandwidth != current_bandwidth:
            return SnoozeCorrectionResult(
                active_bandwidth=new_bandwidth,
                active_confidence=new_confidence,
                bandwidth_changed=True,
                reason_code=CorrectionReason.LIGHT_SNOOZE_DEFLATE,
                suggest_clarification=False,
                predicted_bandwidth=predicted_bandwidth,
            )
        return SnoozeCorrectionResult(
            active_bandwidth=new_bandwidth,
            active_confidence=new_confidence,
            bandwidth_changed=False,
            reason_code=CorrectionReason.LIGHT_SNOOZE_DEFLATE,
            suggest_clarification=False,
            predicted_bandwidth=predicted_bandwidth,
        )

    # Same-level candidate: degrade confidence when evidence is ambiguous
    new_confidence = max(current_confidence - 0.05, 0.0)
    return SnoozeCorrectionResult(
        active_bandwidth=current_bandwidth,
        active_confidence=new_confidence,
        bandwidth_changed=False,
        reason_code=CorrectionReason.CONFIDENCE_DEGRADE,
        suggest_clarification=False,
        predicted_bandwidth=predicted_bandwidth,
    )
