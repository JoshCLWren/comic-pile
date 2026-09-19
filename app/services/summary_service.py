"""Session narrative summary service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread


async def build_narrative_summary(session_id: int, db: AsyncSession) -> dict[str, list[str]]:
    """Build narrative summary categorizing session events."""
    events_result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    events = events_result.scalars().all()

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

        if event.type == "rate":
            read_entries.append(f"{title}{issue_suffix} ({event.rating}/5.0)")
            if thread and thread.status == "completed":
                completed_titles.add(f"{title}{issue_suffix}")
        elif event.type == "rolled_but_skipped":
            skipped_titles.add(f"{title}{issue_suffix}")

    summary["read"] = read_entries
    summary["skipped"] = sorted(skipped_titles)
    summary["completed"] = sorted(completed_titles)

    return summary