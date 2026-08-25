"""Read-only roll-to-rating decision latency derivation.

Derives how much time elapsed between the dice offering a thread (``roll``)
and the reader rating that reading session (``rate``). Latencies come
exclusively from the explicit Phase 0 source-roll linkage stored on
``Event.source_roll_event_id``, never from event-order heuristics, so later
reading-effort aggregation can trust every emitted observation.

Unlinked legacy outcomes are tolerated and simply skipped; a separate,
clearly quarantined compatibility fallback exists for callers that must
estimate latencies from legacy data, and its output is never mixed into the
trustworthy linked dataset.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event

_LATENCY_SOURCE_EVENT_TYPES = frozenset({"roll", "rate"})


@dataclass(frozen=True, slots=True)
class RollRateLatency:
    """Deterministic elapsed time between one roll and its linked rate event.

    Attributes:
        session_id: Reading session the paired events belong to, if any.
        thread_id: Thread rated by the linked rate event, if still present.
        issue_id: Issue recorded by the linked rate event, if tracked.
        issue_number: Denormalized issue number recorded at rate time.
        roll_event_id: ID of the originating roll event.
        rate_event_id: ID of the linked rate event.
        rolled_at: Timestamp of the originating roll event.
        rated_at: Timestamp of the linked rate event.
        elapsed_seconds: Signed seconds between roll and rate.
        elapsed_minutes: ``elapsed_seconds`` expressed in minutes.
    """

    session_id: int | None
    thread_id: int | None
    issue_id: int | None
    issue_number: str | None
    roll_event_id: int
    rate_event_id: int
    rolled_at: datetime
    rated_at: datetime
    elapsed_seconds: float
    elapsed_minutes: float


def _latency_from_linked_pair(roll_event: Event, rate_event: Event) -> RollRateLatency:
    """Build one latency record from an explicitly linked roll/rate pair."""
    rolled_at = roll_event.timestamp
    rated_at = rate_event.timestamp
    elapsed_seconds = (rated_at - rolled_at).total_seconds()
    return RollRateLatency(
        session_id=rate_event.session_id,
        thread_id=rate_event.thread_id,
        issue_id=rate_event.issue_id,
        issue_number=rate_event.issue_number,
        roll_event_id=roll_event.id,
        rate_event_id=rate_event.id,
        rolled_at=rolled_at,
        rated_at=rated_at,
        elapsed_seconds=elapsed_seconds,
        elapsed_minutes=elapsed_seconds / 60,
    )


def derive_roll_rate_latencies(events: Iterable[Event]) -> list[RollRateLatency]:
    """Derive deterministic latencies from explicitly linked roll/rate pairs.

    Only rate events carrying a non-null ``source_roll_event_id`` that resolves
    to a roll event in the provided dataset produce records. Unlinked legacy
    outcomes, dangling links, snoozes, and unrelated event types are ignored
    without fabricating links. Events must be persisted (or carry explicit
    IDs) so links can resolve.

    Args:
        events: Persisted events in any order.

    Returns:
        Latency observations ordered chronologically by rate timestamp with
        event-ID tie-breaking for deterministic output.
    """
    rolls_by_id = {
        event.id: event for event in events if event.type == "roll" and event.id is not None
    }
    latencies = [
        _latency_from_linked_pair(rolls_by_id[rate.source_roll_event_id], rate)
        for rate in events
        if (
            rate.type == "rate"
            and rate.id is not None
            and rate.source_roll_event_id is not None
            and rate.source_roll_event_id in rolls_by_id
        )
    ]
    latencies.sort(key=lambda item: (item.rated_at, item.rate_event_id))
    return latencies


def derive_legacy_order_fallback_latencies(events: Iterable[Event]) -> list[RollRateLatency]:
    """Estimate latencies for unlinked legacy outcomes via event ordering.

    Compatibility fallback for datasets written before Phase 0 linkage. Each
    rate event without an explicit link is paired with the most recent prior
    roll event in the same session using ``(timestamp, id)`` order. This is a
    heuristic estimate: it must never be mixed into the trustworthy linked
    dataset returned by :func:`derive_roll_rate_latencies`.

    Args:
        events: Persisted events in any order.

    Returns:
        Fallback latency estimates ordered like
        :func:`derive_roll_rate_latencies`, covering only unlinked rates.
    """
    rolls_by_session: dict[int | None, Event] = {}
    latencies: list[RollRateLatency] = []
    for event in sorted(events, key=lambda item: (item.timestamp, item.id or 0)):
        if event.type == "roll":
            rolls_by_session[event.session_id] = event
            continue

        if event.type != "rate" or event.id is None or event.source_roll_event_id is not None:
            continue

        latest_roll = rolls_by_session.get(event.session_id)
        if latest_roll is None:
            continue
        latencies.append(_latency_from_linked_pair(latest_roll, event))

    latencies.sort(key=lambda item: (item.rated_at, item.rate_event_id))
    return latencies


async def load_decision_latency_events(
    db: AsyncSession,
    *,
    session_ids: Sequence[int] | None = None,
) -> list[Event]:
    """Load the persisted roll and rate events needed for latency derivation.

    Read-only helper that fetches only the two event types participating in
    decision-latency derivation, optionally bounded to specific sessions.

    Args:
        db: Database session used exclusively for reads.
        session_ids: Optional allow-list of reading sessions. ``None`` loads
            every session; an empty sequence loads nothing.

    Returns:
        Roll and rate events ordered by event ID.
    """
    stmt = select(Event).where(Event.type.in_(frozenset(_LATENCY_SOURCE_EVENT_TYPES)))
    if session_ids is not None:
        if not session_ids:
            return []
        stmt = stmt.where(Event.session_id.in_(session_ids))
    stmt = stmt.order_by(Event.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def derive_decision_latencies(
    db: AsyncSession,
    *,
    session_ids: Sequence[int] | None = None,
) -> list[RollRateLatency]:
    """Load linked decision events and derive their trusted latencies.

    Args:
        db: Database session used exclusively for reads.
        session_ids: Optional allow-list of reading sessions passed through to
            :func:`load_decision_latency_events`.

    Returns:
        Trusted linked roll-to-rate latency observations.
    """
    events = await load_decision_latency_events(db, session_ids=session_ids)
    return derive_roll_rate_latencies(events)
