"""Tests for Issue API endpoints."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
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
        Issue(thread_id=thread.id, issue_number=str(i), status="unread" if i > 2 else "read")
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


@pytest.mark.asyncio
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
        Issue(thread_id=thread.id, issue_number=str(i), status="unread" if i > 2 else "read")
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?status=unread")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 3
    assert all(issue["status"] == "unread" for issue in data["issues"])


@pytest.mark.asyncio
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
        Issue(thread_id=thread.id, issue_number=str(i), status="unread" if i > 2 else "read")
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?status=read")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 2
    assert all(issue["status"] == "read" for issue in data["issues"])


@pytest.mark.asyncio
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
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert response.status_code == 200

    data = response.json()
    assert data["total_count"] == 0
    assert data["issues"] == []


@pytest.mark.asyncio
async def test_list_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """GET /threads/{thread_id}/issues returns 404 for non-existent thread."""
    response = await auth_client.get("/api/v1/threads/999/issues")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
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

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
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
        Issue(thread_id=thread.id, issue_number=str(i), status="unread") for i in range(1, 11)
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


@pytest.mark.asyncio
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
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?page_token=invalid")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_from_simple_range(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues creates issues from range '1-25'."""
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
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-25"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 25
    assert len(data["issues"]) == 25
    assert data["page_size"] == 25

    await async_db.refresh(thread)
    assert thread.total_issues == 25
    assert thread.issues_remaining == 25
    assert thread.reading_progress == "not_started"
    assert thread.next_unread_issue_id is not None


@pytest.mark.asyncio
async def test_create_issues_from_complex_range(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues creates issues from '1, 3, 5-7'."""
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
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1, 3, 5-7"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 5
    assert len(data["issues"]) == 5

    issue_numbers = {issue["issue_number"] for issue in data["issues"]}
    assert issue_numbers == {"1", "3", "5", "6", "7"}


@pytest.mark.asyncio
async def test_create_issues_skips_duplicates(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues skips duplicate existing issues."""
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

    existing = Issue(thread_id=thread.id, issue_number="1", status="unread")
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
    assert issue_numbers == {"2", "3", "4", "5"}


@pytest.mark.asyncio
async def test_create_issues_invalid_range_non_numeric(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues returns 400 for non-numeric range."""
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
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-Annual, 3"}
    )
    assert response.status_code == 400
    assert "non-numeric" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_empty_range(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /threads/{thread_id}/issues returns 422 for empty range (schema validation)."""
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
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_issues_all_exist(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /threads/{thread_id}/issues returns 400 if all issues already exist."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    for i in range(1, 4):
        issue = Issue(thread_id=thread.id, issue_number=str(i), status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-3"}
    )
    assert response.status_code == 400
    assert "already exist" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """POST /threads/{thread_id}/issues returns 404 for non-existent thread."""
    response = await auth_client.post("/api/v1/threads/999/issues", json={"issue_range": "1-5"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_already_migrated(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues returns 400 for thread already using issue tracking."""
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

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 400
    assert "already uses" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues returns 404 for thread owned by different user."""
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

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_creates_event(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues creates issues_created event."""
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
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 201

    result = await async_db.execute(
        select(Event).where(Event.thread_id == thread.id, Event.type == "issues_created")
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.type == "issues_created"


@pytest.mark.asyncio
async def test_mark_issue_read_creates_event(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markRead creates issue_read event."""
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

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
    assert response.status_code == 204

    result = await async_db.execute(
        select(Event).where(
            Event.thread_id == thread.id,
            Event.type == "issue_read",
            Event.issue_id == issue.id,
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.type == "issue_read"
    assert event.issue_id == issue.id


@pytest.mark.asyncio
async def test_mark_issue_unread_creates_event(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markUnread creates issue_unread event."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="1", status="read", read_at=datetime.now(UTC))
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 204

    result = await async_db.execute(
        select(Event).where(
            Event.thread_id == thread.id,
            Event.type == "issue_unread",
            Event.issue_id == issue.id,
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.type == "issue_unread"
    assert event.issue_id == issue.id


@pytest.mark.asyncio
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

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == issue.id
    assert data["thread_id"] == thread.id
    assert data["issue_number"] == "1"
    assert data["status"] == "unread"


@pytest.mark.asyncio
async def test_get_issue_not_found(auth_client: AsyncClient) -> None:
    """GET /issues/{issue_id} returns 404 for non-existent issue."""
    response = await auth_client.get("/api/v1/issues/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
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

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mark_issue_read_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /issues/{issue_id}:markRead marks unread issue as read."""
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
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue1 = Issue(thread_id=thread.id, issue_number="1", status="unread", read_at=None)
    issue2 = Issue(thread_id=thread.id, issue_number="2", status="unread", read_at=None)
    issue3 = Issue(thread_id=thread.id, issue_number="3", status="unread", read_at=None)
    async_db.add(issue1)
    async_db.add(issue2)
    async_db.add(issue3)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue3.id}:markRead")
    assert response.status_code == 204

    await async_db.refresh(issue3)
    assert issue3.status == "read"
    assert issue3.read_at is not None

    await async_db.refresh(thread)
    assert thread.reading_progress == "in_progress"


@pytest.mark.asyncio
async def test_mark_issue_read_updates_next_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markRead updates thread's next_unread_issue_id."""
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

    issues = [Issue(thread_id=thread.id, issue_number=str(i), status="unread") for i in range(1, 6)]
    for issue in issues:
        async_db.add(issue)
    await async_db.flush()

    thread.next_unread_issue_id = issues[0].id
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issues[0].id}:markRead")
    assert response.status_code == 204

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[1].id


@pytest.mark.asyncio
async def test_mark_issue_read_completes_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markRead marks thread as completed when all issues read."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", status="read", read_at=datetime.now(UTC)),
        Issue(thread_id=thread.id, issue_number="2", status="read", read_at=datetime.now(UTC)),
        Issue(thread_id=thread.id, issue_number="3", status="unread"),
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issues[2].id}:markRead")
    assert response.status_code == 204

    await async_db.refresh(thread)
    assert thread.reading_progress == "completed"
    assert thread.status == "completed"
    assert thread.issues_remaining == 0
    assert thread.next_unread_issue_id is None


@pytest.mark.asyncio
async def test_mark_issue_read_already_read(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markRead returns 400 if issue already read."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="1", status="read", read_at=datetime.now(UTC))
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
    assert response.status_code == 400
    assert "already marked as read" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mark_issue_read_not_found(auth_client: AsyncClient) -> None:
    """POST /issues/{issue_id}:markRead returns 404 for non-existent issue."""
    response = await auth_client.post("/api/v1/issues/999:markRead")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mark_issue_read_other_user_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markRead returns 404 for issue owned by different user."""
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

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mark_issue_unread_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /issues/{issue_id}:markUnread marks read issue as unread."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="3", status="read", read_at=datetime.now(UTC))
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 204

    await async_db.refresh(issue)
    assert issue.status == "unread"
    assert issue.read_at is None


@pytest.mark.asyncio
async def test_mark_issue_unread_reactivates_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markUnread reactivates thread if it was completed."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        user_id=user.id,
        total_issues=3,
        reading_progress="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="2", status="read", read_at=datetime.now(UTC))
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 204

    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.reading_progress == "in_progress"
    assert thread.issues_remaining == 1


@pytest.mark.asyncio
async def test_mark_issue_unread_already_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markUnread returns 400 if issue already unread."""
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

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 400
    assert "already marked as unread" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mark_issue_unread_not_found(auth_client: AsyncClient) -> None:
    """POST /issues/{issue_id}:markUnread returns 404 for non-existent issue."""
    response = await auth_client.post("/api/v1/issues/999:markUnread")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mark_issue_unread_other_user_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:markUnread returns 404 for issue owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(thread_id=thread.id, issue_number="1", status="read", read_at=datetime.now(UTC))
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
