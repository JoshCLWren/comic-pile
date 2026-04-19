"""Test to reproduce issue #504 - 500 error when creating issues."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_insert_after_issue_id_does_not_500_after_uq_constraint_migration(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test that insert_after_issue_id works correctly after uq_issue_thread_position migration.

    This test exercises the positional-insert path with a valid-but-unusual issue_range
    to ensure the deferred unique constraint migration doesn't cause 500 errors.
    """
    user = await get_or_create_user_async(async_db)

    # Create thread with existing issues to test positional-insert behavior
    thread = Thread(
        title="Test Thread for Deferred Constraint Migration",
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

    # Create existing issues to test insert_after_issue_id with positional logic
    existing_issue_1 = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(existing_issue_1)
    await async_db.flush()

    existing_issue_2 = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add(existing_issue_2)
    await async_db.flush()
    await async_db.commit()
    await async_db.refresh(existing_issue_2)

    # Test 1: Create issue with valid-but-unusual range using insert_after_issue_id
    # This exercises the positional-insert path after the deferred constraint migration
    create_response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={
            "issue_range": "esadfas3",
            "insert_after_issue_id": existing_issue_2.id,
        },
    )
    assert create_response.status_code == 201, (
        f"Expected 201, got {create_response.status_code}: {create_response.text}"
    )

    # Test 2: Verify duplicate issue number detection still works (should get 400)
    duplicate_response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues",
        json={
            "issue_range": "1",  # This already exists
            "insert_after_issue_id": existing_issue_2.id,
        },
    )
    assert duplicate_response.status_code == 400, (
        f"Expected 400, got {duplicate_response.status_code}: {duplicate_response.text}"
    )
