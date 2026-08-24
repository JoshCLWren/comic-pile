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
    MODE_CHANGE = "mode_change"


class ThreadStatus(StrEnum):
    """Thread status values."""

    ACTIVE = "active"
    COMPLETED = "completed"


class ModeSource(StrEnum):
    """Provenance of the active session-mode state (#1685, #1706, #1728)."""

    INFERRED = "inferred"
    MANUAL = "manual"
    SNOOZE = "snooze"
    QUIZ = "quiz"


class ModeIntent(StrEnum):
    """Reading-intent values for the active session (#1685, #1728).

    ``random`` is a first-class escape hatch that must keep producing the
    legacy unweighted selection inside the bounded die pool.
    """

    BALANCED = "balanced"
    MOMENTUM = "momentum"
    FAMILIAR = "familiar"
    EXPLORE = "explore"
    RANDOM = "random"


# Canonical bandwidth axis values (#1685, #1706). Stored on sessions as
# ephemeral state; contextual weighting consumes them only inside the
# existing die pool.
MODE_BANDWIDTHS: tuple[str, ...] = ("light", "balanced", "deep")
MODE_INTENTS: tuple[str, ...] = tuple(value.value for value in ModeIntent)

# Confidence recorded when the reader explicitly sets a mode dimension.
MANUAL_MODE_CONFIDENCE = 1.0


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
