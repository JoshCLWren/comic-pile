"""Canonical recommendation algorithm versioning and safe legacy rollback.

Defines the single algorithm version identifier used in roll decisions,
provides the operator-level kill switch to recover legacy unweighted
selection, and leaves all durable data untouched.
"""

from __future__ import annotations

from app.config import get_recommendation_settings

# Canonical recommendation algorithm version used when contextual
# weighting is active.
CANONICAL_ALGORITHM_VERSION: str = "v1-contextual"

# Legacy identifier used when the kill switch forces unweighted selection.
LEGACY_ALGORITHM_VERSION: str = "legacy"

# Control-state labels used in event metrics and decision snapshots.
ALGORITHM_CONTROL_STATE_WEIGHTED: str = "contextual"
ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED: str = "legacy"


def is_legacy_mode_enabled() -> bool:
    """Return whether the operator kill switch forces legacy unweighted mode.

    The switch is safe to toggle at any time: it does not modify session
    history, Taste Bank data, ratings, queue positions, or effort estimates.
    A forced legacy run records ``LEGACY_ALGORITHM_VERSION`` and
    ``ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED`` in the roll event so
    metrics remain distinguishable.
    """
    recommendation_settings = get_recommendation_settings()
    return recommendation_settings.control_mode == "legacy"


def get_current_algorithm_version() -> str:
    """Return the version identifier active for the current request."""
    return LEGACY_ALGORITHM_VERSION if is_legacy_mode_enabled() else CANONICAL_ALGORITHM_VERSION


def get_current_control_state() -> str:
    """Return the control-state label for the current request."""
    return (
        ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED
        if is_legacy_mode_enabled()
        else ALGORITHM_CONTROL_STATE_WEIGHTED
    )