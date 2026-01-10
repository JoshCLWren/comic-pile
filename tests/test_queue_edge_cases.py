"""Edge case tests for queue reordering operations."""

import pytest

from app.models import Thread


@pytest.mark.asyncio
async def test_move_first_to_front_no_op(client, db, sample_data):
    """Moving first thread to front is a no-op."""
    thread_id = sample_data["threads"][0].id

    response = await client.put(f"/api/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread3 = db.get(Thread, sample_data["threads"][2].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    thread5 = db.get(Thread, sample_data["threads"][4].id)

    assert thread2.queue_position == 2
    assert thread3.queue_position == 3
    assert thread4.queue_position == 4
    assert thread5.queue_position == 5


@pytest.mark.asyncio
async def test_move_last_to_back_no_op(client, db, sample_data):
    """Moving last thread to back is a no-op."""
    thread_id = sample_data["threads"][4].id

    response = await client.put(f"/api/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 5

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread3 = db.get(Thread, sample_data["threads"][2].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)

    assert thread1.queue_position == 1
    assert thread2.queue_position == 2
    assert thread3.queue_position == 3
    assert thread4.queue_position == 4
