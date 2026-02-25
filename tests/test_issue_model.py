"""Test Issue model functionality."""

import pytest
from datetime import UTC, datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User


@pytest.mark.asyncio
async def test_issue_creation(async_db: AsyncSession):
    """Test creating a new issue."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()

    assert issue.id is not None
    assert issue.thread_id == thread.id
    assert issue.issue_number == "1"
    assert issue.status == "unread"
    assert issue.read_at is None


@pytest.mark.asyncio
async def test_issue_thread_relationship(async_db: AsyncSession):
    """Test Issue-Thread relationship."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        status="read",
    )
    async_db.add(issue)
    await async_db.flush()

    # Query with eager loading to avoid lazy='raise' errors
    result = await async_db.execute(select(Issue).where(Issue.id == issue.id))
    issue_loaded = result.scalar_one()

    # Query thread with issues eagerly loaded
    result = await async_db.execute(
        select(Thread).options(selectinload(Thread.issues)).where(Thread.id == thread.id)
    )
    thread_loaded = result.scalar_one()

    assert issue_loaded.thread_id == thread_loaded.id
    assert len(thread_loaded.issues) == 1


@pytest.mark.asyncio
async def test_issue_with_read_timestamp(async_db: AsyncSession):
    """Test issue with read_at timestamp."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    read_time = datetime.now(UTC)
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        status="read",
        read_at=read_time,
    )
    async_db.add(issue)
    await async_db.flush()

    assert issue.status == "read"
    assert issue.read_at is not None
    assert abs((issue.read_at - read_time).total_seconds()) < 1


@pytest.mark.asyncio
async def test_thread_uses_issue_tracking_old_system(sample_data):
    """Test that old thread (total_issues = NULL) uses old system."""
    thread = sample_data["threads"][0]
    assert thread.total_issues is None
    assert thread.uses_issue_tracking() is False


@pytest.mark.asyncio
async def test_thread_uses_issue_tracking_new_system(async_db: AsyncSession):
    """Test that migrated thread uses new system."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=25,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.flush()

    assert thread.uses_issue_tracking() is True


@pytest.mark.asyncio
async def test_issue_default_status_unread(async_db: AsyncSession):
    """Test that issue defaults to unread status."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
    )
    async_db.add(issue)
    await async_db.flush()

    assert issue.status == "unread"


@pytest.mark.asyncio
async def test_multiple_issues_per_thread(async_db: AsyncSession):
    """Test that a thread can have multiple issues."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    for i in range(1, 6):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            status="read" if i <= 3 else "unread",
        )
        async_db.add(issue)
    await async_db.flush()

    # Query thread with issues loaded
    result = await async_db.execute(
        select(Thread).options(selectinload(Thread.issues)).where(Thread.id == thread.id)
    )
    thread_loaded = result.scalar_one()

    assert len(thread_loaded.issues) == 5
    read_issues = [i for i in thread_loaded.issues if i.status == "read"]
    assert len(read_issues) == 3
    unread_issues = [i for i in thread_loaded.issues if i.status == "unread"]
    assert len(unread_issues) == 2
