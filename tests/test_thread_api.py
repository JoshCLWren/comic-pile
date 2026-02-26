"""Tests for Thread API endpoints."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_success(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test successful migration creates issues and updates thread."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == thread.id
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_id"] is not None
    assert data["issues_remaining"] == 10

    await async_db.refresh(thread)

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25

    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 15


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_last_exceeds_total(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migration fails when last_issue_read > total_issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 30, "total_issues": 25},
    )

    assert response.status_code == 400
    assert "cannot exceed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_negative_values_blocked(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test schema validation blocks negative values."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": -1, "total_issues": 25},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """Test migration returns 404 for non-existent thread."""
    response = await auth_client.post(
        "/api/threads/999:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_already_migrated(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migration fails when thread already uses issue tracking."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=25,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 400
    assert "already uses" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migration fails for other user's threads."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_completed(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migrating a fully read thread marks it as completed."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 25, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "completed"
    assert data["next_unread_issue_id"] is None
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    await async_db.refresh(thread)

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25
    assert all(i.status == "read" for i in issues)


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migrating an unread thread."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=25,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 0, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_id"] is not None
    assert data["issues_remaining"] == 25

    await async_db.refresh(thread)

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25

    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 0


@pytest.mark.asyncio
async def test_create_thread_without_total_issues_maintains_backward_compat(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Creating thread without total_issues uses old system (backward compat)."""
    response = await auth_client.post(
        "/api/threads/",
        json={
            "title": "Old Style Thread",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Old Style Thread"
    assert data["issues_remaining"] == 10
    assert data["total_issues"] is None
    assert data["reading_progress"] is None

    thread = await async_db.get(Thread, data["id"])
    assert thread is not None
    assert thread.issues_remaining == 10
    assert thread.total_issues is None
    assert not thread.uses_issue_tracking()


@pytest.mark.asyncio
async def test_create_thread_with_total_issues_enables_tracking(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Creating thread with total_issues enables issue tracking."""
    response = await auth_client.post(
        "/api/threads/",
        json={
            "title": "New Style Thread",
            "format": "Comic",
            "issues_remaining": 10,
            "total_issues": 25,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Style Thread"
    assert data["total_issues"] == 25
    assert data["reading_progress"] is None

    thread = await async_db.get(Thread, data["id"])
    assert thread is not None
    assert thread.total_issues == 25
    assert thread.uses_issue_tracking()

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 0


@pytest.mark.asyncio
async def test_thread_create_schema_accepts_total_issues() -> None:
    """ThreadCreate schema accepts optional total_issues field."""
    from app.schemas import ThreadCreate

    schema = ThreadCreate(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        total_issues=25,
    )
    assert schema.total_issues == 25

    schema_without = ThreadCreate(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
    )
    assert schema_without.total_issues is None


@pytest.mark.asyncio
async def test_migration_enables_issue_tracking(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Migrating a thread enables issue tracking."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Old Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    assert thread.total_issues is None
    assert not thread.uses_issue_tracking()

    response = await auth_client.post(
        f"/api/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "in_progress"

    await async_db.refresh(thread)
    assert thread.total_issues == 25
    assert thread.uses_issue_tracking()

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25
