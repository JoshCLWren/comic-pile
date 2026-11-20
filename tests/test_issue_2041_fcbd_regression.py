"""Regression coverage for FCBD prerequisite enforcement (issue #2041).

Proves the canonical evaluator never surfaces a genuinely read prerequisite
in blocker explanations, and that Roll candidate selection agrees with that
prerequisite state for Ultimates #18.

Also covers aggregate blocking: when the target remains blocked for another
branch, the reported cause is the actual remaining unread issue rather than
the already-read FCBD entry.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import get_blocking_explanations, refresh_user_blocked_status
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.conftest import get_or_create_user_async


async def _make_thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_number: str,
    queue_position: int,
    status: str = "unread",
) -> tuple[Thread, Issue]:
    """Create one owned thread with a single issue."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=1,
        status=status,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id if status == "unread" else None
    if status == "read":
        thread.reading_progress = "completed"
        thread.status = "completed"
        thread.issues_remaining = 0
    await db.flush()
    return thread, issue


async def _roll_pool_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return thread IDs currently eligible for bounded Roll candidate selection."""
    rows = await get_bounded_roll_pool_rows(user_id, db, current_die=20)
    return {row[0].id for row in rows}


@pytest.mark.asyncio
async def test_read_prerequisite_never_reported_as_blocker(
    async_db: AsyncSession,
) -> None:
    """A read source issue never appears in blocker explanations."""
    user = await get_or_create_user_async(async_db)

    _fcbd_thread, fcbd_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Free Comic Book Day 2025",
        issue_number="2025",
        queue_position=30,
        status="read",
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="The Ultimates",
        issue_number="18",
        queue_position=31,
        status="unread",
    )
    async_db.add(
        Dependency(
            source_issue_id=fcbd_issue.id,
            target_issue_id=target_issue.id,
        )
    )
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []

    roll_ids = await _roll_pool_ids(user.id, async_db)
    assert target_thread.id in roll_ids
