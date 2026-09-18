"""Tests for dependency repository functions."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from app.repositories import dependency_repository
from tests.conftest import create_test_user


async def test_get_dependency(db: AsyncSession, test_user: dict) -> None:
    """Test getting a dependency by ID."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    db.add_all([issue1, issue2])
    await db.commit()
    
    # Create dependency
    dependency = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    await db.commit()
    
    # Test getting dependency
    result = await dependency_repository.get_dependency(db, dependency.id)
    assert result is not None
    assert result.id == dependency.id
    assert result.source_issue_id == issue1.id
    assert result.target_issue_id == issue2.id


async def test_get_dependency_not_found(db: AsyncSession) -> None:
    """Test getting a non-existent dependency."""
    result = await dependency_repository.get_dependency(db, 999)
    assert result is None


async def test_get_thread_dependencies(db: AsyncSession, test_user: dict) -> None:
    """Test getting thread dependencies."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    thread3 = Thread(title="Thread 3", user_id=user.id)
    db.add_all([thread1, thread2, thread3])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    issue3 = Issue(thread_id=thread3.id, issue_number="1", position=1)
    db.add_all([issue1, issue2, issue3])
    await db.commit()
    
    # Create dependencies
    dep1 = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    dep2 = await dependency_repository.create_dependency(db, issue2.id, issue3.id)
    await db.commit()
    
    # Test getting thread dependencies
    blocking, blocked_by = await dependency_repository.get_thread_dependencies(db, thread2.id)
    
    # thread2 should be blocked by thread1 and block thread3
    assert len(blocking) == 1
    assert len(blocked_by) == 1
    assert blocking[0].source_issue_id == issue2.id
    assert blocking[0].target_issue_id == issue3.id
    assert blocked_by[0].source_issue_id == issue1.id
    assert blocked_by[0].target_issue_id == issue2.id


async def test_get_issue_dependencies(db: AsyncSession, test_user: dict) -> None:
    """Test getting issue dependencies."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    issue3 = Issue(thread_id=thread2.id, issue_number="2", position=2)
    db.add_all([issue1, issue2, issue3])
    await db.commit()
    
    # Create dependencies
    dep1 = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    dep2 = await dependency_repository.create_dependency(db, issue2.id, issue3.id)
    await db.commit()
    
    # Test getting issue dependencies
    incoming, outgoing = await dependency_repository.get_issue_dependencies(db, issue2.id)
    
    # issue2 should have 1 incoming (from issue1) and 1 outgoing (to issue3)
    assert len(incoming) == 1
    assert len(outgoing) == 1
    assert incoming[0].source_issue_id == issue1.id
    assert incoming[0].target_issue_id == issue2.id
    assert outgoing[0].source_issue_id == issue2.id
    assert outgoing[0].target_issue_id == issue3.id


async def test_get_dependency_by_ids(db: AsyncSession, test_user: dict) -> None:
    """Test getting dependency by source and target IDs."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    db.add_all([issue1, issue2])
    await db.commit()
    
    # Create dependency
    dependency = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    await db.commit()
    
    # Test getting by IDs
    result = await dependency_repository.get_dependency_by_ids(db, issue1.id, issue2.id)
    assert result is not None
    assert result.id == dependency.id
    
    # Test non-existent
    result = await dependency_repository.get_dependency_by_ids(db, issue2.id, issue1.id)
    assert result is None


async def test_create_dependency(db: AsyncSession, test_user: dict) -> None:
    """Test creating a dependency."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    db.add_all([issue1, issue2])
    await db.commit()
    
    # Create dependency
    dependency = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    
    assert dependency is not None
    assert dependency.source_issue_id == issue1.id
    assert dependency.target_issue_id == issue2.id


async def test_update_dependency_note(db: AsyncSession, test_user: dict) -> None:
    """Test updating dependency note."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    db.add_all([issue1, issue2])
    await db.commit()
    
    # Create dependency
    dependency = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    await db.commit()
    
    # Update note
    updated = await dependency_repository.update_dependency_note(db, dependency.id, "Test note")
    
    assert updated is not None
    assert updated.note == "Test note"


async def test_delete_dependency(db: AsyncSession, test_user: dict) -> None:
    """Test deleting a dependency."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    db.add_all([issue1, issue2])
    await db.commit()
    
    # Create dependency
    dependency = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    await db.commit()
    
    # Delete dependency
    await dependency_repository.delete_dependency(db, dependency.id)
    
    # Verify it's gone
    result = await db.execute(select(Dependency).where(Dependency.id == dependency.id))
    assert result.scalar_one_or_none() is None


async def test_is_dependency_owned_by_user(db: AsyncSession, test_user: dict) -> None:
    """Test checking dependency ownership."""
    # Create test data
    user = await create_test_user(db, test_user["username"], test_user["email"])
    
    # Create threads
    thread1 = Thread(title="Thread 1", user_id=user.id)
    thread2 = Thread(title="Thread 2", user_id=user.id)
    db.add_all([thread1, thread2])
    await db.commit()
    
    # Create issues
    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1)
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1)
    db.add_all([issue1, issue2])
    await db.commit()
    
    # Create dependency
    dependency = await dependency_repository.create_dependency(db, issue1.id, issue2.id)
    await db.commit()
    
    # Test ownership
    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, user.id, db)
    assert is_owned is True
    
    # Test non-existent user
    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, 999, db)
    assert is_owned is False