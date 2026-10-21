"""Session narrative summary service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread


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


async def build_narrative_summary(session_id: int, db: AsyncSession) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events.

    Args:
        session_id: The session ID to build summary for.
        db: Database session.

    Returns:
        Dictionary with keys "read", "skipped", and "completed", each containing
        a list of formatted strings.
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
    snoozed_titles = set()
    completed_titles = set()

    thread_ids = {thread_id for thread_id in (_event_thread_id(e) for e in events) if thread_id}
    threads_dict: dict[int, Thread] = {}
    if thread_ids:
        threads_result = await db.execute(
            select(Thread).where(Thread.id.in_(thread_ids))
        )
        threads_dict = {thread.id: thread for thread in threads_result.scalars().all()}

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
        elif event.type == "snooze":
            snoozed_titles.add(f"{title}{issue_suffix}")

    summary["read"] = read_entries
    summary["skipped"] = sorted(skipped_titles)
    summary["snoozed"] = sorted(snoozed_titles)
    summary["completed"] = sorted(completed_titles)

    return summary
