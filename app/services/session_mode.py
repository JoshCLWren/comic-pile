"""Canonical session-mode state and Snooze correction guidance.

This module owns the compact, deterministic contract behind the Roll session
mode (bandwidth + intent) and the Snooze correction signal used by the
frontend correction sheet.

Bandwidth describes how mentally demanding a comic is for the reader right now.
Intent describes whether the reader wants momentum, familiarity, exploration,
or unweighted randomness. Both are ephemeral session state: they never change
durable thread affinity, ratings, or queue positions.
"""

from __future__ import annotations

from dataclasses import dataclass

BANDWIDTH_LEVELS: tuple[str, ...] = ("light", "balanced", "deep")
INTENT_LEVELS: tuple[str, ...] = ("balanced", "momentum", "familiar", "explore", "random")
MODE_SOURCES: tuple[str, ...] = ("manual", "snooze")

DEFAULT_BANDWIDTH_CONFIDENCE = 0.5
MANUAL_BANDWIDTH_CONFIDENCE = 1.0

#: Confidence at or below which a directional correction counts as meaningful
#: uncertainty even before the repeated-mismatch threshold is reached.
LOW_CONFIDENCE_THRESHOLD = 0.3

#: Number of snoozes in one session after which the backend asks the reader to
#: clarify instead of continuing to guess. The first two snoozes of a session
#: stay frictionless by design.
REPEATED_MISMATCH_SNOOZE_COUNT = 3


def is_valid_bandwidth(value: str | None) -> bool:
    """Check whether ``value`` is a canonical bandwidth level.

    Args:
        value: Candidate bandwidth value.

    Returns:
        True when the value is a canonical bandwidth level or None.
    """
    return value is None or value in BANDWIDTH_LEVELS


def is_valid_intent(value: str | None) -> bool:
    """Check whether ``value`` is a canonical intent level.

    Args:
        value: Candidate intent value.

    Returns:
        True when the value is a canonical intent level or None.
    """
    return value is None or value in INTENT_LEVELS


def estimate_candidate_effort(issues_remaining: int | None) -> str:
    """Estimate the coarse effort tier of a candidate from its remaining issues.

    The estimate is deliberately simple and deterministic: it only needs to be
    consistent enough to detect that a rejected recommendation was clearly
    heavy relative to the session's active bandwidth.

    Args:
        issues_remaining: Remaining issue count for the candidate, if tracked.

    Returns:
        One of ``light``, ``balanced``, ``deep``, or ``unknown``.
    """
    if issues_remaining is None:
        return "unknown"
    if issues_remaining <= 5:
        return "light"
    if issues_remaining <= 15:
        return "balanced"
    return "deep"


@dataclass(frozen=True)
class CorrectionDecision:
    """Pure Snooze correction outcome for one rejected candidate.

    Attributes:
        bandwidth_changed: Whether the proposed state changes active bandwidth.
        new_bandwidth: Proposed active bandwidth after applying the decision.
        new_confidence: Proposed confidence after applying the decision.
        reason_code: Compact machine-readable reason for the transition.
        suggest_clarification: Whether the frontend should offer the
            correction sheet for this snooze.
    """

    bandwidth_changed: bool
    new_bandwidth: str | None
    new_confidence: float
    reason_code: str
    suggest_clarification: bool


def _one_step_lighter(bandwidth: str) -> str:
    """Return the next lighter canonical bandwidth level.

    Args:
        bandwidth: Current non-light bandwidth level.

    Returns:
        The canonical level one step lighter; ``light`` never lightens further.
    """
    index = BANDWIDTH_LEVELS.index(bandwidth)
    return BANDWIDTH_LEVELS[max(0, index - 1)]


def decide_snooze_correction(
    *,
    active_bandwidth: str | None,
    active_bandwidth_source: str | None,
    active_confidence: float | None,
    candidate_effort: str,
    session_snooze_count: int,
) -> CorrectionDecision:
    """Interpret one Snooze as evidence about current session bandwidth.

    The function is deterministic and side-effect free. Rules are conservative:

    - Snoozing a clearly heavier candidate than the active bandwidth shifts the
      inferred bandwidth one step lighter with source ``snooze``.
    - Snoozing an equal-or-lighter candidate lowers confidence instead of
      inventing an impossible extra-light mode.
    - Manual bandwidth is never overridden; evidence only accumulates against
      it through lowered confidence.
    - Repeated mismatches within one session ask for clarification rather than
      letting the model keep guessing.

    Args:
        active_bandwidth: Session's active bandwidth level, or None when unset.
        active_bandwidth_source: Source of the active bandwidth, or None.
        active_confidence: Confidence in the active bandwidth, or None when unset.
        candidate_effort: Coarse effort tier of the rejected candidate.
        session_snooze_count: Snooze count for this session including this one.

    Returns:
        A CorrectionDecision describing the proposed transition.
    """
    reference_bandwidth = active_bandwidth if active_bandwidth is not None else "balanced"
    previous_confidence = (
        active_confidence if active_confidence is not None else DEFAULT_BANDWIDTH_CONFIDENCE
    )
    repeated_mismatch = session_snooze_count >= REPEATED_MISMATCH_SNOOZE_COUNT

    if candidate_effort == "unknown":
        return CorrectionDecision(
            bandwidth_changed=False,
            new_bandwidth=active_bandwidth,
            new_confidence=previous_confidence,
            reason_code="none",
            suggest_clarification=False,
        )

    candidate_index = BANDWIDTH_LEVELS.index(candidate_effort)
    reference_index = BANDWIDTH_LEVELS.index(reference_bandwidth)
    manual_override = active_bandwidth_source == "manual"

    if candidate_index > reference_index and not manual_override:
        proposed = _one_step_lighter(reference_bandwidth)
        changed = proposed != active_bandwidth
        boosted = min(0.9, previous_confidence + 0.2)
        return CorrectionDecision(
            bandwidth_changed=changed,
            new_bandwidth=proposed,
            new_confidence=boosted,
            reason_code="bandwidth_lightened",
            suggest_clarification=repeated_mismatch or boosted <= LOW_CONFIDENCE_THRESHOLD,
        )

    if manual_override:
        reason = "manual_respected"
    elif candidate_effort == "light":
        reason = "already_light"
    else:
        reason = "weak_signal"

    lowered = max(0.05, previous_confidence * 0.8)
    return CorrectionDecision(
        bandwidth_changed=False,
        new_bandwidth=active_bandwidth,
        new_confidence=lowered,
        reason_code=reason,
        suggest_clarification=repeated_mismatch,
    )
