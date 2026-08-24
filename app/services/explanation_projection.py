"""Projection of recommendation reason codes into human-readable explanations."""

from __future__ import annotations


EXPLANATION_MAP: dict[str, str] = {
    "strong_affinity": "Strong affinity",
    "moderate_affinity": "Moderate affinity",
    "quick_read": "Quick read",
    "~11_minute_read": "~11-minute read",
    "longer_read": "Longer read",
    "format_compatible": "Fits your preferred format",
    "recent_series_momentum": "Recent series momentum",
    "some_series_activity": "Some series activity",
    "pure_random": "Pure random selection",
    "fallback_random": "Fallback to random selection",
}


def project_explanations(reason_codes: list[str] | None) -> list[str]:
    """Project recommendation reason codes into human-readable explanations.

    Args:
        reason_codes: List of recommendation reason codes from the event

    Returns:
        List of human-readable explanation strings
    """
    if not reason_codes:
        return []

    explanations = []
    for code in reason_codes:
        if code in EXPLANATION_MAP:
            explanations.append(EXPLANATION_MAP[code])

    # If no explanations were mapped but we had codes, return the codes as fallback
    if not explanations and reason_codes:
        return [code.replace("_", " ").title() for code in reason_codes]

    return explanations


def get_primary_explanation(reason_codes: list[str] | None) -> str | None:
    """Get the primary (most important) explanation from reason codes.
    
    Args:
        reason_codes: List of recommendation reason codes from the event
        
    Returns:
        Primary explanation string or None
    """
    explanations = project_explanations(reason_codes)
    return explanations[0] if explanations else None