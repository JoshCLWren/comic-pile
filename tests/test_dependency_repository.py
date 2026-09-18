"""Tests for dependency repository functions."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User
from app.repositories import dependency_repository


@pytest.mark.asyncio
async def test_get_dependency(async_db: AsyncSession, default_user: User) -> None:
    """Test getting a dependency by ID."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    dependency = await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await async_db.flush()

    result = await dependency_repository.get_dependency(async_db, dependency.id)
    assert result is not None
    assert result.id == dependency.id
    assert result.source_issue_id == issue1.id
    assert result.target_issue_id == issue2.id


@pytest.mark.asyncio
async def test_get_dependency_not_found(async_db: AsyncSession) -> None:
    """Test getting a non-existent dependency."""
    result = await dependency_repository.get_dependency(async_db, 999)
    assert result is None


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

    await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await dependency_repository.create_dependency(async_db, issue2.id, issue3.id)
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

    await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await dependency_repository.create_dependency(async_db, issue2.id, issue3.id)
    await async_db.flush()

    incoming, outgoing = await dependency_repository.get_issue_dependencies(async_db, issue2.id)

    assert len(incoming) == 1
    assert len(outgoing) == 1
    assert incoming[0].source_issue_id == issue1.id
    assert incoming[0].target_issue_id == issue2.id
    assert outgoing[0].source_issue_id == issue2.id
    assert outgoing[0].target_issue_id == issue3.id


@pytest.mark.asyncio
async def test_get_dependency_by_ids(async_db: AsyncSession, default_user: User) -> None:
    """Test getting dependency by source and target IDs."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    dependency = await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await async_db.flush()

    result = await dependency_repository.get_dependency_by_ids(async_db, issue1.id, issue2.id)
    assert result is not None
    assert result.id == dependency.id

    result = await dependency_repository.get_dependency_by_ids(async_db, issue2.id, issue1.id)
    assert result is None


@pytest.mark.asyncio
async def test_create_dependency(async_db: AsyncSession, default_user: User) -> None:
    """Test creating a dependency."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    dependency = await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)

    assert dependency is not None
    assert dependency.source_issue_id == issue1.id
    assert dependency.target_issue_id == issue2.id


@pytest.mark.asyncio
async def test_update_dependency_note(async_db: AsyncSession, default_user: User) -> None:
    """Test updating dependency note."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    dependency = await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await async_db.flush()

    updated = await dependency_repository.update_dependency_note(async_db, dependency.id, "Test note")

    assert updated is not None
    assert updated.note == "Test note"


@pytest.mark.asyncio
async def test_delete_dependency(async_db: AsyncSession, default_user: User) -> None:
    """Test deleting a dependency."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    dependency = await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await async_db.flush()

    await dependency_repository.delete_dependency(async_db, dependency.id)

    result = await async_db.execute(select(Dependency).where(Dependency.id == dependency.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_is_dependency_owned_by_user(async_db: AsyncSession, default_user: User) -> None:
    """Test checking dependency ownership."""
    user = default_user

    thread1 = Thread(title="Thread 1", user_id=user.id, format="Comic", queue_position=0)
    thread2 = Thread(title="Thread 2", user_id=user.id, format="Comic", queue_position=0)
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    dependency = await dependency_repository.create_dependency(async_db, issue1.id, issue2.id)
    await async_db.flush()

    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, user.id, async_db)
    assert is_owned is True

    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, 999, async_db)
    assert is_owned is False
