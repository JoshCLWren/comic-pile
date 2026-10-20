"""Regression coverage for the read-frontier blocking fix (#3590).

A thread whose ``next_unread_issue_id`` points at an issue the reader already
finished cannot be blocked by an unread prerequisite: the reader has nothing
left to wait for. The prod report showed a 100%-read series still listed as
"Blocked series" in Queue and in the Roll waiting list while its own thread
page listed no explicit series prerequisites.

These tests pin every surface the fix touches:

* the canonical evaluator (``_get_blocked_thread_ids_uncached``),
* both stored-flag refresh paths (per user and all users),
* the single and batch blocking explanations the Queue renders,
* and a genuinely blocked thread whose frontier issue is still unread.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.blocked_flag_refresh import refresh_all_users_blocked_status_async
from comic_pile import dependencies
from comic_pile.dependencies import (
    get_blocking_explanations,
    get_blocking_explanations_batch,
    refresh_user_blocked_status,
)
from tests.conftest import get_or_create_user_async


async def _thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    issue_status: str = "unread",
    is_blocked: bool = False,
) -> tuple[Thread, Issue]:
    """Insert an active thread whose frontier is a single issue."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        queue_position=queue_position,
        status="active",
        issues_remaining=0 if issue_status == "read" else 1,
        total_issues=1,
        reading_progress="completed" if issue_status == "read" else "unstarted",
        is_blocked=is_blocked,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status=issue_status,
        read_at=datetime.now(UTC) if issue_status == "read" else None,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()
    return thread, issue


async def _stored_flags(db: AsyncSession) -> dict[int, bool]:
    """Return every thread's stored blocked flag."""
    result = await db.execute(select(Thread.id, Thread.is_blocked))
    return {row.id: row.is_blocked for row in result.all()}


@pytest.mark.asyncio
async def test_read_frontier_issue_never_blocks_its_thread(async_db: AsyncSession) -> None:
    """A read frontier clears the stale flag on every surface.

    The reader finished the frontier issue, so an unread prerequisite no
    longer blocks the thread. The stored flag, the canonical evaluator, the
    single explanation and the batch explanation must all agree.
    """
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_with_issue(
        async_db,
        user_id=user.id,
        title="Unread Prerequisite",
        queue_position=1,
    )
    target_thread, target_issue = await _thread_with_issue(
        async_db,
        user_id=user.id,
        title="Read Frontier",
        queue_position=2,
        issue_status="read",
        is_blocked=True,
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note=None,
        )
    )
    await async_db.commit()

    assert target_thread.next_unread_issue_id == target_issue.id
    assert target_issue.status == "read"

    blocked_ids = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked_ids

    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []
    batched = await get_blocking_explanations_batch([target_thread.id], user.id, async_db)
    assert batched[target_thread.id] == []

    # The per-user refresh path clears the stale stored flag.
    changes = await refresh_user_blocked_status(user.id, async_db)
    assert changes == {target_thread.id: True}
    flags = await _stored_flags(async_db)
    assert flags[target_thread.id] is False
    assert flags[source_thread.id] is False

    # The all-users refresh path (the migration helper) clears it too.
    await async_db.execute(
        update(Thread).where(Thread.id == target_thread.id).values(is_blocked=True)
    )
    await async_db.commit()
    assert (await _stored_flags(async_db))[target_thread.id] is True

    changed = await refresh_all_users_blocked_status_async(async_db)
    assert changed == {user.id: 1}
    assert (await _stored_flags(async_db))[target_thread.id] is False

    # A second refresh is a no-op.
    assert await refresh_all_users_blocked_status_async(async_db) == {}


@pytest.mark.asyncio
async def test_unread_frontier_issue_still_blocks_its_thread(async_db: AsyncSession) -> None:
    """The fix does not weaken blocking for a frontier the reader still owes."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_with_issue(
        async_db,
        user_id=user.id,
        title="Unread Prerequisite",
        queue_position=1,
    )
    target_thread, target_issue = await _thread_with_issue(
        async_db,
        user_id=user.id,
        title="Unread Frontier",
        queue_position=2,
        issue_status="unread",
        is_blocked=True,
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note=None,
        )
    )
    await async_db.commit()

    blocked_ids = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked_ids

    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert [reason.label for reason in reasons] == ["Blocked by Unread Prerequisite: #1"]
    batched = await get_blocking_explanations_batch([target_thread.id], user.id, async_db)
    assert [reason.label for reason in batched[target_thread.id]] == [
        "Blocked by Unread Prerequisite: #1"
    ]

    await refresh_user_blocked_status(user.id, async_db)
    flags = await _stored_flags(async_db)
    assert flags[target_thread.id] is True

    changed = await refresh_all_users_blocked_status_async(async_db)
    assert changed == {}
    assert (await _stored_flags(async_db))[target_thread.id] is True
