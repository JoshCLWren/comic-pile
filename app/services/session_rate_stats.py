"""Undo-aware reading totals for reading-session cards.

A session card reports how many issues the session read and the most recent
rating the reader gave. Undo cancels the newest reading, so those totals must
be replayed from the ordered rate/undo event stream instead of summing every
stored rate event (#3195, #3708).

The rule lives in this one service so the session card and the History card
cannot drift apart. Query construction stays in
:mod:`app.repositories.rate_repository`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.repositories import rate_repository

#: ``(total_issues_read, last_rating)`` for one reading session.
type SessionRateStats = tuple[int, float | None]


def _last_open_rating(active_rates: Sequence[Event]) -> float | None:
    """Return the newest surviving rating in the open-reading stack.

    Args:
        active_rates: Open rate events, oldest first.

    Returns:
        The rating of the newest open reading that recorded one, or None when
        no open reading has a rating. A read-without-rating does not erase an
        earlier rating the reader still stands behind.
    """
    for event in reversed(active_rates):
        if event.rating is not None:
            return event.rating
    return None


def aggregate_session_rate_stats(
    events: Iterable[Event],
    session_ids: Iterable[int],
) -> dict[int, SessionRateStats]:
    """Aggregate undo-aware reading totals for the supplied sessions.

    Events must be ordered by ``(session_id, timestamp, id)``. Each undo
    cancels the newest reading still open in that session, so canceling a
    later rating leaves the earlier count and rating intact.

    Args:
        events: Ordered rate and undo events.
        session_ids: Sessions to report on. Sessions without events report
            ``(0, None)``.

    Returns:
        Mapping of session ID to ``(total_issues_read, last_rating)``.
    """
    events_by_session: dict[int, list[Event]] = {}
    for event in events:
        event_session_id = event.session_id
        if event_session_id is None:
            continue
        events_by_session.setdefault(event_session_id, []).append(event)

    stats: dict[int, SessionRateStats] = {}
    for session_id in session_ids:
        total_issues_read = 0
        # Ordered stack of open readings, oldest first. The newest reading is
        # the last entry, so an undo cancels the most recent one instead of an
        # arbitrary member, which kept the wrong count and rating (#3195).
        active_rates: list[Event] = []

        for event in events_by_session.get(session_id, []):
            if event.type == "rate":
                active_rates.append(event)
                if event.issues_read is not None:
                    total_issues_read += event.issues_read
            elif event.type == "undo" and active_rates:
                undone = active_rates.pop()
                if undone.issues_read is not None:
                    total_issues_read = max(0, total_issues_read - undone.issues_read)

        stats[session_id] = (total_issues_read, _last_open_rating(active_rates))

    return stats


async def load_session_rate_stats(
    db: AsyncSession,
    session_id: int,
) -> SessionRateStats:
    """Load undo-aware reading totals for one session.

    Args:
        db: Database session.
        session_id: Reading session to report on.

    Returns:
        ``(total_issues_read, last_rating)``.
    """
    events = await rate_repository.fetch_rate_and_undo_events(db, [session_id])
    return aggregate_session_rate_stats(events, [session_id]).get(session_id, (0, None))
