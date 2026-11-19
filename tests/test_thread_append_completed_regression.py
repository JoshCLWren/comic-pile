"""Regression coverage for issue #2192: appending unread CBL issues to completed threads."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import select

from app.models import Dependency, Issue, Thread
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
        or (
            "completed"
            if status == "completed"
            else "in_progress"
            if unread < len(specs)
            else "not_started"
        ),
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
async def test_append_one_unread_to_completed_transitions_to_active(auth_client, async_db) -> None:
    """Appending one unread issue to a completed thread transitions it out of completed."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_thread_with_issues(
        async_db,
        user,
        "Tom Strong (1999 - 2006)",
        [("1", "read"), ("2", "read")],
        status="completed",
        reading_progress="completed",
    )
    # Ensure thread is completed with 0 remaining before append
    await async_db.refresh(thread)
    assert thread.status == "completed"
    assert thread.issues_remaining == 0
    assert thread.next_unread_issue_id is None

    resp = await auth_client.post(f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "3"})
    assert resp.status_code == 201

    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id is not None
    assert thread.total_issues == 3
    assert thread.reading_progress == "in_progress"
    # blocker denormalization should be consistent (not blocked since no dependency)
    assert thread.is_blocked is False
    # Semantic: status completed only with zero unread
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id, Issue.status != "read")
    )
    unread = result.scalars().all()
    assert len(unread) == 1
    assert thread.next_unread_issue_id == unread[0].id


@pytest.mark.asyncio
async def test_append_multiple_preserves_read_history(auth_client, async_db) -> None:
    """Appending multiple unread issues preserves existing read history while recomputing state."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_thread_with_issues(
        async_db,
        user,
        "Tomorrow Stories (1999 - 2002)",
        [("1", "read"), ("2", "read"), ("3", "read")],
        status="completed",
        reading_progress="completed",
    )
    # Simulate read_at missing on read rows is okay — status is semantic
    for issue in issues:
        if issue.status == "read":
            issue.read_at = None
    await async_db.commit()

    resp = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "4-12"}
    )
    assert resp.status_code == 201
    assert resp.json()["total_count"] == 12

    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.issues_remaining == 9
    assert thread.total_issues == 12
    # Read history preserved: first three remain read with unchanged read_at (None stays None, not mutated to now)
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    all_issues = result.scalars().all()
    assert [i.status for i in all_issues[:3]] == ["read", "read", "read"]
    # Timestamps not mutated: they remain None (no inference from completed status)
    assert all(i.read_at is None for i in all_issues[:3])
    assert all(i.status == "unread" for i in all_issues[3:])


@pytest.mark.asyncio
async def test_append_blocked_new_first_unread_reflects_blocked(auth_client, async_db) -> None:
    """If the new first unread is blocked, status is active but is_blocked true."""
    user = await get_or_create_user_async(async_db)
    # Source thread with unread issue that blocks target's next unread
    source_thread, source_issues = await _create_thread_with_issues(
        async_db, user, "Source Block", [("1", "unread")]
    )
    target_thread, _ = await _create_thread_with_issues(
        async_db,
        user,
        "Target Blocked Thread",
        [("1", "read"), ("2", "read")],
        status="completed",
        reading_progress="completed",
    )
    # Append one unread to completed target
    resp = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}/issues", json={"issue_range": "3"}
    )
    assert resp.status_code == 201
    new_issue_id = resp.json()["issues"][0]["id"]
    # Create dependency: source unread blocks new issue
    async_db.add(Dependency(source_issue_id=source_issues[0].id, target_issue_id=new_issue_id))
    await async_db.commit()
    # Trigger recompute via another append? Instead directly call refresh path: append another issue will recompute blocked
    # Simpler: verify that after dependency, blocked flag would be true after a no-op move that refreshes blocked
    # We test the invariant directly: after dependency exists, a second append should leave thread blocked
    resp2 = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}/issues", json={"issue_range": "4"}
    )
    assert resp2.status_code == 201

    await async_db.refresh(target_thread)
    assert target_thread.status == "active"
    assert target_thread.is_blocked is True
    # next_unread should still be the first unread (issue 3)
    assert target_thread.next_unread_issue_id == new_issue_id


@pytest.mark.asyncio
async def test_append_eligible_new_first_unread_reflects_active(auth_client, async_db) -> None:
    """If new first unread is eligible, status active and not blocked."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_thread_with_issues(
        async_db,
        user,
        "Eligible Thread",
        [("1", "read")],
        status="completed",
        reading_progress="completed",
    )
    resp = await auth_client.post(f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "2"})
    assert resp.status_code == 201

    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.is_blocked is False
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id is not None


@pytest.mark.asyncio
async def test_after_write_status_remaining_next_unread_agree(auth_client, async_db) -> None:
    """After the write, status, issues_remaining, next_unread, and totals agree."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_thread_with_issues(
        async_db,
        user,
        "Agree Thread",
        [("1", "read"), ("2", "read")],
        status="completed",
        reading_progress="completed",
    )
    await auth_client.post(f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "3-5"})
    await async_db.refresh(thread)
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id, Issue.status != "read")
    )
    unread = result.scalars().all()
    assert thread.issues_remaining == len(unread)
    assert thread.total_issues == 5
    if unread:
        assert thread.status == "active"
        assert thread.next_unread_issue_id == min(unread, key=lambda i: i.position).id
        assert thread.reading_progress == "in_progress"
    else:
        assert thread.status == "completed"
        assert thread.next_unread_issue_id is None
