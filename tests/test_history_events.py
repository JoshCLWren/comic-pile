"""Tests for history event logging."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_delete_thread_creates_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Test that deleting a thread creates a delete event.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    from app.models import Event, Thread

    result = await async_db.execute(select(Event).where(Event.type == "delete"))
    initial_delete_count = len(result.scalars().all())

    create_response = await auth_client.post(
        "/api/v1/threads/",
        json={"title": "Test Thread", "format": "Comic", "issues_remaining": 5},
    )
    assert create_response.status_code == 201
    thread_id = create_response.json()["id"]

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    owner_id = thread.user_id

    delete_response = await auth_client.delete(f"/api/v1/threads/{thread_id}")
    assert delete_response.status_code == 204

    result = await async_db.execute(select(Event).where(Event.type == "delete"))
    final_delete_events = result.scalars().all()
    final_delete_count = len(final_delete_events)

    assert final_delete_count == initial_delete_count + 1
    assert any(event.user_id == owner_id for event in final_delete_events)

    db_thread = await async_db.get(Thread, thread_id)
    assert db_thread is None
