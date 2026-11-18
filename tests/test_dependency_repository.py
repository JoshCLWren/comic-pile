"""Tests for dependency repository functions."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User
from app.repositories import dependency_repository


@pytest.mark.asyncio
async def test_get_thread_dependencies(async_db: AsyncSession, default_user: User) -> None:
    """Test getting thread dependencies."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    thread3 = Thread(title="Thread 3", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2, thread3])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    issue3 = Issue(thread_id=thread3.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2, issue3])
    await async_db.flush()

    async_db.add_all(
        [
            Dependency(source_issue_id=issue1.id, target_issue_id=issue2.id, origin="reader"),
            Dependency(source_issue_id=issue2.id, target_issue_id=issue3.id, origin="reader"),
        ]
    )
    await async_db.flush()

    blocking, blocked_by = await dependency_repository.get_thread_dependencies(async_db, thread2.id)

    assert len(blocking) == 1
    assert len(blocked_by) == 1
    assert blocking[0].source_issue_id == issue2.id
    assert blocking[0].target_issue_id == issue3.id
    assert blocked_by[0].source_issue_id == issue1.id
    assert blocked_by[0].target_issue_id == issue2.id


@pytest.mark.asyncio
async def test_get_issue_dependencies(async_db: AsyncSession, default_user: User) -> None:
    """Test getting issue dependencies."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    issue3 = Issue(thread_id=thread2.id, issue_number="2", position=2)
    async_db.add_all([issue1, issue2, issue3])
    await async_db.flush()

    async_db.add_all(
        [
            Dependency(source_issue_id=issue1.id, target_issue_id=issue2.id, origin="reader"),
            Dependency(source_issue_id=issue2.id, target_issue_id=issue3.id, origin="reader"),
        ]
    )
    await async_db.flush()

    incoming, outgoing = await dependency_repository.get_issue_dependencies(async_db, issue2.id)

    assert len(incoming) == 1
    assert len(outgoing) == 1
    assert incoming[0].source_issue_id == issue1.id
    assert incoming[0].target_issue_id == issue2.id
    assert outgoing[0].source_issue_id == issue2.id
    assert outgoing[0].target_issue_id == issue3.id
