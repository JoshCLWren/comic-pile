"""Test for deleting thread with issues (reproduces production bug)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread


@pytest.mark.asyncio
async def test_delete_thread_with_issues_reproduces_lazy_raise_bug(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test that deleting a thread with issues triggers lazy='raise' error.

    This reproduces the production bug where deleting a thread that has
    Issue records causes: 'Issue.thread' is not available due to lazy='raise'

    The bug occurs because:
    1. Thread.issues has cascade="all, delete-orphan"
    2. Issue.thread has lazy="raise"
    3. When deleting thread, SQLAlchemy tries to cascade delete issues
    4. During cascade, it tries to access Issue.thread relationship
    5. lazy="raise" causes InvalidRequestError
    """
    # Ensure a valid user exists for FK references (use test helper to align with auth)
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    user_id = user.id

    # Create a thread with issue tracking
    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        total_issues=5,
        queue_position=100,
        status="active",
        user_id=user_id,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)
    thread_id = thread.id

    # Create some issues for this thread
    for i in range(1, 4):
        issue = Issue(
            thread_id=thread_id,
            issue_number=str(i),
            status="unread",
            position=i,
        )
        async_db.add(issue)

    await async_db.commit()

    # Try to delete the thread - this should trigger the lazy='raise' bug
    response = await auth_client.delete(f"/api/threads/{thread_id}")

    # Currently this fails with 500 due to lazy='raise' on Issue.thread
    # After fix, this should return 204
    assert response.status_code == 204

    # Verify thread was deleted
    deleted_thread = await async_db.get(Thread, thread_id)
    assert deleted_thread is None

    # Verify issues were cascade deleted
    issues_result = await async_db.execute(select(Issue).where(Issue.thread_id == thread_id))
    remaining_issues = issues_result.scalars().all()
    assert len(remaining_issues) == 0


@pytest.mark.asyncio
async def test_delete_thread_not_found_returns_404(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test DELETE /api/threads/{id} returns 404 for non-existent thread."""
    response = await auth_client.delete("/api/threads/999999")
    assert response.status_code == 404
