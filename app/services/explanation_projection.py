"""Projection of recommendation reason codes into human-readable explanations.

The reason codes persisted on a roll ``Event`` describe the actual
decision-time selection context. They never expose implementation-only
identifiers, raw candidate arrays, or opaque scores. The backend selection
logic (momentum weighting with a pure-random bypass) is the single source of
truth for these codes; this module only projects them into reader-facing text.
"""

from __future__ import annotations

# Human-readable projection of persisted reason codes. Codes not present here
# fall back to a safe title-cased rendering of the code itself.
EXPLANATION_MAP: dict[str, str] = {
    "momentum_weighted": "Weighted by your recent reading momentum",
    "pure_random": "Pure random selection",
    "fallback_random": "Fallback to random selection",
}


def project_explanations(reason_codes: list[str] | None) -> list[str]:
    """Project recommendation reason codes into human-readable explanations.

    Args:
        reason_codes: Reason codes persisted on the roll event.

    Returns:
        Ordered list of human-readable explanation strings. Empty when no
        codes are present, which keeps the UI collapsed by default.
    """
    if not reason_codes:
        return []

    explanations: list[str] = []
    for code in reason_codes:
        if code in EXPLANATION_MAP:
            explanations.append(EXPLANATION_MAP[code])
        else:
            explanations.append(code.replace("_", " ").title())

    return explanations


def get_primary_explanation(reason_codes: list[str] | None) -> str | None:
    """Return the primary explanation for a roll, or ``None`` if none exists.

    Args:
        reason_codes: Reason codes persisted on the roll event.

    Returns:
        The first human-readable explanation, or ``None`` when the selection
        carried no explanation (e.g. an explicit manual override).
    """
    explanations = project_explanations(reason_codes)
    return explanations[0] if explanations else None