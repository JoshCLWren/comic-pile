"""Bulk loaders for per-thread issue statistics.

These helpers eliminate N+1 query patterns in hot endpoints by loading
unread counts and next-unread issue numbers for many threads in a small
constant number of queries. Single-thread callers may keep using the
convenient ``Thread.get_issues_remaining()`` helper.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread


async def load_unread_counts(threads: list[Thread], db: AsyncSession) -> dict[int, int]:
    """Bulk-load unread issue counts for migrated threads in one grouped query.

    Unmigrated threads (``total_issues`` null) fall back to their stored
    ``issues_remaining`` value and are omitted from the returned map so
    callers can keep the stored counter unchanged.

    Args:
        threads: Threads that may appear in a list response.
        db: Database session.

    Returns:
        Mapping of migrated thread ID to its unread issue count.
    """
    migrated_ids = [t.id for t in threads if t.uses_issue_tracking()]
    if not migrated_ids:
        return {}

    result = await db.execute(
        select(Issue.thread_id, func.count())
        .where(Issue.thread_id.in_(migrated_ids))
        .where(Issue.status == "unread")
        .group_by(Issue.thread_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def load_next_issue_numbers(threads: list[Thread], db: AsyncSession) -> dict[int, str]:
    """Bulk-load next-unread issue numbers for migrated threads in one query.

    Args:
        threads: Threads that may appear in a list response.
        db: Database session.

    Returns:
        Mapping of issue ID to issue number for every referenced next-unread issue.
    """
    issue_ids = {
        t.next_unread_issue_id
        for t in threads
        if t.uses_issue_tracking() and t.next_unread_issue_id is not None
    }
    if not issue_ids:
        return {}

    result = await db.execute(select(Issue.id, Issue.issue_number).where(Issue.id.in_(issue_ids)))
    return {row[0]: row[1] for row in result.all()}
