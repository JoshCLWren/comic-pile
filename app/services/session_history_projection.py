"""Linear event projection for session-history summaries."""

from collections.abc import Iterable
from dataclasses import dataclass

from app.models import Event

_DIE_EVENT_TYPES = frozenset({"rate", "snooze", "undo"})


@dataclass(frozen=True, slots=True)
class SessionHistoryEventProjection:
    """Precomputed event-derived values for a bounded History page."""

    latest_roll_by_session: dict[int, Event]
    die_path_by_session: dict[int, tuple[int, ...]]
    latest_die_by_session: dict[int, int]


def project_session_history_events(
    session_ids: Iterable[int],
    events: Iterable[Event],
) -> SessionHistoryEventProjection:
    """Project ordered History events into constant-time session lookups.

    Events must be ordered by ``(session_id, timestamp, id)``. Later events
    overwrite earlier latest-event values, which gives deterministic event-ID
    precedence when timestamps are equal.

    Args:
        session_ids: Session IDs included in the bounded History page.
        events: Events ordered by session ID, timestamp, and event ID.

    Returns:
        Constant-time maps for latest rolls, chronological die paths, and the
        latest event-derived die value.
    """
    included_session_ids = set(session_ids)
    latest_roll_by_session: dict[int, Event] = {}
    die_path_lists: dict[int, list[int]] = {
        session_id: [] for session_id in included_session_ids
    }
    latest_die_by_session: dict[int, int] = {}

    for event in events:
        session_id = event.session_id
        if session_id not in included_session_ids:
            continue

        if event.type == "roll" and event.selected_thread_id is not None:
            latest_roll_by_session[session_id] = event

        if event.type in _DIE_EVENT_TYPES and event.die_after is not None:
            die_path_lists[session_id].append(event.die_after)
            latest_die_by_session[session_id] = event.die_after

    return SessionHistoryEventProjection(
        latest_roll_by_session=latest_roll_by_session,
        die_path_by_session={
            session_id: tuple(die_values)
            for session_id, die_values in die_path_lists.items()
        },
        latest_die_by_session=latest_die_by_session,
    )
