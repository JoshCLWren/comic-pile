"""Tests for queue API endpoints."""

import pytest

from app.models import Thread


@pytest.mark.asyncio
async def test_move_to_position(client, db, sample_data):
    """PUT /queue/threads/{id}/position/ works."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread2 = db.get(Thread, sample_data["threads"][0].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    assert thread2.queue_position == 2
    assert thread4.queue_position == 3


@pytest.mark.asyncio
async def test_move_to_front(client, db, sample_data):
    """PUT /queue/threads/{id}/front/ moves to position 1."""
    thread_id = sample_data["threads"][4].id

    response = await client.put(f"/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    assert thread1.queue_position == 2


@pytest.mark.asyncio
async def test_move_to_back(client, db, sample_data):
    """PUT /queue/threads/{id}/back/ moves to last position."""
    thread_id = sample_data["threads"][0].id

    response = await client.put(f"/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 5

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_queue_order_preserved(client, db, sample_data):
    """Other threads shift correctly when one moves."""
    thread_id = sample_data["threads"][1].id
    new_position = 4

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 4

    thread3 = db.get(Thread, sample_data["threads"][2].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    thread5 = db.get(Thread, sample_data["threads"][4].id)

    assert thread3.queue_position == 2
    assert thread4.queue_position == 3
    assert thread5.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_position_invalid(client, db, sample_data):
    """Moving to invalid position caps at boundaries."""
    thread_id = sample_data["threads"][2].id

    response = await client.put(f"/queue/threads/{thread_id}/position/", json={"new_position": 999})
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_position_zero(client, db, sample_data):
    """Moving to position 0 caps at 1."""
    thread_id = sample_data["threads"][2].id

    response = await client.put(f"/queue/threads/{thread_id}/position/", json={"new_position": 0})
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_get_roll_pool(client, sample_data):
    """GET /threads/ returns threads ordered by position."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 5

    for i in range(len(data) - 1):
        assert data[i]["position"] <= data[i + 1]["position"]


@pytest.mark.asyncio
async def test_move_completed_thread(client, db, sample_data):
    """Moving completed thread works correctly."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_nonexistent_thread(client, db, sample_data):
    """Returns 404 for non-existent thread."""
    response = await client.put("/queue/threads/999/front/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
