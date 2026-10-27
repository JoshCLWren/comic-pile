"""Application constants and enums."""

from enum import StrEnum
from typing import Literal


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
THEME_CLASSIC: Literal["classic"] = "classic"
THEME_INK_GOLD: Literal["ink-gold"] = "ink-gold"
THEME_COMMAND_CENTER: Literal["command-center"] = "command-center"
SUPPORTED_THEMES: tuple[str, ...] = (
    THEME_CLASSIC,
    THEME_INK_GOLD,
    THEME_COMMAND_CENTER,
)
ThemeId = Literal["classic", "ink-gold", "command-center"]
DEFAULT_THEME: ThemeId = THEME_CLASSIC

# Deadlock retry configuration
DEADLOCK_MAX_RETRIES = 3
DEADLOCK_INITIAL_DELAY = 0.1

# Password requirements
MIN_PASSWORD_LENGTH = 6
MAX_BCRYPT_PASSWORD_BYTES = 72


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

# Minimum rated issues needed before personal creator statistics are treated as
# reliable. Applies to creator-level averages and, since #3173, also gates which
# series "strongest series" is allowed to rank. Shared by the aggregation layer
# and the response schema so the documented minimum sample and the enforced
# contract cannot drift apart.
MIN_RATED_FOR_RELIABLE: int = 5
MIN_RATED_ISSUES_PER_SERIES: int = MIN_RATED_FOR_RELIABLE

#: Minimum number of shared rated issues a pair of canonical creators must
#: credit before the pair is ranked as a strong or weak team. Below this sample
#: a pair is omitted from ranked results entirely rather than ranked on a thin
#: shared average (issue #3094). Shared by the aggregation layer and the
#: response schema so the documented minimum and the enforced contract cannot
#: drift apart.
MIN_SHARED_TEAM_SAMPLE: int = 3

# ---------------------------------------------------------------------------
# Creator taste-discovery thresholds (issue #3093)
# ---------------------------------------------------------------------------
# Deterministic, documented numbers behind the personal taste-discovery views.
# Discovery is descriptive personal analytics, never a global quality signal.
# Small samples are excluded from every view whose ranking implies reliability
# (consistency, polarization, top-rating rate, trend); the one small-sample
# view is explicitly labeled and sits below the reliability floor. Shared by
# the aggregation layer, the response schema, and the UI copy so the documented
# rule and the enforced contract cannot drift apart.

#: Minimum headline-rated sample before a creator may rank in a view that
#: implies reliability. Reuses the canonical personal-reliability floor.
DISCOVERY_MIN_RELIABLE_SAMPLE: int = MIN_RATED_FOR_RELIABLE

#: "Most consistently loved": a high personal average backed by a meaningful
#: sample and low dispersion (population standard deviation) across the
#: creator's rated issues.
CONSISTENCY_LOVED_MIN_AVERAGE: float = 4.0
CONSISTENCY_LOVED_MAX_STDDEV: float = 0.5

#: "Most polarizing": the spread between a creator's lowest and highest
#: effective rating must reach this value on a meaningful sample.
POLARIZING_MIN_SPREAD: float = 2.0

#: Top of the product's real 0.5–5.0 rating scale and the minimum proportion
#: of a creator's ratings that must sit there to qualify for the top-rate view.
TOP_RATING_VALUE: float = 5.0
TOP_RATING_RATE_MIN_PROPORTION: float = 0.6

#: "Great average, small sample": promising creators whose evidence is still
#: below the reliable-sample floor but who already average highly.
SMALL_SAMPLE_MAX: int = DISCOVERY_MIN_RELIABLE_SAMPLE - 1
SMALL_SAMPLE_MIN_AVERAGE: float = 4.0

#: "Loved creators with unread work": a high personal average plus at least one
#: attributed unread owned issue.
LOVED_WITH_UNREAD_MIN_AVERAGE: float = 4.0

#: "Warmed to / cooled on": minimum rated issues carrying a timestamp before a
#: trend may be claimed, and the minimum change in average rating between the
#: earlier and recent halves of that rated history.
TREND_MIN_SAMPLE: int = 6
TREND_MIN_DELTA: float = 0.5

#: Maximum number of entries returned per discovery view (bounded response).
MAX_DISCOVERY_ENTRIES: int = 10


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
