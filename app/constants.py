"""Application constants and enums."""

from enum import StrEnum


class EventType(StrEnum):
    """Event types for the event log."""

    ROLL = "roll"
    RATE = "rate"
    REORDER = "reorder"
    DELETE = "delete"
    ROLLED_BUT_SKIPPED = "rolled_but_skipped"
    SNOOZE = "snooze"


class ThreadStatus(StrEnum):
    """Thread status values."""

    ACTIVE = "active"
    COMPLETED = "completed"


class Bandwidth(StrEnum):
    """Ephemeral reading-bandwidth levels for an active session (issue #1706)."""

    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"


class BandwidthSource(StrEnum):
    """Provenance of a session's ephemeral bandwidth state (issue #1706)."""

    INFERRED = "inferred"
    MANUAL = "manual"
    SNOOZE = "snooze"
    QUIZ = "quiz"


# Inference-facing alias (issue #1707): the pure bandwidth-inference service
# and its tests refer to the same canonical level enum by this name.
BandwidthLevel = Bandwidth


class Intent(StrEnum):
    """Ephemeral reading-intent levels for an active session (issue #1728).

    ``random`` is a first-class intent value that bypasses contextual
    weighting. The remaining values are ordinary intents that are neutral by
    default until later intent inference is implemented.
    """

    BALANCED = "balanced"
    MOMENTUM = "momentum"
    FAMILIAR = "familiar"
    EXPLORE = "explore"
    RANDOM = "random"


class IntentSource(StrEnum):
    """Provenance of a session's ephemeral reading-intent state (issue #1728)."""

    INFERRED = "inferred"
    MANUAL = "manual"
    SNOOZE = "snooze"
    QUIZ = "quiz"


# Inference-facing alias mirroring BandwidthLevel: later intent-inference
# services and their tests can refer to the canonical level enum by this name.
IntentLevel = Intent


# Persisted value tuples backing the sessions CHECK constraints. Kept in sync
# with the Bandwidth / BandwidthSource / Intent / IntentSource StrEnum members.
BANDWIDTH_VALUES: tuple[str, ...] = tuple(b.value for b in Bandwidth)
BANDWIDTH_SOURCE_VALUES: tuple[str, ...] = tuple(s.value for s in BandwidthSource)
INTENT_VALUES: tuple[str, ...] = tuple(i.value for i in Intent)
INTENT_SOURCE_VALUES: tuple[str, ...] = tuple(src.value for src in IntentSource)


# Dice ladder - standard RPG dice progression
# Extended to support large thread pools (50+ threads)
DICE_LADDER = [4, 6, 8, 10, 12, 20, 30, 50, 100]

# Session configuration
DEFAULT_SESSION_GAP_HOURS = 6

# Supported visual theme identifiers persisted per user (issue #1398).
THEME_CLASSIC = "classic"
THEME_INK_GOLD = "ink-gold"
THEME_COMMAND_CENTER = "command-center"
SUPPORTED_THEMES: tuple[str, ...] = (
    THEME_CLASSIC,
    THEME_INK_GOLD,
    THEME_COMMAND_CENTER,
)
DEFAULT_THEME = THEME_CLASSIC

# Deadlock retry configuration
DEADLOCK_MAX_RETRIES = 3
DEADLOCK_INITIAL_DELAY = 0.1


# ---------------------------------------------------------------------------
# Tag vocabulary and color palette (issue #3030)
# ---------------------------------------------------------------------------

TAG_COLOR_PALETTE: dict[str, str] = {
    "red": "#DC2626",
    "orange": "#F97316",
    "amber": "#F59E0B",
    "yellow": "#EAB308",
    "lime": "#84CC16",
    "green": "#22C55E",
    "emerald": "#10B981",
    "teal": "#14B8A6",
    "cyan": "#06B6D4",
    "sky": "#0EA5E9",
    "blue": "#3B82F6",
    "indigo": "#6366F1",
    "violet": "#8B5CF6",
    "purple": "#A855F7",
    "fuchsia": "#D946EF",
    "pink": "#EC4899",
    "rose": "#F43F5E",
    "crimson": "#B91C1C",
    "burgundy": "#7F1D1D",
    "maroon": "#78350F",
    "brown": "#92400E",
    "gold": "#D97706",
    "bronze": "#B45309",
    "khaki": "#A16207",
    "olive": "#65A30D",
    "forest": "#15803D",
    "mint": "#34D399",
    "ice": "#22D3EE",
    "cobalt": "#2563EB",
    "royal": "#4F46E5",
    "violet-deep": "#7C3AED",
    "magenta": "#E879F9",
}
"""32 supported tag colors, keyed by human name and mapped to ``#RRGGBB``."""

TAG_COLOR_NAMES: tuple[str, ...] = tuple(TAG_COLOR_PALETTE.keys())
"""Ordered, deduplicated names from the color palette."""

DEFAULT_TAG_COLOR_NAME: str = "red"
"""The default tag color name."""

DEFAULT_TAG_COLOR_HEX: str = "#DC2626"
"""The default tag color value (``#RRGGBB``)."""

TAG_TARGET_TYPES: tuple[str, ...] = ("Issue", "Thread", "ContinuityPlan")
"""Entity types that a tag assignment can point at."""

# Maximum number of edit-distance steps to consider two tag names "near matches".
NEAR_MATCH_DISTANCE: int = 2
# Maximum number of near-match suggestions returned by the API.
NEAR_MATCH_LIMIT: int = 8


def validate_tag_color(color: object) -> tuple[str, str]:
    """Validate and normalize a tag color against the fixed palette.

    Accepts either a palette name (e.g. ``"red"``) or a hex value matching a
    palette entry (e.g. ``"#DC2626"``), case-insensitively.

    Args:
        color: The color to validate.

    Returns:
        Tuple of ``(color_name, color_hex)``. The hex is always the canonical
        palette value, so a lowercase request such as ``"#3b82f6"`` resolves to
        the stored ``"#3B82F6"``.

    Raises:
        ValueError: When ``color`` is not a string or is not in the palette.
    """
    if not isinstance(color, str):
        raise ValueError("Tag color must be a string")

    normalized = color.strip().lower()
    if not normalized:
        raise ValueError("Tag color cannot be empty")

    if normalized in TAG_COLOR_PALETTE:
        return normalized, TAG_COLOR_PALETTE[normalized]

    if normalized.startswith("#") and len(normalized) == 7:
        for name, hex_value in TAG_COLOR_PALETTE.items():
            if hex_value.lower() == normalized:
                return name, hex_value

    raise ValueError(
        f"Color '{color}' is not in the fixed tag color palette of "
        f"{len(TAG_COLOR_NAMES)} colors"
    )
