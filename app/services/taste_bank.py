"""Centralized, deterministic Taste Bank discovery eligibility rules.

These rules decide which inferred taste signals may be surfaced as an
occasional "ComicPile noticed something" discovery card (issue #1750). The
rules are deliberately conservative and pure: given the same signal state and
clock reading they always produce the same answer.

Suppression model:

- An explicit verdict ends prompting permanently. ``rejected`` never prompts
  again; ``confirmed`` and ``sometimes`` are already-known preferences.
- A dismissal is only a temporary cooldown. It never sets or implies a
  verdict.
- A recent prompt starts a cooldown so the same pattern does not nag.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.models.taste_signal import (
    SIGNAL_VERDICT_CONFIRMED,
    SIGNAL_VERDICT_REJECTED,
    SIGNAL_VERDICT_SOMETIMES,
    TasteSignal,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# Minimum evidence before ComicPile dares to ask.
MIN_PROMPT_EVIDENCE_COUNT = 3
# Mean rating points above the reader's baseline required to prompt.
MIN_PROMPT_AFFINITY_DELTA = 0.5
# Evidence must span more than one thread so one lucky comic cannot prompt.
MIN_PROMPT_DISTINCT_THREADS = 2
# After surfacing a signal, wait this long before surfacing it again.
PROMPT_COOLDOWN_DAYS = 30
# A dismissal suppresses re-prompting for this long. It is not a verdict.
DISMISSAL_SUPPRESSION_DAYS = 14
# Upper bound on discoveries returned at once; Roll shows one at a time.
MAX_ACTIVE_DISCOVERIES = 3

PROMPT_COOLDOWN = timedelta(days=PROMPT_COOLDOWN_DAYS)
DISMISSAL_SUPPRESSION = timedelta(days=DISMISSAL_SUPPRESSION_DAYS)


def is_prompt_eligible(signal: TasteSignal, *, now: datetime | None = None) -> bool:
    """Return whether a signal may currently be surfaced as a discovery.

    Args:
        signal: The inferred taste signal to evaluate.
        now: Current time; defaults to the current UTC time.

    Returns:
        True when the signal has enough diverse evidence, no explicit verdict,
        and is outside both the prompt cooldown and any dismissal suppression.
    """
    current_time = now if now is not None else datetime.now(UTC)

    if signal.verdict is not None:
        return False
    if signal.evidence_count < MIN_PROMPT_EVIDENCE_COUNT:
        return False
    if signal.distinct_threads < MIN_PROMPT_DISTINCT_THREADS:
        return False
    if signal.affinity_delta < MIN_PROMPT_AFFINITY_DELTA:
        return False
    if signal.prompted_at is not None and current_time - signal.prompted_at < PROMPT_COOLDOWN:
        return False
    if (
        signal.dismissed_at is not None
        and current_time - signal.dismissed_at < DISMISSAL_SUPPRESSION
    ):
        return False
    return True


def rank_prompt_eligible(signals: Sequence[TasteSignal], *, now: datetime | None = None) -> list[
    TasteSignal
]:
    """Filter signals down to prompt-eligible ones, strongest first.

    Args:
        signals: Candidate inferred signals for one user.
        now: Current time; defaults to the current UTC time.

    Returns:
        Eligible signals ordered by strength: highest affinity delta first,
        then the richest evidence count as a tiebreaker.
    """
    eligible = [signal for signal in signals if is_prompt_eligible(signal, now=now)]
    return sorted(eligible, key=lambda signal: (-signal.affinity_delta, -signal.evidence_count))


def build_discovery_prompt(signal: TasteSignal) -> str:
    """Build concise human-readable prompt copy for a signal.

    Args:
        signal: The eligible signal to describe.

    Returns:
        Prompt copy that states the observed pattern and asks for a verdict.
    """
    reads = f"across {signal.evidence_count} reads"
    if signal.feature_type == "creator":
        role = signal.creator_role
        if role == "writer":
            subject = f"comics written by {signal.label}"
        elif role == "artist":
            subject = f"comics with art by {signal.label}"
        else:
            subject = f"comics involving {signal.label}"
        return (
            f"You've rated {subject} well above your usual baseline {reads}. "
            f"Is {signal.label} generally a draw for you?"
        )
    return (
        f"You've rated {signal.label} issues well above your usual baseline {reads}. "
        f"Do you generally enjoy {signal.label}?"
    )


__all__ = [
    "DISMISSAL_SUPPRESSION",
    "DISMISSAL_SUPPRESSION_DAYS",
    "MAX_ACTIVE_DISCOVERIES",
    "MIN_PROMPT_AFFINITY_DELTA",
    "MIN_PROMPT_DISTINCT_THREADS",
    "MIN_PROMPT_EVIDENCE_COUNT",
    "PROMPT_COOLDOWN",
    "PROMPT_COOLDOWN_DAYS",
    "SIGNAL_VERDICT_CONFIRMED",
    "SIGNAL_VERDICT_REJECTED",
    "SIGNAL_VERDICT_SOMETIMES",
    "build_discovery_prompt",
    "is_prompt_eligible",
    "rank_prompt_eligible",
]
