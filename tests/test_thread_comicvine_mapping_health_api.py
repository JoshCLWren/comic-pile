"""Focused API tests for the per-thread ComicVine mapping health endpoint (#2723)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_thread_comicvine_mapping_health_unresolved(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unresolved thread reports unresolved status."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Unresolved Series",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    async_db.add_all(
        [
            Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
            Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
        ]
    )
    await async_db.commit()

    response = await auth_client.get(
        f"/api/v1/threads/{thread.id}/comicvine-mapping-health"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unresolved"
    assert data["tracked_issue_count"] == 2
    assert data["confirmed_issue_count"] == 0


@pytest.mark.asyncio
async def test_thread_comicvine_mapping_health_not_found_for_other_user(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Other user's thread returns 404."""
    # Create a thread owned by a different user by inserting directly with a new user id.
    from app.models import User

    other = User(username="other", email="other@example.com", password_hash="x")
    async_db.add(other)
    await async_db.flush()

    thread = Thread(
        user_id=other.id,
        title="Other Series",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.commit()

    response = await auth_client.get(
        f"/api/v1/threads/{thread.id}/comicvine-mapping-health"
    )

    assert response.status_code == 404