"""Tests for Issue Create API endpoints."""

from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User
from tests.conftest import get_or_create_user_async

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

async def test_create_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """POST /threads/{thread_id}/issues returns 404 for non-existent thread."""
    response = await auth_client.post("/api/v1/threads/999/issues", json={"issue_range": "1-5"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

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

