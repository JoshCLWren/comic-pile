"""Session narrative summary service.

The summary is a historical projection. Its ``snoozed`` section lists only the
series that were still snoozed when the reading session ended; it is not a log
of every snooze action. The detailed event timeline remains the authoritative
record of each individual snooze and unsnooze.
"""

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread
from app.repositories.reading_session_repository import (
    first_start_snapshot,
    get_reading_session,
)
from app.repositories.thread_repository import threads_by_ids

SNOOZE_EVENT_TYPES = frozenset({"snooze", "unsnooze"})


def _event_thread_id(event: Event) -> int | None:
    """Return the series an event refers to.

    A dismissal names the cancelled roll through ``selected_thread_id``: that
    column carries no foreign key, so the dismissal stays readable after the
    series is deleted (#3763).

    Args:
        event: Session event to inspect.

    Returns:
        The referenced thread ID, or None when the event names no series.
    """
    if event.type == "dismiss":
        return event.selected_thread_id
    return event.thread_id


def _recorded_start_snoozes(snapshot: Snapshot | None) -> list[int]:
    """Return the snoozed thread IDs captured by a session-start snapshot.

    New session-start snapshots record the session-scoped snooze set that was
    in force when the session began. Older snapshots predate that field, so an
    absent or malformed value falls back to the empty set: a reading session is
    created with no session-scoped snoozes, and every later snooze is durable in
    the event stream.

    Args:
        snapshot: Earliest "Session start" snapshot for the session, or None.

    Returns:
        Recorded thread IDs, or an empty list when no trustworthy start state
        exists.
    """
    if snapshot is None or not isinstance(snapshot.session_state, dict):
        return []
    raw_ids = snapshot.session_state.get("snoozed_thread_ids")
    if not isinstance(raw_ids, list):
        return []
    return [
        thread_id
        for thread_id in raw_ids
        if isinstance(thread_id, int) and not isinstance(thread_id, bool)
    ]


def project_still_snoozed_thread_ids(
    *,
    start_thread_ids: Iterable[int],
    events: Sequence[Event],
) -> list[int]:
    """Project the snooze set in force at a historical session boundary.

    The projection starts from recorded session state and replays the session's
    own ordered snooze/unsnooze actions. It never reads today's Queue, later
    sessions, or another reader's state, and it never mutates an event.

    Replaying over a persisted end state is safe for a toggle set: the last
    recorded action for a series determines its membership, and series with no
    recorded action keep the membership they already had. That lets the same
    helper handle both an authoritative live/end snapshot and a recorded
    session-start state.

    Args:
        start_thread_ids: Series snoozed at the projection's starting state.
        events: The session's events in ``(timestamp, id)`` order.

    Returns:
        Sorted thread IDs still snoozed at the session boundary.
    """
    still_snoozed = set(start_thread_ids)

    for event in events:
        if event.type not in SNOOZE_EVENT_TYPES:
            continue
        thread_id = event.thread_id
        if thread_id is None:
            continue
        if event.type == "snooze":
            still_snoozed.add(thread_id)
        else:
            still_snoozed.discard(thread_id)

    return sorted(still_snoozed)


async def build_narrative_summary(session_id: int, db: AsyncSession) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events.

    Read/skipped/completed entries remain action records. The ``snoozed``
    section is a different kind of projection: it contains only the series
    still snoozed at the session's end. The UI labels it "Still snoozed at
    end" so it cannot be mistaken for a count of snooze events.

    Args:
        session_id: The session ID to build summary for.
        db: Database session.

    Returns:
        Dictionary with keys "read", "skipped", "snoozed", and "completed",
        each containing a list of formatted strings.
    """
    events_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .order_by(Event.timestamp, Event.id)
    )
    events = events_result.scalars().all()

    # Net undo events against rate events. Each undo reverts the most recent
    # not-yet-undone rate before it. Live snapshots cannot identify undone
    # rates: delta undo snapshots are deleted when applied, so the undo event
    # stream is the durable record of what was reverted.
    undone_rate_ids: set[int] = set()
    open_rate_ids: list[int] = []
    for event in events:
        if event.type == "rate":
            open_rate_ids.append(event.id)
        elif event.type == "undo" and open_rate_ids:
            undone_rate_ids.add(open_rate_ids.pop())

    summary = {
        "read": [],
        "skipped": [],
        "snoozed": [],
        "completed": [],
    }

    read_entries = []
    skipped_titles = set()
    completed_titles = set()

    # The persisted snooze column is the authoritative live/end state whenever
    # it was not cleared. Sessions finished through the rate flow clear it, so
    # those rebuild from the recorded start state instead. Replaying the
    # session's ordered actions over either base resolves the boundary state
    # without reading today's Queue.
    reading_session = await get_reading_session(db, session_id)
    if reading_session is not None and reading_session.snoozed_thread_ids is not None:
        base_snoozed_ids: list[int] = [
            thread_id
            for thread_id in reading_session.snoozed_thread_ids
            if isinstance(thread_id, int) and not isinstance(thread_id, bool)
        ]
    else:
        start_snapshot = (
            await first_start_snapshot(db, session_id) if reading_session is not None else None
        )
        base_snoozed_ids = _recorded_start_snoozes(start_snapshot)

    still_snoozed_ids = project_still_snoozed_thread_ids(
        start_thread_ids=base_snoozed_ids,
        events=events,
    )

    # Still-snoozed series usually have no event naming them on the boundary,
    # so their IDs must join the event-derived set before titles are resolved.
    thread_ids = {thread_id for thread_id in (_event_thread_id(e) for e in events) if thread_id}
    thread_ids.update(still_snoozed_ids)
    threads_dict: dict[int, Thread] = await threads_by_ids(db, thread_ids)

    # Scope state and titles to the reader who owns the session. A malformed
    # event that points at another reader's series must not leak that title or
    # state.
    if reading_session is not None:
        still_snoozed_ids = [
            thread_id
            for thread_id in still_snoozed_ids
            if thread_id not in threads_dict
            or threads_dict[thread_id].user_id == reading_session.user_id
        ]

    still_snoozed_titles = {
        threads_dict[thread_id].title if thread_id in threads_dict else f"Thread #{thread_id}"
        for thread_id in still_snoozed_ids
    }

    for event in events:
        thread_id = _event_thread_id(event)
        thread = threads_dict.get(thread_id) if thread_id else None
        title = thread.title if thread else f"Thread #{thread_id}"
        issue_suffix = f" #{event.issue_number}" if event.issue_number else ""

        if event.type == "rate" and event.id not in undone_rate_ids:
            read_entries.append(f"{title}{issue_suffix} ({event.rating}/5.0)")
            if thread and thread.status == "completed":
                completed_titles.add(f"{title}{issue_suffix}")
        elif event.type == "rolled_but_skipped":
            skipped_titles.add(f"{title}{issue_suffix}")
        elif event.type == "dismiss":
            # A cancelled pending roll is an abandoned series, so it is
            # classified with the skipped ones (#3763).
            skipped_titles.add(f"{title}{issue_suffix}")

    summary["read"] = read_entries
    summary["skipped"] = sorted(skipped_titles)
    summary["snoozed"] = sorted(still_snoozed_titles)
    summary["completed"] = sorted(completed_titles)

    return summary
