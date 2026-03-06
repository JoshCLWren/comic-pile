"""Test for thread deletion bug that causes 500 errors."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient

from app.models import Event, Issue, Thread
from app.models.collection import Collection
from app.models.dependency import Dependency
from app.models.user import User
from sqlalchemy import select


@pytest.mark.asyncio
async def test_delete_thread_with_dependencies(
    auth_client: AsyncClient, async_db, test_username: str
) -> None:
    """Test that deleting a thread with dependencies works correctly.

    This test creates threads with dependencies and tries to delete them
    to reproduce a potential 500 error.
    """
    # Get the test user
    result = await async_db.execute(select(User).where(User.username == test_username))
    user = result.scalar_one()

    # Create a collection
    collection = Collection(
        name="DC Comics",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(collection)
    await async_db.commit()
    await async_db.refresh(collection)

    # Create thread 1 (source)
    thread1 = Thread(
        title="Batman",
        format="Comic",
        issues_remaining=10,
        total_issues=50,
        queue_position=1,
        status="active",
        user_id=user.id,
        collection_id=collection.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread1)

    # Create thread 2 (target)
    thread2 = Thread(
        title="Detective Comics",
        format="Comic",
        issues_remaining=15,
        total_issues=100,
        queue_position=2,
        status="active",
        user_id=user.id,
        collection_id=collection.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    # Create a dependency from thread1 to thread2
    dependency = Dependency(
        source_thread_id=thread1.id,
        target_thread_id=thread2.id,
    )
    async_db.add(dependency)

    # Create some issues for thread1
    for i in range(1, 6):
        issue = Issue(
            thread_id=thread1.id,
            issue_number=str(i),
            status="unread",
            read_at=None,
        )
        async_db.add(issue)

    # Create some issues for thread2
    for i in range(1, 6):
        issue = Issue(
            thread_id=thread2.id,
            issue_number=str(i),
            status="unread",
            read_at=None,
        )
        async_db.add(issue)

    # Create an event
    event = Event(
        type="create",
        timestamp=datetime.now(UTC),
        thread_id=thread1.id,
    )
    async_db.add(event)

    await async_db.commit()

    # Now try to delete thread1 (which has dependencies and issues)
    response = await auth_client.delete(f"/api/threads/{thread1.id}")

    # This should not return a 500 error
    assert response.status_code == 204

    # Verify thread1 is deleted
    db_thread1 = await async_db.get(Thread, thread1.id)
    assert db_thread1 is None

    # Verify dependencies are cascade deleted
    dep_result = await async_db.execute(
        select(Dependency).where(Dependency.source_thread_id == thread1.id)
    )
    assert dep_result.scalar_one_or_none() is None

    # Verify issues are cascade deleted
    issue_result = await async_db.execute(select(Issue).where(Issue.thread_id == thread1.id))
    assert issue_result.scalar_one_or_none() is None

    # Verify thread2 still exists
    db_thread2 = await async_db.get(Thread, thread2.id)
    assert db_thread2 is not None


@pytest.mark.asyncio
async def test_delete_thread_with_issues(
    auth_client: AsyncClient, async_db, test_username: str
) -> None:
    """Test deleting a thread with issue tracking enabled.

    This test verifies that deleting a thread with Issue records works correctly.
    """
    # Get the test user
    result = await async_db.execute(select(User).where(User.username == test_username))
    user = result.scalar_one()

    # Create a thread with issue tracking
    thread = Thread(
        title="Superman",
        format="Comic",
        issues_remaining=25,
        total_issues=50,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Create issues for the thread
    for i in range(1, 51):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            status="read" if i <= 25 else "unread",
            read_at=datetime.now(UTC) if i <= 25 else None,
        )
        async_db.add(issue)

    await async_db.commit()

    # Delete the thread
    response = await auth_client.delete(f"/api/threads/{thread.id}")
    assert response.status_code == 204

    # Verify thread and issues are deleted
    db_thread = await async_db.get(Thread, thread.id)
    assert db_thread is None

    issue_result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    assert issue_result.scalar_one_or_none() is None
