"""Session narrative summary service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Thread


async def build_narrative_summary(session_id: int, db: AsyncSession) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events."""
    events_result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    events = events_result.scalars().all()

    # Identify rate events that have been undone via snapshots.
    # Snapshots store event_id referencing the event they were based on;
    # if that event was a rate event, the rate was undone.
    snapshots_result = await db.execute(
        select(Snapshot).where(Snapshot.session_id == session_id)
    )
    snapshots = snapshots_result.scalars().all()

    rate_event_ids = {event.id for event in events if event.type == "rate"}
    undone_rate_ids = {
        snapshot.event_id
        for snapshot in snapshots
        if snapshot.event_id is not None and snapshot.event_id in rate_event_ids
    }

    summary = {
        "read": [],
        "skipped": [],
        "completed": [],
    }

    read_entries = []
    skipped_titles = set()
    completed_titles = set()

    thread_ids = {event.thread_id for event in events if event.thread_id}
    if thread_ids:
        threads_result = await db.execute(
            select(Thread).where(Thread.id.in_(thread_ids))
        )
        threads_dict = {thread.id: thread for thread in threads_result.scalars().all()}

    for event in events:
        thread = threads_dict.get(event.thread_id) if event.thread_id else None
        title = thread.title if thread else f"Thread #{event.thread_id}"
        issue_suffix = f" #{event.issue_number}" if event.issue_number else ""

        if event.type == "rate" and event.id not in undone_rate_ids:
            read_entries.append(f"{title}{issue_suffix} ({event.rating}/5.0)")
            if thread and thread.status == "completed":
                completed_titles.add(f"{title}{issue_suffix}")
        elif event.type == "rolled_but_skipped":
            skipped_titles.add(f"{title}{issue_suffix}")

    summary["read"] = read_entries
    summary["skipped"] = sorted(skipped_titles)
    summary["completed"] = sorted(completed_titles)

    return summary