"""Central typed ownership validation for graph and library write edges.

Issue #3225 makes reader ownership an enforced property of every graph and
library write boundary instead of an application convention. Catalog identity
is shared between readers (``catalog_issues`` rows after #3220), so a shared
catalog id is never authorization evidence: every check here resolves ownership
through the owning ``threads.user_id``.

Two complementary layers implement the contract:

* this module is the single typed validator every write path funnels through,
  so an API request, a CBL adoption, a migration, and a direct service call
  all reject the same cross-reader edge before any row is persisted;
* ``app/ownership_constraints.py`` holds the PostgreSQL-level enforcement for
  the two edges a foreign key cannot express without changing delete semantics
  (``threads.next_unread_issue_id`` and ``sessions.pending_thread_id``), so
  raw SQL is rejected too.

Polymorphic edges (``tag_assignments``) and cross-table plan membership cannot
use a foreign key at all; those stay application-enforced and are documented in
``docs/READER_OWNERSHIP_CONSISTENCY.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import ownership_consistency_repository

#: Bounds every reported violation list so a preflight report stays small and
#: attachable to a change or a deploy log.
REPORT_ROW_LIMIT = 20


async def ensure_thread_frontier_issue(
    db: AsyncSession,
    *,
    thread_id: int,
    issue_id: int | None,
) -> None:
    """Reject a natural frontier that escapes its own thread.

    ``Thread.next_unread_issue_id`` is the thread's natural frontier. Pointing it
    at an issue of a *different* thread of the *same* reader is invalid even
    though both ids exist and the reader owns both threads; it is also how a
    cross-reader leak starts when the two threads belong to different readers.

    Args:
        db: Database session.
        thread_id: Thread whose frontier is being written.
        issue_id: Proposed frontier issue, or ``None`` to clear the frontier.

    Raises:
        HTTPException: 422 ``frontier_issue_not_in_thread`` when the issue does
            not belong to ``thread_id``.
    """
    if issue_id is None:
        return
    escaped = await ownership_consistency_repository.find_issue_ids_outside_thread(
        db, thread_id=thread_id, issue_ids=[issue_id]
    )
    if escaped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "frontier_issue_not_in_thread",
                "thread_id": thread_id,
                "issue_id": issue_id,
            },
        )


async def ensure_pending_thread_owned(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int | None,
) -> None:
    """Reject a pending reading-session reference to another reader's thread.

    Args:
        db: Database session.
        user_id: Reader that owns the reading session.
        thread_id: Proposed pending thread, or ``None`` to clear it.

    Raises:
        HTTPException: 422 ``pending_thread_not_owned`` when the thread belongs
            to another reader.
    """
    if thread_id is None:
        return
    foreign = await ownership_consistency_repository.find_thread_ids_of_other_readers(
        db, user_id=user_id, thread_ids=[thread_id]
    )
    if foreign:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "pending_thread_not_owned",
                "thread_id": thread_id,
            },
        )


async def ensure_issue_ids_owned(
    db: AsyncSession,
    *,
    user_id: int,
    issue_ids: Sequence[int],
    code: str,
) -> None:
    """Reject references to issues the reader does not own.

    Missing issues and another reader's issues are reported identically so this
    boundary cannot be used as an existence oracle.

    Args:
        db: Database session.
        user_id: Reader that must own every issue.
        issue_ids: Candidate issue primary keys.
        code: Domain error code reported to the client.

    Raises:
        HTTPException: 422 ``<code>`` naming the rejected references.
    """
    unowned = await ownership_consistency_repository.find_unowned_issue_ids(
        db, user_id=user_id, issue_ids=issue_ids
    )
    if unowned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": code,
                "issue_ids": sorted(unowned),
            },
        )


async def reader_ownership_violation_report(
    db: AsyncSession,
    *,
    limit: int = REPORT_ROW_LIMIT,
) -> dict[str, dict[str, Any]]:
    """Report existing reader-ownership violations without private payloads.

    Every section returns a count plus a bounded list of primary keys. Reader
    content (titles, notes, ratings, corrections, tags, events) is never
    selected, so the report is safe to attach to a change or a deploy log.

    Args:
        db: Database session.
        limit: Maximum number of identifying rows per section.

    Returns:
        Mapping of violation class to ``{"count": int, "rows": [...]}``.
    """
    frontier_count = await ownership_consistency_repository.count_frontiers_outside_thread(db)
    pending_thread_count = (
        await ownership_consistency_repository.count_pending_threads_of_other_readers(db)
    )
    return {
        "thread_frontier_outside_thread": {
            "count": frontier_count,
            "rows": await ownership_consistency_repository.list_frontiers_outside_thread(
                db, limit=limit
            ),
        },
        "session_pending_thread_other_reader": {
            "count": pending_thread_count,
            "rows": await ownership_consistency_repository.list_pending_threads_of_other_readers(
                db, limit=limit
            ),
        },
    }