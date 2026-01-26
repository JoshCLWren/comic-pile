"""Edge case tests for queue reordering operations."""

import pytest

from app.models import Thread


@pytest.mark.asyncio
async def test_move_first_to_front_no_op(auth_client, db, sample_data):
    """Moving first thread to front is a no-op."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["queue_position"] == 1

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
async def test_move_last_to_back_no_op(auth_client, db, sample_data):
    """Moving last thread to back is a no-op."""
    thread_id = sample_data["threads"][4].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["queue_position"] == 5

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread3 = db.get(Thread, sample_data["threads"][2].id)

    assert thread1.queue_position == 1
    assert thread2.queue_position == 2
    assert thread3.queue_position == 3


@pytest.mark.asyncio
async def test_move_to_position_clamps_to_max(auth_client, db, sample_data):
    """Moving to position > max_position clamps to max."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.get("/api/threads/")
    threads = response.json()
    active_threads = [t for t in threads if t["status"] == "active"]
    max_position = len(active_threads)

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": max_position + 10}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == max_position


@pytest.mark.asyncio
async def test_move_to_position_clamps_to_min(auth_client, sample_data):
    """Moving to position < 1 returns validation error."""
    thread_id = sample_data["threads"][-1].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 0}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_move_to_position_when_no_threads(auth_client, db, default_user):
    """Moving to position when no threads handles gracefully."""
    from app.models import Thread as ThreadModel

    thread = ThreadModel(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    response = await auth_client.put(
        f"/api/queue/threads/{thread.id}/position/", json={"new_position": 1}
    )
    assert response.status_code == 200

    thread = db.get(ThreadModel, thread.id)
    assert thread.queue_position == 1
