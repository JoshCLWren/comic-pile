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
