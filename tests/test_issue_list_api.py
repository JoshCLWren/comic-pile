"""Tests for Issue List API endpoints."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User
from tests.conftest import get_or_create_user_async

async def test_list_issues_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /threads/{thread_id}/issues returns all issues for a thread."""
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

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(i),
            position=i,
            status="unread" if i > 2 else "read",
        )
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 5
    assert data["page_size"] == 50
    assert data["next_page_token"] is None

async def test_list_issues_filter_by_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /threads/{thread_id}/issues?status=unread filters unread issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(i),
            position=i,
            status="unread" if i > 2 else "read",
        )
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?status=unread")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 3
    assert len(data["issues"]) == 3
    assert all(issue["status"] == "unread" for issue in data["issues"])

async def test_list_issues_filter_by_read(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /threads/{thread_id}/issues?status=read filters read issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(i),
            position=i,
            status="unread" if i > 2 else "read",
        )
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?status=read")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 2
    assert len(data["issues"]) == 2
    assert all(issue["status"] == "read" for issue in data["issues"])

async def test_list_issues_empty_thread(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /threads/{thread_id}/issues returns empty list for thread with no issues."""
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
    await async_db.flush()
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 0
    assert data["issues"] == []

async def test_list_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """GET /threads/{thread_id}/issues returns 404 for non-existent thread."""
    response = await auth_client.get("/api/v1/threads/999/issues")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

async def test_list_issues_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /threads/{thread_id}/issues returns 404 for thread owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

async def test_list_issues_pagination(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /threads/{thread_id}/issues with page_size and page_token paginates results."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        for i in range(1, 11)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?page_size=3")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 10
    assert len(data["issues"]) == 3
    assert data["page_size"] == 3
    assert data["next_page_token"] is not None

    next_token = data["next_page_token"]
    response2 = await auth_client.get(
        f"/api/v1/threads/{thread.id}/issues?page_size=3&page_token={next_token}"
    )
    assert response2.status_code == 200

    data2 = response2.json()
    assert len(data2["issues"]) == 3
    assert data2["issues"][0]["issue_number"] != data["issues"][0]["issue_number"]

async def test_list_issues_invalid_page_token(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /threads/{thread_id}/issues with invalid page_token returns 400."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?page_token=invalid")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()

async def test_validate_issue_order_returns_dependency_conflicts(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """GET /threads/{thread_id}/issues:validateOrder reports in-thread order conflicts."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Order Validation Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue_one = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    issue_two = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add_all([issue_one, issue_two])
    await async_db.flush()

    async_db.add(
        Dependency(
            source_issue_id=issue_two.id,
            target_issue_id=issue_one.id,
        )
    )
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues:validateOrder")
    assert response.status_code == 200

    data = response.json()
    assert len(data["warnings"]) == 1
    assert "issue #2" in data["warnings"][0]
    assert "issue #1" in data["warnings"][0]

async def test_get_issue_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /issues/{issue_id} returns single issue details."""
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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == issue.id
    assert data["thread_id"] == thread.id
    assert data["issue_number"] == "1"
    assert data["status"] == "unread"

async def test_get_issue_not_found(auth_client: AsyncClient) -> None:
    """GET /issues/{issue_id} returns 404 for non-existent issue."""
    response = await auth_client.get("/api/v1/issues/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

async def test_get_issue_other_user_issue(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /issues/{issue_id} returns 404 for issue owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

async def test_issue_ordering_in_api_response(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test that issues are returned in correct position order from API."""
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
    await async_db.flush()

    for i in range(1, 11):
        issue = Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5, Annual 2"}
    )
    assert response.status_code == 201

    list_response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert list_response.status_code == 200

    data = list_response.json()
    assert data["total_count"] == 11
    issue_numbers = [i["issue_number"] for i in data["issues"]]

    expected_numbers = [str(i) for i in range(1, 11)] + ["Annual 2"]
    assert issue_numbers == expected_numbers

