"""Reading-mode service: canonical session bandwidth/intent state.

This module owns the single source of truth for the ephemeral reading-mode
axes (bandwidth + intent) stored on the active session. The frontend renders
whatever bootstrap reports and never keeps a second mode cache.
"""

from app.models import Session
from app.schemas.reading_mode import (
    BANDWIDTH_LABELS,
    INTENT_LABELS,
    CorrectionGuidance,
    CorrectionOption,
    SessionModeState,
)

# Number of consecutive snoozes without a durable rating after which the
# backend starts asking the reader to clarify their current mode. One snooze is
# normal usage and must never interrupt with a modal.
REPEATED_MISMATCH_THRESHOLD = 2

MANUAL_CONFIDENCE = 1.0

_CORRECTION_OPTIONS: list[CorrectionOption] = [
    CorrectionOption(id="easier", label="Even easier", bandwidth="light"),
    # Confirms the current bandwidth as intentionally chosen without changing it.
    CorrectionOption(
        id="keep_level", label="Keep this level, different comic", confirm_bandwidth=True
    ),
    CorrectionOption(id="familiar", label="Something familiar", intent="familiar"),
    CorrectionOption(id="different", label="Something different", intent="explore"),
    CorrectionOption(id="pure_random", label="Pure random", intent="random"),
]


def build_mode_state(session: Session) -> SessionModeState:
    """Project a session's persisted mode columns into the canonical schema."""
    return SessionModeState(
        bandwidth=session.bandwidth,
        bandwidth_source=session.bandwidth_source,
        bandwidth_confidence=session.bandwidth_confidence,
        intent=session.intent,
        intent_source=session.intent_source,
        intent_confidence=session.intent_confidence,
        mode_version=session.mode_version,
    )


def apply_manual_mode_change(
    session: Session,
    *,
    bandwidth: str | None = None,
    intent: str | None = None,
) -> SessionModeState:
    """Apply an explicit reader mode change to the session in place.

    Changed dimensions are marked ``manual`` with full confidence; untouched
    dimensions keep their existing value, source, and confidence. Every change
    bumps ``mode_version`` so later analytics can order mode states.

    Args:
        session: The active session model to mutate (not committed).
        bandwidth: New canonical bandwidth value, or None to preserve.
        intent: New canonical intent value, or None to preserve.

    Returns:
        The updated canonical SessionModeState.
    """
    if bandwidth is not None:
        session.bandwidth = bandwidth
        session.bandwidth_source = "manual"
        session.bandwidth_confidence = MANUAL_CONFIDENCE
    if intent is not None:
        session.intent = intent
        session.intent_source = "manual"
        session.intent_confidence = MANUAL_CONFIDENCE

    session.mode_version += 1
    # Explicit guidance supersedes the repeated-snooze mismatch signal.
    session.consecutive_snoozes = 0
    return build_mode_state(session)


def record_snooze_streak(session: Session) -> int:
    """Increment the consecutive-snooze counter and persist the new value.

    Returns:
        The updated consecutive-snooze count.
    """
    session.consecutive_snoozes = (session.consecutive_snoozes or 0) + 1
    return session.consecutive_snoozes


def clear_snooze_streak(session: Session) -> None:
    """Reset the consecutive-snooze counter after durable reading activity."""
    session.consecutive_snoozes = 0


def build_correction_guidance(session: Session) -> CorrectionGuidance:
    """Compute Snooze correction guidance for the current session state.

    A normal snooze never asks for correction. Only a repeated mismatch —
    consecutive snoozes beyond ``REPEATED_MISMATCH_THRESHOLD`` without any
    durable rating — produces actionable guidance, and the options map to the
    same canonical bandwidth/intent values used everywhere else.

    Args:
        session: The active session after its streak was recorded.

    Returns:
        CorrectionGuidance with suggest_correction=False for ordinary snoozes.
    """
    if session.consecutive_snoozes < REPEATED_MISMATCH_THRESHOLD:
        return CorrectionGuidance(suggest_correction=False)

    reason = (
        "You've skipped several picks in a row. "
        "Want to steer the session instead?"
    )
    return CorrectionGuidance(
        suggest_correction=True,
        reason=reason,
        options=list(_CORRECTION_OPTIONS),
    )


def resolve_correction_option(option_id: str) -> CorrectionOption | None:
    """Return the canonical correction option for an id, or None."""
    for option in _CORRECTION_OPTIONS:
        if option.id == option_id:
            return option
    return None


def mode_display_label(bandwidth: str, intent: str) -> str:
    """Human-readable compact label such as 'Light · Momentum'."""
    return f"{BANDWIDTH_LABELS.get(bandwidth, bandwidth)} · {INTENT_LABELS.get(intent, intent)}"
