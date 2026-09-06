"""Canonical recommendation algorithm versioning and operator control state.

Phase 9 of the personalized-Roll architecture (issue #1767): recommendation
behavior must be safely reversible. This module owns the single canonical
algorithm-version identifiers and the operator-level control-mode vocabulary so
selection, decision snapshots, diagnostics, and metrics all refer to the same
strings instead of drifting per call site.

The module is deliberately dependency-free (standard library only): selection
and weighting modules import it without pulling in FastAPI/SQLAlchemy, and
runtime configuration feeds these identifiers into ``app/config.py``.

Control model
-------------

- ``RECOMMENDATION_ALGORITHM_VERSION`` names the active contextual selector
  generation (``v1-contextual``).
- ``RECOMMENDATION_ALGORITHM_VERSION_LEGACY`` names the pre-contextual
  unweighted behavior that the operator kill switch restores.
- ``CONTROL_MODE_CONTEXTUAL`` is the default runtime state: bandwidth/intent
  weighting applies inside the bounded die pool.
- ``CONTROL_MODE_LEGACY`` is the operator-controlled kill switch. It forces the
  legacy unweighted draw inside the existing die pool for every intent while
  leaving instrumentation active so the forced runs stay distinguishable.
- The user-level ``random`` intent remains an independent bypass: it is
  recorded as a pure-random bypass regardless of any operator control state.
"""

from __future__ import annotations

from typing import Final

#: Canonical identifier of the active contextual recommendation algorithm.
RECOMMENDATION_ALGORITHM_VERSION: Final[str] = "v1-contextual"

#: Canonical identifier of legacy unweighted selection (the pre-contextual and
#: forced-legacy behavior).
RECOMMENDATION_ALGORITHM_VERSION_LEGACY: Final[str] = "legacy"

#: Version attributed to pre-instrumentation events that carry no recorded
#: algorithm version at all.
RECOMMENDATION_ALGORITHM_VERSION_LEGACY_UNKNOWN: Final[str] = "legacy-unknown"

#: Runtime control mode enforcing contextual weighting.
CONTROL_MODE_CONTEXTUAL: Final[str] = "contextual"

#: Runtime control mode forcing legacy unweighted selection.
CONTROL_MODE_LEGACY: Final[str] = "legacy"

#: Every supported operator control mode.
CONTROL_MODES: Final[frozenset[str]] = frozenset(
    {CONTROL_MODE_CONTEXTUAL, CONTROL_MODE_LEGACY}
)

#: Reason code recorded on forced-legacy roll events.
FORCED_LEGACY_REASON_CODE: Final[str] = "forced_legacy"

#: ``selection_method`` label recorded on forced-legacy roll events so decision
#: history distinguishes operator-forced unweighted draws from user ``random``
#: intent bypasses and from pre-instrumentation events.
FORCED_LEGACY_SELECTION_METHOD: Final[str] = "legacy"


def recommendation_algorithm_version(control_mode: str | None) -> str:
    """Return the canonical algorithm version for a control mode.

    Args:
        control_mode: Operator control mode (``contextual`` or ``legacy``).
            ``None`` or anything unrecognized resolves to the active
            contextual version.

    Returns:
        ``RECOMMENDATION_ALGORITHM_VERSION_LEGACY`` for the legacy control
        mode, otherwise ``RECOMMENDATION_ALGORITHM_VERSION``.
    """
    if control_mode == CONTROL_MODE_LEGACY:
        return RECOMMENDATION_ALGORITHM_VERSION_LEGACY
    return RECOMMENDATION_ALGORITHM_VERSION