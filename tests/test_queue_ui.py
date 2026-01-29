"""Tests for queue UI button disabled states."""

import pytest
from httpx import AsyncClient

from app.models import Thread
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_jump_to_position_works_for_large_distance(
    auth_client, async_db: AsyncSession, sample_data
):
    """Jump from position 1 to last position works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.get("/api/threads/")
    threads = response.json()
    active_threads = [t for t in threads if t["status"] == "active"]
    last_position = len(active_threads)

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": last_position}
    )
    assert response.status_code == 200

    thread = await async_db.get(Thread, sample_data["threads"][0].id)
    assert thread is not None
    assert thread.queue_position == last_position


@pytest.mark.usefixtures("sample_data")
@pytest.mark.asyncio
async def test_jump_to_position_works_for_small_distance(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Jump from last position to position 1 works correctly."""
    response = await auth_client.get("/api/threads/")
    threads = response.json()
    last_thread_id = threads[-1]["id"]

    response = await auth_client.put(
        f"/api/queue/threads/{last_thread_id}/position/", json={"new_position": 1}
    )
    assert response.status_code == 200

    thread = await async_db.get(Thread, last_thread_id)
    assert thread is not None
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_drag_and_drop_updates_position(auth_client, async_db: AsyncSession, sample_data):
    """Drag and drop reordering updates position correctly."""
    thread_id = sample_data["threads"][0].id
    new_position = 3

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["queue_position"] == new_position

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    assert thread.queue_position == new_position


@pytest.mark.asyncio
async def test_move_to_front_via_api(auth_client, async_db: AsyncSession, sample_data):
    """Move to front endpoint works correctly."""
    thread_id = sample_data["threads"][2].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_to_back_via_api(auth_client, async_db: AsyncSession, sample_data):
    """Move to back endpoint works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.get("/api/threads/")
    threads = response.json()
    active_threads = [t for t in threads if t["status"] == "active"]
    last_position = max(t["queue_position"] for t in active_threads)

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    assert thread.queue_position == last_position
