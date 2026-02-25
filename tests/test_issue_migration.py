"""Test thread migration to issue tracking."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_partial_read(async_db: AsyncSession):
    """Test migrating a partially-read thread."""
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

    # User has read issues 1-15, total is 25
    migrated = await thread.migrate_to_issues(15, 25, async_db)
    await async_db.flush()

    assert migrated.total_issues == 25
    assert migrated.reading_progress == "in_progress"
    assert migrated.next_unread_issue_id is not None
    assert migrated.issues_remaining == 10

    # Check issue records created
    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25

    # Check first 15 are read
    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 15

    # Check last 10 are unread
    unread_issues = [i for i in issues if i.status == "unread"]
    assert len(unread_issues) == 10


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_completed(async_db: AsyncSession):
    """Test migrating a completed thread."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # User has read all 25 issues
    migrated = await thread.migrate_to_issues(25, 25, async_db)
    await async_db.flush()

    assert migrated.total_issues == 25
    assert migrated.reading_progress == "completed"
    assert migrated.next_unread_issue_id is None
    assert migrated.status == "completed"
    assert migrated.issues_remaining == 0

    # All issues should be read
    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25
    assert all(i.status == "read" for i in issues)


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_unread(async_db: AsyncSession):
    """Test migrating an unread thread."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=25,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # User hasn't read any issues yet
    migrated = await thread.migrate_to_issues(0, 25, async_db)
    await async_db.flush()

    assert migrated.total_issues == 25
    assert migrated.reading_progress == "in_progress"
    assert migrated.next_unread_issue_id is not None
    assert migrated.issues_remaining == 25

    # All issues should be unread
    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25
    assert all(i.status == "unread" for i in issues)


@pytest.mark.asyncio
async def test_migrate_thread_validation_errors(async_db: AsyncSession):
    """Test migration validation."""
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

    # Negative last_issue_read
    with pytest.raises(ValueError, match="last_issue_read must be >= 0"):
        await thread.migrate_to_issues(-1, 25, async_db)

    # last_issue_read exceeds total_issues
    with pytest.raises(ValueError, match="last_issue_read cannot exceed total_issues"):
        await thread.migrate_to_issues(30, 25, async_db)


@pytest.mark.asyncio
async def test_get_issues_remaining_old_system(sample_data, async_db: AsyncSession):
    """Test get_issues_remaining for unmigrated thread."""
    thread = sample_data["threads"][0]
    count = await thread.get_issues_remaining(async_db)
    assert count == thread.issues_remaining


@pytest.mark.asyncio
async def test_get_issues_remaining_new_system(async_db: AsyncSession):
    """Test get_issues_remaining for migrated thread."""
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
    await async_db.flush()  # Flush to get thread.id
    await thread.migrate_to_issues(15, 25, async_db)
    await async_db.flush()

    count = await thread.get_issues_remaining(async_db)
    assert count == 10


@pytest.mark.asyncio
async def test_migrate_single_issue(async_db: AsyncSession):
    """Test migrating a thread with a single issue."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # Single issue, unread
    migrated = await thread.migrate_to_issues(0, 1, async_db)
    await async_db.flush()

    assert migrated.total_issues == 1
    assert migrated.reading_progress == "in_progress"
    assert migrated.next_unread_issue_id is not None

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 1
    assert issues[0].issue_number == "1"
    assert issues[0].status == "unread"


@pytest.mark.asyncio
async def test_migrate_large_series(async_db: AsyncSession):
    """Test migrating a thread with many issues."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=50,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # 100 issues, user has read 75
    migrated = await thread.migrate_to_issues(75, 100, async_db)
    await async_db.flush()

    assert migrated.total_issues == 100
    assert migrated.reading_progress == "in_progress"
    assert migrated.issues_remaining == 25

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 100

    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 75

    unread_issues = [i for i in issues if i.status == "unread"]
    assert len(unread_issues) == 25


@pytest.mark.asyncio
async def test_migrate_preserves_thread_status_when_completed(async_db: AsyncSession):
    """Test that migration sets thread status to completed when all issues read."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # All issues read
    migrated = await thread.migrate_to_issues(10, 10, async_db)
    await async_db.flush()

    assert migrated.status == "completed"
    assert migrated.reading_progress == "completed"
    assert migrated.next_unread_issue_id is None


@pytest.mark.asyncio
async def test_next_unread_issue_points_to_correct_issue(async_db: AsyncSession):
    """Test that next_unread_issue_id points to the correct issue."""
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

    # Read first 5 of 10 issues
    migrated = await thread.migrate_to_issues(5, 10, async_db)
    await async_db.flush()

    # Get the next unread issue
    result = await async_db.execute(
        select(Issue).where(
            Issue.thread_id == thread.id,
            Issue.issue_number == "6",
        )
    )
    expected_next = result.scalar_one()

    assert migrated.next_unread_issue_id == expected_next.id
