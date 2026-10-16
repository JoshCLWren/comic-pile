"""Bulk loaders for per-thread issue statistics.

These helpers eliminate N+1 query patterns in hot endpoints by loading
unread counts and next-unread issue numbers for many threads in a small
constant number of queries. Single-thread callers may keep using the
convenient ``Thread.get_issues_remaining()`` helper.
"""

from sqlalchemy import func, or_, select
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


async def load_issue_stats(
    threads: list[Thread], db: AsyncSession
) -> tuple[dict[int, int], dict[int, str]]:
    """Bulk-load unread counts and next-unread numbers in a single query.

    This is the combined form of :func:`load_unread_counts` and
    :func:`load_next_issue_numbers` for hot list paths such as
    ``GET /api/v1/threads`` (issue #3463): the two sequential reads cost one
    pooled round trip each on the size-2/no-overflow production pool, so the
    queue page resolves both maps with one ``SELECT``.

    The result is exactly equivalent to calling both single-purpose loaders:
    unread counts cover migrated threads with at least one unread issue
    (callers default missing threads to zero), and the number map resolves
    every referenced ``next_unread_issue_id`` that still exists, whatever its
    status. Only unread rows plus the referenced pointer rows are fetched, so
    already-read back-catalog rows never cross the wire.

    Args:
        threads: Threads that may appear in a list response.
        db: Database session.

    Returns:
        Tuple of (thread ID to unread count, issue ID to issue number).
    """
    migrated = [t for t in threads if t.uses_issue_tracking()]
    if not migrated:
        return {}, {}
    migrated_ids = [t.id for t in migrated]
    pointer_ids = {
        t.next_unread_issue_id for t in migrated if t.next_unread_issue_id is not None
    }
    unread_rows = (Issue.thread_id.in_(migrated_ids)) & (Issue.status == "unread")
    if pointer_ids:
        predicate = or_(unread_rows, Issue.id.in_(pointer_ids))
    else:
        predicate = unread_rows
    result = await db.execute(
        select(Issue.id, Issue.thread_id, Issue.issue_number, Issue.status).where(predicate)
    )
    unread_counts: dict[int, int] = {}
    numbers: dict[int, str] = {}
    for issue_id, thread_id, issue_number, status in result.all():
        if issue_id in pointer_ids:
            numbers[issue_id] = issue_number
        if status == "unread":
            unread_counts[thread_id] = unread_counts.get(thread_id, 0) + 1
    return unread_counts, numbers
