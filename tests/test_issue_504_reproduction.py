"""Test to reproduce issue #504 - 500 error when creating issues."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_create_issue_with_invalid_range_reproduces_504(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Reproduce issue #504: Creating issue with 'esadfas3' range causes 500 error.
    
    This test simulates the exact curl request from the bug report:
    curl 'https://app-production-72b9.up.railway.app/api/v1/threads/377/issues' \
      -X POST \
      --data-raw '{"issue_range":"esadfas3","insert_after_issue_id":10882}'
    """
    user = await get_or_create_user_async(async_db)

    # Create thread with some existing issues
    thread = Thread(
        title="Test Thread for Issue #504",
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
    await async_db.commit()
    await async_db.refresh(thread)

    # Create some existing issues to have an insert_after_issue_id
    issue1 = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(issue1)
    await async_db.flush()

    issue2 = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add(issue2)
    await async_db.flush()
    await async_db.commit()
    await async_db.refresh(issue2)

    # Test 1: Try creating with valid unusual range (this should work)
    response1 = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={
            "issue_range": "esadfas3",
            "insert_after_issue_id": issue2.id,
        },
    )
    print(f"Test 1 - Response status: {response1.status_code}")
    print(f"Test 1 - Response body: {response1.text}")
    assert response1.status_code != 500, f"Got 500 error: {response1.text}"

    # Test 2: Try creating duplicate issue number (should get 409)
    response2 = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={
            "issue_range": "1",  # This already exists
            "insert_after_issue_id": issue2.id,
        },
    )
    print(f"Test 2 - Response status: {response2.status_code}")
    print(f"Test 2 - Response body: {response2.text}")
    assert response2.status_code == 409, (
        f"Expected 409, got {response2.status_code}: {response2.text}"
    )
