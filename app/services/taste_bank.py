"""Taste Bank discovery surfacing for the Roll page (issue #1750).

This service adapts the canonical prompt-eligibility engine
(``app.services.prompt_eligibility``, issue #1746) and the durable Taste Bank
model to the occasional "ComicPile noticed something" discovery card:

- Only signals that pass the canonical eligibility gates are surfaced.
- Explicit verdicts are never written here; verdicts go through the canonical
  Taste Bank verdict API (issue #1749). Signals with any explicit verdict are
  excluded from discovery entirely.
- Dismissal only starts a temporary suppression window by writing
  ``prompt_suppressed_until``; it never sets or implies a verdict.
- Surfacing a signal records ``last_prompted_at`` so the canonical cooldown
  suppresses immediate re-prompting.

Discovery never blocks rolling or rating: callers treat every failure here as
"no card".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.taste_signal import SIGNAL_CREATOR, TasteSignal
from app.repositories import taste_signals as taste_signals_repository
from app.schemas.taste import TasteSignal as EligibilitySignal
from app.schemas.taste_discovery import (
    TasteDiscovery,
    TasteDiscoveryListResponse,
)
from app.services.prompt_eligibility import evaluate_prompt_eligibility

# Upper bound on discoveries returned at once; Roll shows one at a time.
MAX_ACTIVE_DISCOVERIES = 3

# A dismissal suppresses re-prompting for this long. It is not a verdict.
DISMISSAL_SUPPRESSION_DAYS = 14
DISMISSAL_SUPPRESSION = timedelta(days=DISMISSAL_SUPPRESSION_DAYS)


def _is_creator_role(signal: TasteSignal) -> bool:
    """Return whether a creator signal carries a specific role segment.

    Args:
        signal: The durable ORM signal.

    Returns:
        True for keys shaped like ``creator:<role>:<name>``.
    """
    if signal.signal_type != SIGNAL_CREATOR:
        return False
    return len(signal.external_key.split(":")) >= 3


def _to_eligibility_signal(
    signal: TasteSignal, *, now: datetime
) -> EligibilitySignal | None:
    """Convert a durable signal into the canonical eligibility input.

    Signals carrying an explicit verdict are dropped entirely: confirmed and
    sometimes patterns are already-known preferences and rejected ones are
    suppressed for good, so none of them should ever surface again. Signals
    inside their dismissal-suppression window are skipped as well.

    Args:
        signal: The durable ORM signal.
        now: Current UTC time used for dismissal-suppression evaluation.

    Returns:
        The canonical eligibility signal, or ``None`` when the row must not be
        evaluated.
    """
    if signal.user_verdict is not None:
        return None
    if (
        signal.prompt_suppressed_until is not None
        and now < signal.prompt_suppressed_until
    ):
        return None
    return EligibilitySignal(
        user_id=signal.user_id,
        signal_type=signal.signal_type,
        stable_key=signal.external_key,
        display_name=signal.display_name,
        affinity=signal.affinity_estimate or 0.0,
        confidence=signal.confidence or 0.0,
        evidence_count=signal.evidence_count,
        evidence_diversity=signal.distinct_thread_count,
        verdict=None,
        last_prompted_at=signal.last_prompted_at,
        last_rejected_at=None,
        is_creator_role=_is_creator_role(signal),
    )


def build_discovery_prompt(signal: TasteSignal) -> str:
    """Build concise human-readable prompt copy for a durable signal.

    Args:
        signal: The eligible durable signal.

    Returns:
        Prompt copy stating the observed pattern with evidence context.
    """
    reads = f"across {signal.evidence_count} reads"
    if signal.signal_type == SIGNAL_CREATOR:
        subject = f"comics involving {signal.display_name}"
        if ":writer:" in signal.external_key:
            subject = f"comics written by {signal.display_name}"
        elif ":artist:" in signal.external_key:
            subject = f"comics with art by {signal.display_name}"
        return (
            f"You've rated {subject} well above your usual baseline {reads}. "
            f"Is {signal.display_name} generally a draw for you?"
        )
    return (
        f"You've rated {signal.display_name} issues well above your usual "
        f"baseline {reads}. Do you generally enjoy {signal.display_name}?"
    )


async def list_discoveries(
    db: AsyncSession, *, user_id: int, limit: int = MAX_ACTIVE_DISCOVERIES
) -> TasteDiscoveryListResponse:
    """Return ranked eligible discoveries and record the prompting.

    Args:
        db: Async database session.
        user_id: Authenticated reader id.
        limit: Maximum number of discoveries to return.

    Returns:
        Ranked discoveries with concise evidence context; prompting timestamps
        are persisted so the canonical cooldown applies.
    """
    now = datetime.now(UTC)

    signals = await taste_signals_repository.list_for_user(db, user_id)

    eligibility_inputs: list[EligibilitySignal] = []
    by_stable_key: dict[str, TasteSignal] = {}
    for signal in signals:
        converted = _to_eligibility_signal(signal, now=now)
        if converted is None:
            continue
        eligibility_inputs.append(converted)
        by_stable_key[converted.stable_key] = signal

    result = evaluate_prompt_eligibility(eligibility_inputs)

    discovered: list[TasteDiscovery] = []
    for candidate in result.candidates[:limit]:
        signal = by_stable_key[candidate.signal.stable_key]
        discovered.append(
            TasteDiscovery(
                id=signal.id,
                signal_type=signal.signal_type,
                external_key=signal.external_key,
                display_name=signal.display_name,
                prompt=build_discovery_prompt(signal),
                evidence_count=signal.evidence_count,
                distinct_thread_count=signal.distinct_thread_count,
            )
        )
        signal.last_prompted_at = now

    if discovered:
        await taste_signals_repository.commit(db)

    return TasteDiscoveryListResponse(discoveries=discovered, generated_at=now)


async def dismiss_discovery(
    db: AsyncSession, *, signal_id: int, user_id: int
) -> TasteSignal | None:
    """Dismiss one discovery without recording any verdict.

    Dismissal writes only ``prompt_suppressed_until``; it can therefore never
    count as confirmation.

    Args:
        db: Async database session.
        signal_id: Target signal id.
        user_id: Authenticated owner id.

    Returns:
        The updated signal, or ``None`` when missing or foreign.
    """
    signal = await taste_signals_repository.get_owned(
        db, signal_id=signal_id, user_id=user_id
    )
    if signal is None:
        return None

    signal.prompt_suppressed_until = datetime.now(UTC) + DISMISSAL_SUPPRESSION
    await taste_signals_repository.commit(db)
    return signal


__all__ = [
    "DISMISSAL_SUPPRESSION",
    "DISMISSAL_SUPPRESSION_DAYS",
    "MAX_ACTIVE_DISCOVERIES",
    "build_discovery_prompt",
    "dismiss_discovery",
    "list_discoveries",
]
