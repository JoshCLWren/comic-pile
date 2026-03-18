"""Tests for Issue API endpoints."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Event, Issue, Thread, User
from comic_pile.dependencies import refresh_user_blocked_status
from tests.conftest import get_or_create_user_async


async def _create_issue_tracking_thread(
    async_db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_specs: list[tuple[str, str]],
) -> tuple[Thread, list[Issue]]:
    """Create a thread with ordered issues for issue API tests."""
    unread_count = sum(1 for _, issue_status in issue_specs if issue_status == "unread")
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=unread_count,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=len(issue_specs),
        reading_progress="not_started" if unread_count == len(issue_specs) else "in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues: list[Issue] = []
    for position, (issue_number, issue_status) in enumerate(issue_specs, start=1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=issue_number,
            position=position,
            status=issue_status,
            read_at=datetime.now(UTC) if issue_status == "read" else None,
        )
        issues.append(issue)

    async_db.add_all(issues)
    await async_db.flush()

    first_unread = next((issue for issue in issues if issue.status == "unread"), None)
    thread.next_unread_issue_id = first_unread.id if first_unread else None
    if first_unread is None:
        thread.reading_progress = "completed"
        thread.status = "completed"

    await async_db.commit()
    return thread, issues


async def _get_thread_issues(async_db: AsyncSession, thread_id: int) -> list[Issue]:
    """Return issues for a thread ordered by position."""
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    return list(result.scalars().all())


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
    await async_db.flush()
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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
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
    await async_db.flush()
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/threads/{thread.id}/issues?page_token=invalid")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
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
    await async_db.flush()
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
    await async_db.flush()
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

    existing = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
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
async def test_create_issues_literal_range_identifier(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues accepts non-numeric ranges as literal identifiers."""
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
    assert response.status_code == 201
    data = response.json()
    # "1-Annual" is accepted as a literal identifier, "3" as a number
    issue_numbers = {issue["issue_number"] for issue in data["issues"]}
    assert issue_numbers == {"1-Annual", "3"}


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
        issue = Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-3"}
    )
    assert response.status_code == 400
    assert "already exist" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_issues_rejects_duplicate_issue_number_before_insert(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues returns 400 when all requested issues already exist."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Duplicate Guard Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    async_db.add(Issue(thread_id=thread.id, issue_number="7", position=1, status="unread"))
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={"issue_range": "7"},
    )
    assert response.status_code == 400
    assert "already exist" in response.json()["detail"].lower()

    issue_count_result = await async_db.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread.id)
    )
    assert issue_count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_create_issues_returns_409_on_db_unique_conflict(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /threads/{thread_id}/issues returns 409 when uq_issue_thread_number is hit."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Duplicate Conflict Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    thread_id = thread.id
    await async_db.commit()

    original_flush = async_db.flush
    conflict_injected = False

    async def flush_with_unique_conflict(*args, **kwargs) -> None:
        nonlocal conflict_injected
        pending_duplicate = next(
            (
                obj
                for obj in async_db.new
                if isinstance(obj, Issue) and obj.thread_id == thread_id and obj.issue_number == "7"
            ),
            None,
        )
        if pending_duplicate is not None and not conflict_injected:
            conflict_injected = True
            raise IntegrityError(
                "INSERT INTO issues",
                {},
                Exception(
                    'duplicate key value violates unique constraint "uq_issue_thread_number"'
                ),
            )
        await original_flush(*args, **kwargs)

    monkeypatch.setattr(async_db, "flush", flush_with_unique_conflict)

    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}/issues",
        json={"issue_range": "7"},
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()

    issue_count_result = await async_db.execute(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    )
    assert issue_count_result.scalar_one() == 0


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
    """POST /threads/{thread_id}/issues adds issues to thread already using issue tracking."""
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
    await async_db.flush()

    issues = []
    for i in range(1, 26):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            position=i,
            status="read" if i <= 15 else "unread",
            read_at=datetime.now(UTC) if i <= 15 else None,
        )
        async_db.add(issue)
        issues.append(issue)

    await async_db.flush()
    thread.next_unread_issue_id = issues[15].id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "26-30"}
    )
    assert response.status_code == 201

    data = response.json()
    assert data["total_count"] == 30
    assert len(data["issues"]) == 5

    await async_db.refresh(thread)
    assert thread.total_issues == 30
    assert thread.issues_remaining == 15
    assert thread.next_unread_issue_id == issues[15].id


@pytest.mark.asyncio
async def test_create_issues_already_migrated_preserves_not_started_when_all_issues_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues keeps not_started for fully unread migrated threads."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Not Started Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        for i in range(1, 4)
    ]
    async_db.add_all(issues)
    await async_db.flush()

    thread.next_unread_issue_id = issues[0].id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={"issue_range": "4-5"},
    )
    assert response.status_code == 201

    await async_db.refresh(thread)
    assert thread.total_issues == 5
    assert thread.issues_remaining == 5
    assert thread.next_unread_issue_id == issues[0].id
    assert thread.reading_progress == "not_started"


@pytest.mark.asyncio
async def test_create_issues_insert_in_middle_shifts_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues inserts new issues after a specific issue."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Insert Middle Thread",
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
    async_db.add_all(issues)
    await async_db.flush()

    thread.next_unread_issue_id = issues[0].id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={
            "issue_range": "Annual 1, Annual 2",
            "insert_after_issue_id": issues[1].id,
        },
    )
    assert response.status_code == 201

    data = response.json()
    assert [issue["issue_number"] for issue in data["issues"]] == ["Annual 1", "Annual 2"]
    assert [issue["position"] for issue in data["issues"]] == [3, 4]
    assert data["total_count"] == 7

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues_in_order = result.scalars().all()
    assert [issue.issue_number for issue in issues_in_order] == [
        "1",
        "2",
        "Annual 1",
        "Annual 2",
        "3",
        "4",
        "5",
    ]
    assert [issue.position for issue in issues_in_order] == list(range(1, 8))

    await async_db.refresh(thread)
    assert thread.total_issues == 7
    assert thread.issues_remaining == 7
    assert thread.next_unread_issue_id == issues[0].id


@pytest.mark.asyncio
async def test_create_issues_insert_after_last_issue_behaves_like_append(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues appends when inserting after the last issue."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Insert After Last Thread",
        format="Comic",
        issues_remaining=3,
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
        Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        for i in range(1, 4)
    ]
    async_db.add_all(issues)
    await async_db.flush()

    thread.next_unread_issue_id = issues[0].id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={"issue_range": "4-5", "insert_after_issue_id": issues[-1].id},
    )
    assert response.status_code == 201

    data = response.json()
    assert [issue["issue_number"] for issue in data["issues"]] == ["4", "5"]
    assert [issue["position"] for issue in data["issues"]] == [4, 5]
    assert data["total_count"] == 5

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues_in_order = result.scalars().all()
    assert [issue.issue_number for issue in issues_in_order] == ["1", "2", "3", "4", "5"]
    assert [issue.position for issue in issues_in_order] == [1, 2, 3, 4, 5]

    await async_db.refresh(thread)
    assert thread.total_issues == 5
    assert thread.issues_remaining == 5
    assert thread.next_unread_issue_id == issues[0].id


@pytest.mark.asyncio
async def test_create_issues_insert_after_issue_requires_issue_in_same_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues rejects insert_after_issue_id from another thread."""
    user = await get_or_create_user_async(async_db)

    target_thread = Thread(
        title="Target Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    other_thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([target_thread, other_thread])
    await async_db.flush()

    target_issues = [
        Issue(thread_id=target_thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=target_thread.id, issue_number="2", position=2, status="unread"),
    ]
    other_issue = Issue(thread_id=other_thread.id, issue_number="1", position=1, status="unread")
    async_db.add_all([*target_issues, other_issue])
    await async_db.flush()

    target_thread.next_unread_issue_id = target_issues[0].id
    other_thread.next_unread_issue_id = other_issue.id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}/issues",
        json={"issue_range": "Annual 1", "insert_after_issue_id": other_issue.id},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == target_thread.id).order_by(Issue.position)
    )
    issues_in_order = result.scalars().all()
    assert [issue.issue_number for issue in issues_in_order] == ["1", "2"]
    assert [issue.position for issue in issues_in_order] == [1, 2]

    await async_db.refresh(target_thread)
    assert target_thread.total_issues == 2
    assert target_thread.issues_remaining == 2
    assert target_thread.next_unread_issue_id == target_issues[0].id


@pytest.mark.asyncio
async def test_create_issues_insert_updates_next_unread_issue_id(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues updates next_unread when new issues come earlier."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Next Unread Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=4,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue_one = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    issue_two = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="read",
        read_at=datetime.now(UTC),
    )
    issue_three = Issue(thread_id=thread.id, issue_number="3", position=3, status="unread")
    issue_four = Issue(thread_id=thread.id, issue_number="4", position=4, status="unread")
    async_db.add_all([issue_one, issue_two, issue_three, issue_four])
    await async_db.flush()

    thread.next_unread_issue_id = issue_three.id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={"issue_range": "Special A, Special B", "insert_after_issue_id": issue_one.id},
    )
    assert response.status_code == 201

    data = response.json()
    assert [issue["issue_number"] for issue in data["issues"]] == ["Special A", "Special B"]
    assert [issue["position"] for issue in data["issues"]] == [2, 3]

    await async_db.refresh(thread)
    assert thread.total_issues == 6
    assert thread.issues_remaining == 4
    assert thread.next_unread_issue_id == data["issues"][0]["id"]

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues_in_order = result.scalars().all()
    assert [issue.issue_number for issue in issues_in_order] == [
        "1",
        "Special A",
        "Special B",
        "2",
        "3",
        "4",
    ]


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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_move_issue_to_top_reorders_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move can move an issue to the top of its thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move To Top Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[3].id}:move",
        json={"after_issue_id": None},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["4", "1", "2", "3"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[3].id


@pytest.mark.asyncio
async def test_move_issue_to_middle_reorders_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move can move an issue into the middle of a thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move To Middle Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[0].id}:move",
        json={"after_issue_id": issues[2].id},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["2", "3", "1", "4"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_move_issue_to_end_reorders_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move can move an issue to the end of a thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move To End Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[0].id}:move",
        json={"after_issue_id": issues[3].id},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["2", "3", "4", "1"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[1].id


@pytest.mark.asyncio
async def test_move_issue_not_found(auth_client: AsyncClient) -> None:
    """POST /issues/{issue_id}:move returns 404 for non-existent issue."""
    response = await auth_client.post("/api/v1/issues/999:move", json={"after_issue_id": None})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_move_issue_after_issue_must_be_in_same_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move rejects after_issue_id values from another thread."""
    user = await get_or_create_user_async(async_db)
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Target Move Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    other_thread, other_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Other Move Thread",
        issue_specs=[("A", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{target_issues[0].id}:move",
        json={"after_issue_id": other_issues[0].id},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    target_thread_issues = await _get_thread_issues(async_db, target_thread.id)
    assert [issue.issue_number for issue in target_thread_issues] == ["1", "2", "3"]
    assert [issue.position for issue in target_thread_issues] == [1, 2, 3]

    other_thread_issues = await _get_thread_issues(async_db, other_thread.id)
    assert [issue.issue_number for issue in other_thread_issues] == ["A"]
    assert [issue.position for issue in other_thread_issues] == [1]


@pytest.mark.asyncio
async def test_move_issue_recalculates_next_unread_issue_id(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move updates next_unread_issue_id from position order."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move Next Unread Thread",
        issue_specs=[("1", "read"), ("2", "read"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[3].id}:move",
        json={"after_issue_id": None},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["4", "1", "2", "3"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[3].id


@pytest.mark.asyncio
async def test_move_issue_refreshes_blocked_status_from_new_next_unread_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move refreshes blocked flags after changing next unread."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move Block Source Thread",
        issue_specs=[("Alpha", "unread")],
    )
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move Block Target Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[0].id,  # Changed to target issue 1 (next unread)
        )
    )
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    response = await auth_client.post(
        f"/api/v1/issues/{target_issues[2].id}:move",
        json={"after_issue_id": None},
    )
    assert response.status_code == 204

    await async_db.refresh(target_thread)
    assert target_thread.next_unread_issue_id == target_issues[2].id
    assert target_thread.is_blocked is True
    assert target_thread.is_blocked is True


@pytest.mark.asyncio
async def test_reorder_issues_updates_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder rewrites issue positions from the request order."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Bulk Reorder Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "read"), ("4", "unread")],
    )

    requested_order = [issues[2].id, issues[0].id, issues[3].id, issues[1].id]
    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues:reorder",
        json={"issue_ids": requested_order},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.id for issue in reordered_issues] == requested_order
    assert [issue.issue_number for issue in reordered_issues] == ["3", "1", "4", "2"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[0].id


@pytest.mark.asyncio
async def test_reorder_issues_refreshes_blocked_status_from_new_next_unread_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder refreshes blocked flags after reordering."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Reorder Block Source Thread",
        issue_specs=[("Alpha", "unread")],
    )
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Reorder Block Target Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[0].id,  # Changed to target issue 1 (next unread)
        )
    )
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    response = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}/issues:reorder",
        json={"issue_ids": [target_issues[1].id, target_issues[0].id, target_issues[2].id]},
    )
    assert response.status_code == 204

    await async_db.refresh(target_thread)
    assert (
        target_thread.next_unread_issue_id == target_issues[0].id
    )  # After reorder, issue 1 is still first
    assert target_thread.is_blocked is True


@pytest.mark.asyncio
async def test_reorder_issues_rejects_missing_issue_ids(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder returns 400 when request omits thread issues."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Missing IDs Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues:reorder",
        json={"issue_ids": [issues[0].id, issues[2].id]},
    )
    assert response.status_code == 400
    assert "exactly once" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reorder_issues_rejects_extra_issue_ids(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder returns 400 when request has extra IDs."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Extra IDs Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    _, other_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Other Extra IDs Thread",
        issue_specs=[("A", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues:reorder",
        json={"issue_ids": [issues[0].id, issues[1].id, issues[2].id, other_issues[0].id]},
    )
    assert response.status_code == 400
    assert "exactly once" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_middle_issue_shifts_positions_and_logs_event(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} deletes a middle issue and compacts later positions."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Middle Thread",
        issue_specs=[("1", "unread"), ("2", "read"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.delete(f"/api/v1/issues/{issues[1].id}")
    assert response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in remaining_issues] == ["1", "3", "4"]
    assert [issue.position for issue in remaining_issues] == [1, 2, 3]

    await async_db.refresh(thread)
    assert thread.total_issues == 3
    assert thread.issues_remaining == 3
    assert thread.next_unread_issue_id == issues[0].id
    assert thread.reading_progress == "not_started"
    assert thread.status == "active"

    event_result = await async_db.execute(
        select(Event).where(
            Event.thread_id == thread.id,
            Event.type == "issue_deleted",
            Event.issue_number == "2",
        )
    )
    event = event_result.scalar_one_or_none()
    assert event is not None
    assert event.type == "issue_deleted"


@pytest.mark.asyncio
async def test_delete_last_issue_leaves_prior_positions_unchanged(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} leaves earlier positions unchanged when deleting the end."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Last Thread",
        issue_specs=[("1", "read"), ("2", "unread"), ("3", "read")],
    )

    response = await auth_client.delete(f"/api/v1/issues/{issues[2].id}")
    assert response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in remaining_issues] == ["1", "2"]
    assert [issue.position for issue in remaining_issues] == [1, 2]

    await async_db.refresh(thread)
    assert thread.total_issues == 2
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id == issues[1].id
    assert thread.reading_progress == "in_progress"


@pytest.mark.asyncio
async def test_delete_next_unread_issue_advances_pointer_and_deletes_dependencies(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} advances next_unread_issue_id and removes issue dependencies."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Dependency Source Thread",
        issue_specs=[("Alpha", "unread")],
    )
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Next Unread Thread",
        issue_specs=[("1", "read"), ("2", "unread"), ("3", "unread"), ("4", "read")],
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[1].id,
        )
    )
    await async_db.commit()

    response = await auth_client.delete(f"/api/v1/issues/{target_issues[1].id}")
    assert response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, target_thread.id)
    assert [issue.issue_number for issue in remaining_issues] == ["1", "3", "4"]
    assert [issue.position for issue in remaining_issues] == [1, 2, 3]

    await async_db.refresh(target_thread)
    assert target_thread.next_unread_issue_id == target_issues[2].id
    assert target_thread.issues_remaining == 1
    assert target_thread.reading_progress == "in_progress"

    dependency_count_result = await async_db.execute(
        select(func.count())
        .select_from(Dependency)
        .where(Dependency.target_issue_id == target_issues[1].id)
    )
    assert dependency_count_result.scalar_one() == 0


@pytest.mark.asyncio
async def test_delete_all_issues_completes_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} can remove the final issues and complete the thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete All Issues Thread",
        issue_specs=[("1", "unread"), ("2", "unread")],
    )

    first_response = await auth_client.delete(f"/api/v1/issues/{issues[0].id}")
    assert first_response.status_code == 204

    second_response = await auth_client.delete(f"/api/v1/issues/{issues[1].id}")
    assert second_response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, thread.id)
    assert remaining_issues == []

    await async_db.refresh(thread)
    assert thread.total_issues == 0
    assert thread.issues_remaining == 0
    assert thread.next_unread_issue_id is None
    assert thread.reading_progress == "completed"
    assert thread.status == "completed"


@pytest.mark.asyncio
async def test_delete_issue_not_found(auth_client: AsyncClient) -> None:
    """DELETE /issues/{issue_id} returns 404 for non-existent issues."""
    response = await auth_client.delete("/api/v1/issues/999")
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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
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

    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
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


@pytest.mark.asyncio
async def test_create_issues_validates_no_position_duplicates(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues validates no duplicate positions in new issues."""
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

    for i in range(1, 6):
        issue = Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "6-10"}
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 5
    assert data["total_count"] == 10

    positions = [issue["position"] for issue in data["issues"]]
    assert len(positions) == len(set(positions)), (
        f"Response contains duplicate positions: {positions}"
    )

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    db_issues = result.scalars().all()
    db_positions = [issue.position for issue in db_issues]

    assert len(db_positions) == len(set(db_positions)), (
        f"Database contains duplicate positions: {db_positions}"
    )
    assert db_positions == list(range(1, 11))


@pytest.mark.asyncio
async def test_create_issues_validates_no_position_conflicts_with_existing(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues validates no position conflicts with existing issues."""
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

    for i in range(1, 6):
        issue = Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "6-10"}
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 5
    assert data["total_count"] == 10

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    db_issues = result.scalars().all()
    db_positions = [issue.position for issue in db_issues]

    assert len(db_positions) == len(set(db_positions)), (
        f"Database contains duplicate positions: {db_positions}"
    )
    assert db_positions == list(range(1, 11))


@pytest.mark.asyncio
async def test_insert_annual_after_existing_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test inserting Annual 2 after issue 5.

    Existing: Issues 1-10 at positions 1-10
    Request: "1-5, Annual 2"
    Expected: Annual 2 at position 11
    """
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

    data = response.json()
    assert len(data["issues"]) == 1
    assert data["issues"][0]["issue_number"] == "Annual 2"
    assert data["issues"][0]["position"] == 11

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()
    assert [i.issue_number for i in issues] == [str(i) for i in range(1, 11)] + ["Annual 2"]
    assert [i.position for i in issues] == list(range(1, 12))


@pytest.mark.asyncio
async def test_insert_multiple_annuals_in_middle(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test inserting multiple annuals are appended after all existing issues.

    Existing: Issues 1-10 at positions 1-10
    Request: "1-3, Annual 1, 4-6, Annual 2, 7-10"
    Expected: Annual 1 at position 11, Annual 2 at position 12 (after all existing issues)
    """
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
        f"/api/v1/threads/{thread.id}/issues",
        json={"issue_range": "1-3, Annual 1, 4-6, Annual 2, 7-10"},
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 2

    annual_1 = next(i for i in data["issues"] if i["issue_number"] == "Annual 1")
    annual_2 = next(i for i in data["issues"] if i["issue_number"] == "Annual 2")

    assert annual_1["position"] == 11
    assert annual_2["position"] == 12

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()
    expected_order = [str(i) for i in range(1, 11)] + ["Annual 1", "Annual 2"]
    assert [i.issue_number for i in issues] == expected_order
    assert [i.position for i in issues] == list(range(1, 13))


@pytest.mark.asyncio
async def test_append_issues_to_end(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Test appending issues to the end.

    Existing: Issues 1-10 at positions 1-10
    Request: "11-15"
    Expected: Issues 11-15 at positions 11-15
    """
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
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "11-15"}
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 5
    assert data["total_count"] == 15

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()
    assert [i.issue_number for i in issues] == [str(i) for i in range(1, 16)]
    assert [i.position for i in issues] == list(range(1, 16))


@pytest.mark.asyncio
async def test_insert_annual_with_skipped_existing_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test inserting annual and missing issues when some in range already exist.

    Existing: Issues 1-5, 8-10 at positions 1-8
    Request: "1-5, Annual 1, 6-10"
    Expected: Annual 1, 6, 7 are appended (8 doesn't exist yet, 9-10 already exist)
    """
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=8,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    existing_numbers = ["1", "2", "3", "4", "5", "8", "9", "10"]
    for idx, num in enumerate(existing_numbers, start=1):
        issue = Issue(thread_id=thread.id, issue_number=num, position=idx, status="unread")
        async_db.add(issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5, Annual 1, 6-10"}
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 3

    annual_1 = next((i for i in data["issues"] if i["issue_number"] == "Annual 1"), None)
    issue_6 = next((i for i in data["issues"] if i["issue_number"] == "6"), None)
    issue_7 = next((i for i in data["issues"] if i["issue_number"] == "7"), None)

    assert annual_1 is not None
    assert issue_6 is not None
    assert issue_7 is not None
    assert annual_1["position"] == 9
    assert issue_6["position"] == 10
    assert issue_7["position"] == 11

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()
    expected_order = ["1", "2", "3", "4", "5", "8", "9", "10", "Annual 1", "6", "7"]
    assert [i.issue_number for i in issues] == expected_order


@pytest.mark.asyncio
async def test_insert_annual_before_existing_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test inserting annual when it appears before existing issues in request.

    Existing: Issues 1-10 at positions 1-10
    Request: "Annual 0, 1-5"
    Expected: Annual 0 at position 11 (always appended at end, can't insert at beginning)
    """
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
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "Annual 0, 1-5"}
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 1

    annual_0 = next(i for i in data["issues"] if i["issue_number"] == "Annual 0")
    assert annual_0["position"] == 11

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()
    expected_order = [str(i) for i in range(1, 11)] + ["Annual 0"]
    assert [i.issue_number for i in issues] == expected_order
    assert [i.position for i in issues] == list(range(1, 12))


@pytest.mark.asyncio
async def test_insert_mixed_annuals_and_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test inserting multiple annuals interspersed with regular issues into empty thread.

    Existing: None
    Request: "Annual 0, 1-3, Annual 1, 4-6"
    Expected: 8 issues created in requested order (Annual 0 at position 1, etc.)
    """
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

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "Annual 0, 1-3, Annual 1, 4-6"}
    )
    assert response.status_code == 201

    data = response.json()
    assert len(data["issues"]) == 8
    assert data["total_count"] == 8

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()
    expected_order = ["Annual 0", "1", "2", "3", "Annual 1", "4", "5", "6"]
    assert [i.issue_number for i in issues] == expected_order
    assert [i.position for i in issues] == list(range(1, 9))


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
