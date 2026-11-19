"""Tests for session API with issue metadata."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread


def _assert_issue_metadata(
    active_thread: dict[str, object],
    *,
    issue_id: int | None,
    issue_number: str | None,
) -> None:
    assert active_thread["issue_id"] == issue_id
    assert active_thread["issue_number"] == issue_number
    assert active_thread["next_issue_id"] == issue_id
    assert active_thread["next_issue_number"] == issue_number


@pytest.mark.asyncio
async def test_simplified_migration_endpoint(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Simplified migration endpoint works correctly."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Thread to Migrate",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": "5"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread.id
    assert data["total_issues"] == 9
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "5"

    await async_db.refresh(thread)
    assert thread.total_issues == 9
    assert thread.reading_progress == "in_progress"
    assert thread.next_unread_issue_id is not None

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()
    assert len(issues) == 9

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]
    assert len(read_issues) == 4
    assert len(unread_issues) == 5
    assert unread_issues[0].issue_number == "5"




@pytest.mark.asyncio
async def test_migration_with_issue_number_1_starts_from_beginning(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Migration with issue_number=1 marks no issues as read, starts fresh."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Legacy Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": "1"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 10
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "1"

    await async_db.refresh(thread)

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    assert len(issues) == 10

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]

    assert len(read_issues) == 0
    assert len(unread_issues) == 10
    assert unread_issues[0].issue_number == "1"


@pytest.mark.asyncio
async def test_simple_migration_creates_correct_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """MigrateToIssuesSimple must not create a phantom extra issue.

    Regression test for the off-by-one bug in thread.py:833:
        total_issues = thread.issues_remaining + issue_number
    should be:
        total_issues = thread.issues_remaining + issue_number - 1

    Scenario: thread has 5 issues remaining, user just read issue #1.
    Correct total = 5 + 1 - 1 = 5, so migration creates 5 unread issues.
    Buggy code produces 6, leaving a phantom issue that blocks completion.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Simple Migration Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": "1"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 5, (
        "total_issues should be issues_remaining + issue_number - 1 = 5, "
        f"got {data['total_issues']} (off-by-one bug produces 6)"
    )
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "1"

    await async_db.refresh(thread)

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    assert len(issues) == 5, (
        f"Expected 5 issues, got {len(issues)} — phantom issue created by off-by-one bug"
    )

    unread_issues = [i for i in issues if i.status == "unread"]
    read_issues = [i for i in issues if i.status == "read"]

    assert len(unread_issues) == 5
    assert len(read_issues) == 0
    assert unread_issues[0].issue_number == "1"
    assert unread_issues[-1].issue_number == "5"
