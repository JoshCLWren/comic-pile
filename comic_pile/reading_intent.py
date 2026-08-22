"""Reading-intent vocabulary for ephemeral reading-session state.

Intent is the second session-mode axis alongside bandwidth. It records what
kind of reading experience the reader wants right now and lives only on the
reading session: it never changes Thread affinity, queue positions, ratings,
or any Taste Bank metadata. Until real intent inference ships, the inferred
placeholder stays ``balanced``.
"""

from typing import Final

INTENT_VALUES: Final[tuple[str, ...]] = ("balanced", "momentum", "familiar", "explore", "random")
DEFAULT_INTENT: Final[str] = "balanced"
INTENT_SOURCES: Final[tuple[str, ...]] = ("inferred", "manual", "snooze", "quiz")
DEFAULT_INTENT_SOURCE: Final[str] = "inferred"
PLACEHOLDER_INTENT_CONFIDENCE: Final[float] = 0.5
INTENT_STATE_VERSION: Final[str] = "v1"


def is_valid_intent(value: str | None) -> bool:
    """Check whether a value is a first-class intent value.

    Args:
        value: Candidate intent value, or None when unset.

    Returns:
        True when value is one of INTENT_VALUES.
    """
    return isinstance(value, str) and value in INTENT_VALUES


def normalize_intent(value: str | None) -> str:
    """Resolve stored intent to a usable value with safe defaults.

    Unset (NULL) and unknown legacy values behave as the balanced default so
    pre-existing sessions keep working without a backfill migration.

    Args:
        value: Stored intent value, or None when the column is unset.

    Returns:
        The stored intent when valid, otherwise DEFAULT_INTENT.
    """
    if is_valid_intent(value):
        return value
    return DEFAULT_INTENT


def initial_intent_state() -> dict[str, str | float]:
    """Build the placeholder inferred intent state for a brand-new session.

    Returns:
        Column values recording a low-confidence inferred balanced intent.
    """
    return {
        "reading_intent": DEFAULT_INTENT,
        "reading_intent_source": DEFAULT_INTENT_SOURCE,
        "reading_intent_confidence": PLACEHOLDER_INTENT_CONFIDENCE,
        "reading_intent_version": INTENT_STATE_VERSION,
    }
