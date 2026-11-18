"""Tests for issue-order API endpoints that remain on Python.

The GET issue-list handler now runs in native Rust v2; its Python-only
regressions were retired with the handler. The order-validation and API
ordering checks below cover Python routes that are still live.
"""

from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from tests.conftest import get_or_create_user_async

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


async def test_issue_ordering_in_api_response(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The Python create endpoint stores annual issues in canonical position order."""
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

    rows = (
        await async_db.execute(
            select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
        )
    ).scalars().all()
    assert len(rows) == 11
    assert [row.issue_number for row in rows] == [str(i) for i in range(1, 11)] + ["Annual 2"]
