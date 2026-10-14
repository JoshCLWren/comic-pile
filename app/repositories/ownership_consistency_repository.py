"""Read-only ownership-consistency queries for graph and library write edges.

Issue #3225 makes reader ownership an enforced property of every graph and
library write boundary instead of an application convention. Catalog identity
(``catalog_issues`` rows, shared between readers after #3220) is never
authorization evidence, so every query here resolves ownership through the
owning ``threads.user_id``.

The query set is deliberately split in two:

* ``count_*`` / ``list_*`` helpers back the read-only preflight that reports
  existing violations before a constraint is introduced. They return counts and
  primary keys only, never private reader content (titles, notes, ratings,
  events), so a report can be attached to a change or a deploy log safely.
* ``find_*`` helpers back the central service validators that reject a write
  before any row is persisted.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.reading_session import ReadingSession
from app.models.thread import Thread

#: Maximum number of identifying rows a report may return. Preflight output is
#: meant to be attachable to a change or a deploy log, so it stays bounded.
DEFAULT_REPORT_LIMIT = 20


async def count_frontiers_outside_thread(db: AsyncSession) -> int:
    """Count threads whose ``next_unread_issue_id`` is another thread's issue.

    Args:
        db: Database session.

    Returns:
        Number of threads whose natural frontier escapes their own thread.
    """
    result = await db.execute(
        select(func.count())
        .select_from(Thread)
        .join(Issue, Issue.id == Thread.next_unread_issue_id)
        .where(Issue.thread_id != Thread.id)
    )
    return int(result.scalar() or 0)


async def list_frontiers_outside_thread(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_REPORT_LIMIT,
) -> list[tuple[int, int, int, int]]:
    """List identifying rows for frontiers that escape their own thread.

    Args:
        db: Database session.
        limit: Maximum number of rows to return.

    Returns:
        ``(thread_id, user_id, next_unread_issue_id, owning_thread_id)`` tuples.
        No reader content is returned.
    """
    result = await db.execute(
        select(Thread.id, Thread.user_id, Thread.next_unread_issue_id, Issue.thread_id)
        .join(Issue, Issue.id == Thread.next_unread_issue_id)
        .where(Issue.thread_id != Thread.id)
        .order_by(Thread.id)
        .limit(limit)
    )
    return [
        (int(row[0]), int(row[1]), int(row[2]), int(row[3])) for row in result.all()
    ]


async def count_pending_threads_of_other_readers(db: AsyncSession) -> int:
    """Count reading sessions whose ``pending_thread_id`` belongs to another reader.

    Args:
        db: Database session.

    Returns:
        Number of reading sessions pointing at a foreign reader's thread.
    """
    result = await db.execute(
        select(func.count())
        .select_from(ReadingSession)
        .join(Thread, Thread.id == ReadingSession.pending_thread_id)
        .where(Thread.user_id != ReadingSession.user_id)
    )
    return int(result.scalar() or 0)


async def list_pending_threads_of_other_readers(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_REPORT_LIMIT,
) -> list[tuple[int, int, int, int]]:
    """List identifying rows for pending threads owned by another reader.

    Args:
        db: Database session.
        limit: Maximum number of rows to return.

    Returns:
        ``(session_id, session_user_id, pending_thread_id, thread_user_id)``
        tuples. No reader content is returned.
    """
    result = await db.execute(
        select(
            ReadingSession.id,
            ReadingSession.user_id,
            ReadingSession.pending_thread_id,
            Thread.user_id,
        )
        .join(Thread, Thread.id == ReadingSession.pending_thread_id)
        .where(Thread.user_id != ReadingSession.user_id)
        .order_by(ReadingSession.id)
        .limit(limit)
    )
    return [
        (int(row[0]), int(row[1]), int(row[2]), int(row[3])) for row in result.all()
    ]


async def find_unowned_issue_ids(
    db: AsyncSession,
    *,
    user_id: int,
    issue_ids: Sequence[int],
) -> set[int]:
    """Return the issue IDs the reader may not reference.

    An issue is owned when its thread belongs to ``user_id``. A missing issue
    row and an issue owned by another reader are both unusable, and both are
    reported without distinguishing them in the message so the write boundary
    cannot be used as an existence oracle.

    Args:
        db: Database session.
        user_id: Reader that must own every issue.
        issue_ids: Candidate issue primary keys.

    Returns:
        The subset of ``issue_ids`` that is missing or owned by another reader.
    """
    if not issue_ids:
        return set()
    result = await db.execute(
        select(Issue.id, Thread.user_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(issue_ids))
    )
    owner_by_issue = {int(row[0]): int(row[1]) for row in result.all()}
    return {
        issue_id
        for issue_id in issue_ids
        if owner_by_issue.get(issue_id) != user_id
    }


async def find_issue_ids_outside_thread(
    db: AsyncSession,
    *,
    thread_id: int,
    issue_ids: Sequence[int],
) -> set[int]:
    """Return the issue IDs that do not belong to the given thread.

    Args:
        db: Database session.
        thread_id: Thread that must own every candidate issue.
        issue_ids: Candidate issue primary keys.

    Returns:
        The subset of ``issue_ids`` owned by a different thread. Missing issues
        are not reported here; the referencing column's own foreign key covers
        existence.
    """
    if not issue_ids:
        return set()
    result = await db.execute(
        select(Issue.id).where(Issue.id.in_(issue_ids), Issue.thread_id != thread_id)
    )
    return set(result.scalars().all())


async def find_thread_ids_of_other_readers(
    db: AsyncSession,
    *,
    user_id: int,
    thread_ids: Sequence[int],
) -> set[int]:
    """Return the thread IDs that belong to another reader.

    Args:
        db: Database session.
        user_id: Reader that must own every thread.
        thread_ids: Candidate thread primary keys.

    Returns:
        The subset of ``thread_ids`` owned by a different reader.
    """
    if not thread_ids:
        return set()
    result = await db.execute(
        select(Thread.id).where(Thread.id.in_(thread_ids), Thread.user_id != user_id)
    )
    return set(result.scalars().all())