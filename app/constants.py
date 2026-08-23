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
    """Source of a mode change."""

    MANUAL = "manual"
    SYSTEM = "system"
    INFERRED = "inferred"


class ModeIntent(StrEnum):
    """Intent of a mode change."""

    MANUAL = "manual"
    RANDOM = "random"
    SNOOZE = "snooze"
    RATING = "rating"
    OVERRIDE = "override"


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
