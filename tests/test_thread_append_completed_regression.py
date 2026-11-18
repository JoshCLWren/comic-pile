"""Regression coverage for issue #2192: appending unread CBL issues to completed threads."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import select

from app.models import Issue, Thread
from app.services.thread_state_repair import reconcile_contradictory_completed_threads
from tests.conftest import get_or_create_user_async


async def _create_thread_with_issues(
    async_db,
    user,
    title: str,
    specs: list[tuple[str, str]],
    status: str = "active",
    reading_progress: str | None = None,
):
    """Create thread with given issue specs (number, status)."""
    unread = sum(1 for _, s in specs if s != "read")
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=unread,
        queue_position=1,
        status=status,
        user_id=user.id,
        total_issues=len(specs),
        reading_progress=reading_progress
        or ("completed" if status == "completed" else "in_progress" if unread < len(specs) else "not_started"),
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issues: list[Issue] = []
    for pos, (num, st) in enumerate(specs, start=1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=num,
            position=pos,
            status=st,
            read_at=datetime.now(UTC) if st == "read" else None,
        )
        issues.append(issue)
    async_db.add_all(issues)
    await async_db.flush()
    first_unread = next((i for i in issues if i.status != "read"), None)
    thread.next_unread_issue_id = first_unread.id if first_unread else None
    if first_unread is None:
        thread.reading_progress = "completed"
        thread.status = "completed"
    await async_db.commit()
    # Refresh to get committed state; caller may override status to simulate corruption
    return thread, issues












@pytest.mark.asyncio
async def test_reconcile_existing_contradictory_rows_without_mutating_timestamps(async_db) -> None:
    """Repair existing completed threads with unread without touching read_at/ratings."""
    user = await get_or_create_user_async(async_db)
    # Create a corrupted thread: status completed but with unread rows
    thread = Thread(
        title="Marvel Two-in-One Annual (1976)",
        format="Comic",
        issues_remaining=2,  # contradictory
        queue_position=5,
        status="completed",
        user_id=user.id,
        total_issues=3,
        reading_progress="completed",
        next_unread_issue_id=None,  # stale
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    read_issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="read", read_at=datetime(2023, 1, 1, tzinfo=UTC))
    unread2 = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread", read_at=None)
    unread3 = Issue(thread_id=thread.id, issue_number="3", position=3, status="unread", read_at=None)
    # Also add a read with missing read_at to ensure predicate uses status not timestamp
    async_db.add_all([read_issue, unread2, unread3])
    await async_db.flush()
    # Leave thread.next_unread stale None to simulate production corruption
    await async_db.commit()

    original_read_at = read_issue.read_at

    summary = await reconcile_contradictory_completed_threads(async_db, user_id=user.id)
    await async_db.commit()

    assert summary["repaired_threads"] == 1
    await async_db.refresh(thread)
    await async_db.refresh(read_issue)
    assert thread.status == "active"
    assert thread.issues_remaining == 2
    assert thread.total_issues == 3
    assert thread.next_unread_issue_id == unread2.id
    assert thread.reading_progress == "in_progress"
    # No mutation of read timestamps
    assert read_issue.read_at == original_read_at
    assert read_issue.status == "read"
    # Unread rows remain unread
    await async_db.refresh(unread2)
    assert unread2.status == "unread"


@pytest.mark.asyncio
async def test_reconcile_does_not_infer_reads_from_completed_status(async_db) -> None:
    """Repair must not mark unread issues as read just because thread was completed."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Gambit (Vol. 1) (1993-1994) - corrupted",
        format="Comic",
        issues_remaining=7,
        queue_position=2,
        status="completed",
        user_id=user.id,
        total_issues=7,
        reading_progress="completed",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issues = [Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread") for i in range(1, 8)]
    async_db.add_all(issues)
    await async_db.commit()

    await reconcile_contradictory_completed_threads(async_db, user_id=user.id)
    await async_db.commit()

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    for issue in result.scalars().all():
        assert issue.status == "unread"
    await async_db.refresh(thread)
    assert thread.status == "active"


@pytest.mark.asyncio
async def test_reconcile_active_thread_with_zero_issues_completes_and_clears_blocked(async_db) -> None:
    """Active threads with no unread issues must be completed and unblocked."""
    from app.services.thread_state_repair import reconcile_contradictory_completed_threads

    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Hellboy in Love: Shadow Theater",
        format="Comic",
        issues_remaining=0,
        queue_position=3,
        status="active",
        user_id=user.id,
        total_issues=0,
        reading_progress="not_started",
        next_unread_issue_id=None,
        is_blocked=True,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    summary = await reconcile_contradictory_completed_threads(async_db, user_id=user.id)
    await async_db.commit()

    await async_db.refresh(thread)
    assert summary["repaired_threads"] == 1
    assert thread.status == "completed"
    assert thread.is_blocked is False
    assert thread.queue_position == 0


@pytest.mark.asyncio
async def test_reconcile_zero_issue_legacy_thread_keeps_counter_mode(async_db) -> None:
    """Completing an empty legacy thread must not migrate it to issue tracking."""
    from app.services.thread_state_repair import reconcile_contradictory_completed_threads

    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Legacy Counter Series",
        format="Comic",
        issues_remaining=0,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=None,
        reading_progress=None,
        next_unread_issue_id=None,
        is_blocked=True,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    summary = await reconcile_contradictory_completed_threads(async_db, user_id=user.id)
    await async_db.commit()

    await async_db.refresh(thread)
    assert summary["repaired_threads"] == 1
    assert thread.status == "completed"
    assert thread.total_issues is None
    assert thread.issues_remaining == 0
    assert thread.is_blocked is False
    assert thread.queue_position == 0
