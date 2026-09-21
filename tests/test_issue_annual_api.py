"""Tests for Issue Annual insertion API."""

from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from tests.conftest import get_or_create_user_async

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

