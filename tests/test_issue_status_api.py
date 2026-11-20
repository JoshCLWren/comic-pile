"""Tests for Issue Read/Unread status API."""

from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User
from tests.conftest import get_or_create_user_async

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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
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
    assert event.issue_number == "1"

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

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
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
    assert event.issue_number == "1"

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

    issue1 = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
        read_at=None,
    )
    issue2 = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
        read_at=None,
    )
    issue3 = Issue(
        thread_id=thread.id,
        issue_number="3",
        position=3,
        status="unread",
        read_at=None,
    )
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

    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        for i in range(1, 6)
    ]
    for issue in issues:
        async_db.add(issue)
    await async_db.flush()

    thread.next_unread_issue_id = issues[0].id
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issues[0].id}:markRead")
    assert response.status_code == 204

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[1].id

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
        Issue(
            thread_id=thread.id,
            issue_number="1",
            position=1,
            status="read",
            read_at=datetime.now(UTC),
        ),
        Issue(
            thread_id=thread.id,
            issue_number="2",
            position=2,
            status="read",
            read_at=datetime.now(UTC),
        ),
        Issue(thread_id=thread.id, issue_number="3", position=3, status="unread"),
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

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
    assert response.status_code == 400
    assert "already marked as read" in response.json()["detail"].lower()

async def test_mark_issue_read_not_found(auth_client: AsyncClient) -> None:
    """POST /issues/{issue_id}:markRead returns 404 for non-existent issue."""
    response = await auth_client.post("/api/v1/issues/999:markRead")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

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

    issue = Issue(
        thread_id=thread.id,
        issue_number="3",
        position=3,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 204

    await async_db.refresh(issue)
    assert issue.status == "unread"
    assert issue.read_at is None

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

    issue = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 204

    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.reading_progress == "in_progress"
    assert thread.issues_remaining == 1

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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 400
    assert "already marked as unread" in response.json()["detail"].lower()

async def test_mark_issue_unread_not_found(auth_client: AsyncClient) -> None:
    """POST /issues/{issue_id}:markUnread returns 404 for non-existent issue."""
    response = await auth_client.post("/api/v1/issues/999:markUnread")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

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

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markUnread")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

async def test_mark_annual_unread_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /issues/{issue_id}:markUnread works with annuals (regression test for position comparison)."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="completed",
        user_id=user.id,
        total_issues=5,
        reading_progress="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue1 = Issue(
        thread_id=thread.id, issue_number="1", position=1, status="read", read_at=datetime.now(UTC)
    )
    issue2 = Issue(
        thread_id=thread.id,
        issue_number="Annual 1",
        position=2,
        status="read",
        read_at=datetime.now(UTC),
    )
    issue3 = Issue(thread_id=thread.id, issue_number="2", position=3, status="unread")
    async_db.add_all([issue1, issue2, issue3])
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue2.id}:markUnread")
    assert response.status_code == 204

    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.reading_progress == "in_progress"
    assert thread.next_unread_issue_id == issue2.id

async def test_bulk_mark_issue_read_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /issues:bulkMarkRead marks multiple issues as read."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Bulk Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="in_progress",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    i1 = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread", read_at=None)
    i2 = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread", read_at=None)
    async_db.add(i1)
    async_db.add(i2)
    await async_db.commit()

    response = await auth_client.post("/api/v1/issues:bulkMarkRead", json={"issue_ids": [i1.id, i2.id]})
    assert response.status_code == 204
    await async_db.refresh(i1)
    await async_db.refresh(i2)
    await async_db.refresh(thread)
    assert i1.status == "read"
    assert i2.status == "read"
    assert thread.status == "completed"

async def test_bulk_mark_issue_unread_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /issues:bulkMarkUnread marks multiple issues as unread."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Bulk Unread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        user_id=user.id,
        total_issues=2,
        reading_progress="completed",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    i1 = Issue(thread_id=thread.id, issue_number="1", position=1, status="read", read_at=datetime.now(UTC))
    i2 = Issue(thread_id=thread.id, issue_number="2", position=2, status="read", read_at=datetime.now(UTC))
    async_db.add(i1)
    async_db.add(i2)
    await async_db.commit()

    response = await auth_client.post("/api/v1/issues:bulkMarkUnread", json={"issue_ids": [i1.id, i2.id]})
    assert response.status_code == 204
    await async_db.refresh(i1)
    await async_db.refresh(i2)
    await async_db.refresh(thread)
    assert i1.status == "unread"
    assert i2.status == "unread"
    assert thread.status == "active"

async def test_bulk_mark_issue_read_bad_request_empty(auth_client: AsyncClient) -> None:
    """POST /issues:bulkMarkRead returns 422 for empty list."""
    response = await auth_client.post("/api/v1/issues:bulkMarkRead", json={"issue_ids": []})
    assert response.status_code == 422

