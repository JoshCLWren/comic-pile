"""Linear event projection for session-history summaries."""

from collections.abc import Iterable
from dataclasses import dataclass

from app.models import Event
from comic_pile.dice_ladder import automatic_die_after

#: Event types that move the reading die. A dismissal is not one of them: it
#: clears the pending roll without changing the die, so it never carries a
#: ``die_after`` and never belongs on the die ladder.
_DIE_EVENT_TYPES = frozenset({"rate", "snooze", "undo"})


@dataclass(frozen=True, slots=True)
class SessionHistoryEventProjection:
    """Precomputed event-derived values for a bounded History page."""

    latest_roll_by_session: dict[int, Event]
    die_path_by_session: dict[int, tuple[int, ...]]
    latest_die_by_session: dict[int, int]
    issue_by_session_thread: dict[tuple[int, int], tuple[int | None, str | None]]


def _record_issue_identity(
    issue_by_session_thread: dict[tuple[int, int], tuple[int | None, str | None]],
    session_id: int,
    thread_id: int,
    event: Event,
) -> None:
    """Remember the issue identity an event recorded for one thread.

    A History card shows one series with one issue number, so the issue must
    belong to the same thread the card names. Keying the remembered identity by
    ``(session_id, thread_id)`` keeps a rating of one series from lending its
    issue number to another series rolled in the same session (#3763).

    Args:
        issue_by_session_thread: Map updated in place with the event's identity.
        session_id: Session the event belongs to.
        thread_id: Thread the event references.
        event: Event carrying the recorded issue identity.
    """
    if event.issue_id is None and event.issue_number is None:
        return
    issue_by_session_thread[(session_id, thread_id)] = (event.issue_id, event.issue_number)


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
        Constant-time maps for latest rolls, chronological die paths, the
        latest event-derived die value, and the issue identity each thread
        recorded inside a session.
    """
    included_session_ids = set(session_ids)
    latest_roll_by_session: dict[int, Event] = {}
    die_path_lists: dict[int, list[int]] = {
        session_id: [] for session_id in included_session_ids
    }
    latest_die_by_session: dict[int, int] = {}
    issue_by_session_thread: dict[tuple[int, int], tuple[int | None, str | None]] = {}

    for event in events:
        session_id = event.session_id
        if session_id is None or session_id not in included_session_ids:
            continue

        if event.type == "roll" and event.selected_thread_id is not None:
            latest_roll_by_session[session_id] = event
            _record_issue_identity(
                issue_by_session_thread, session_id, event.selected_thread_id, event
            )
        elif event.type == "rate" and event.thread_id is not None:
            # Rate identity only contributes when no roll for this thread in this
            # session has already established the shown issue (#3708).
            key = (session_id, event.thread_id)
            if key not in issue_by_session_thread:
                _record_issue_identity(
                    issue_by_session_thread, session_id, event.thread_id, event
                )

        if event.type in _DIE_EVENT_TYPES and event.die_after is not None:
            die_path_lists[session_id].append(event.die_after)
            latest_die_by_session[session_id] = automatic_die_after(event.die_after, event.context)

    return SessionHistoryEventProjection(
        latest_roll_by_session=latest_roll_by_session,
        die_path_by_session={
            session_id: tuple(die_values)
            for session_id, die_values in die_path_lists.items()
        },
        latest_die_by_session=latest_die_by_session,
        issue_by_session_thread=issue_by_session_thread,
    )


def resolve_history_issue_identity(
    projection: SessionHistoryEventProjection,
    session_id: int,
    thread_id: int,
) -> tuple[int | None, str | None] | None:
    """Return the issue identity a session recorded for one thread.

    The remembered identity comes from the latest event in the session that
    named this thread and carried an issue: the roll that offered the issue or
    the rating that read it. Events about other threads never contribute, so a
    card naming one series never shows another series' issue number (#3763).

    Args:
        projection: Projection built from the page's ordered events.
        session_id: Session the History row belongs to.
        thread_id: Thread the History row names.

    Returns:
        The recorded ``(issue_id, issue_number)`` pair, or None when the
        session recorded no issue for that thread.
    """
    return projection.issue_by_session_thread.get((session_id, thread_id))
