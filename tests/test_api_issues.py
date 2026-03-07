"""Tests for adding issues to existing migrated threads (Phase 2 feature)."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_add_issues_to_existing_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues adds issues to thread that already has issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=11,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=11,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    existing_issues = [
        Issue(thread_id=thread.id, issue_number=str(i), status="unread") for i in range(21, 32)
    ]
    for issue in existing_issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "32-35"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 15
    assert len(data["issues"]) == 4

    issue_numbers = {issue["issue_number"] for issue in data["issues"]}
    assert issue_numbers == {"32", "33", "34", "35"}

    await async_db.refresh(thread)
    assert thread.total_issues == 15
    assert thread.issues_remaining == 15
    assert thread.reading_progress == "in_progress"


@pytest.mark.asyncio
async def test_insert_annual_in_middle(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /threads/{thread_id}/issues appends Annual 3 at end after all existing issues.

    Algorithm: New issues are always appended at position (max_position + 1).
    """
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=11,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=11,
        reading_progress="in_progress",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    existing_issues = [
        Issue(thread_id=thread.id, issue_number=str(i), status="unread", position=idx)
        for idx, i in enumerate(range(21, 32), start=1)
    ]
    for issue in existing_issues:
        async_db.add(issue)
    await async_db.flush()

    thread.next_unread_issue_id = existing_issues[0].id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "21-25, Annual 3, 26-31"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 12
    assert len(data["issues"]) == 1

    new_issue = data["issues"][0]
    assert new_issue["issue_number"] == "Annual 3"
    assert new_issue["status"] == "unread"
    assert new_issue["position"] == 12

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    all_issues = result.scalars().all()
    issue_numbers = [issue.issue_number for issue in all_issues]

    assert issue_numbers[-1] == "Annual 3"

    await async_db.refresh(thread)
    assert thread.total_issues == 12
    assert thread.issues_remaining == 12


@pytest.mark.asyncio
async def test_deduplicate_existing_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues skips issues that already exist."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    existing_issues = [
        Issue(thread_id=thread.id, issue_number="1", status="unread"),
        Issue(thread_id=thread.id, issue_number="2", status="unread"),
    ]
    for issue in existing_issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 3

    issue_numbers = {issue["issue_number"] for issue in data["issues"]}
    assert issue_numbers == {"3", "4", "5"}

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    all_issues = result.scalars().all()
    assert len(all_issues) == 5


@pytest.mark.asyncio
async def test_update_thread_metadata(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /threads/{thread_id}/issues updates total_issues and issues_remaining correctly."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), status="read", read_at=datetime.now(UTC))
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.flush()

    thread.next_unread_issue_id = None
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "11-15"}
    )
    assert response.status_code == 201

    await async_db.refresh(thread)
    assert thread.total_issues == 15
    assert thread.issues_remaining == 10
    assert thread.reading_progress == "in_progress"

    result = await async_db.execute(
        select(Event).where(
            Event.thread_id == thread.id,
            Event.type == "issues_created",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.type == "issues_created"


@pytest.mark.asyncio
async def test_reactivate_completed_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues reactivates completed thread when adding issues."""
    user = await get_or_create_user_async(async_db)

    active_thread = Thread(
        title="Already Active",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(active_thread)
    await async_db.flush()

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=2,
        status="completed",
        user_id=user.id,
        total_issues=10,
        reading_progress="completed",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    for i in range(1, 11):
        issue = Issue(
            thread_id=thread.id, issue_number=str(i), status="read", read_at=datetime.now(UTC)
        )
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "11-12"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 12
    assert len(data["issues"]) == 2

    await async_db.refresh(thread)
    assert thread.total_issues == 12
    assert thread.issues_remaining == 2
    assert thread.reading_progress == "in_progress"
    assert thread.next_unread_issue_id is not None
    assert thread.status == "active"
    assert thread.queue_position == 1

    await async_db.refresh(active_thread)
    assert active_thread.queue_position == 2


@pytest.mark.asyncio
async def test_add_all_duplicate_issues_returns_400(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues returns 400 when all issues already exist."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    for i in range(1, 6):
        issue = Issue(thread_id=thread.id, issue_number=str(i), status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 400
    assert "already exist" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_issues_preserves_next_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues preserves next_unread_issue_id when adding issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), status="unread") for i in range(1, 11)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.flush()

    thread.next_unread_issue_id = issues[4].id
    await async_db.commit()

    original_next_unread = thread.next_unread_issue_id

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "11-15"}
    )
    assert response.status_code == 201

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == original_next_unread


@pytest.mark.asyncio
async def test_add_issues_with_mixed_duplicates(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues handles mix of new and existing issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    existing = Issue(thread_id=thread.id, issue_number="3", status="unread")
    async_db.add(existing)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 4

    issue_numbers = {issue["issue_number"] for issue in data["issues"]}
    assert issue_numbers == {"1", "2", "4", "5"}


@pytest.mark.asyncio
async def test_add_issues_to_thread_with_annuals(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues adds numeric issues to thread with annuals."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    annual1 = Issue(thread_id=thread.id, issue_number="Annual 1", status="unread")
    annual2 = Issue(thread_id=thread.id, issue_number="Annual 2", status="unread")
    async_db.add(annual1)
    async_db.add(annual2)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-3"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 3

    issue_numbers = {issue["issue_number"] for issue in data["issues"]}
    assert issue_numbers == {"1", "2", "3"}

    await async_db.refresh(thread)
    assert thread.total_issues == 5
