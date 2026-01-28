"""Tests for history event logging."""

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_queue_move_creates_event(auth_client, sample_data, async_db):
    """Test that moving a thread in queue creates a reorder event."""
    from app.models import Event

    thread_id = sample_data["threads"][0].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 3}
    )
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.type == "reorder").order_by(Event.timestamp.desc())
    )
    events = result.scalars().all()

    assert len(events) >= 1
    reorder_event = next((e for e in events if e.thread_id == thread_id), None)
    assert reorder_event is not None
    assert reorder_event.type == "reorder"


@pytest.mark.asyncio
async def test_move_to_front_creates_event(auth_client, sample_data, async_db):
    """Test that moving thread to front creates a reorder event."""
    from app.models import Event

    thread_id = sample_data["threads"][1].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.type == "reorder").order_by(Event.timestamp.desc())
    )
    events = result.scalars().all()

    assert len(events) >= 1
    reorder_event = next((e for e in events if e.thread_id == thread_id), None)
    assert reorder_event is not None
    assert reorder_event.type == "reorder"


@pytest.mark.asyncio
async def test_move_to_back_creates_event(auth_client, sample_data, async_db):
    """Test that moving thread to back creates a reorder event."""
    from app.models import Event

    thread_id = sample_data["threads"][2].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.type == "reorder").order_by(Event.timestamp.desc())
    )
    events = result.scalars().all()

    assert len(events) >= 1
    reorder_event = next((e for e in events if e.thread_id == thread_id), None)
    assert reorder_event is not None
    assert reorder_event.type == "reorder"


@pytest.mark.asyncio
async def test_delete_thread_creates_event(auth_client, async_db):
    """Test that deleting a thread creates a delete event."""
    from app.models import Event, Thread

    result = await async_db.execute(select(Event).where(Event.type == "delete"))
    initial_delete_count = len(result.scalars().all())

    create_response = await auth_client.post(
        "/api/threads/",
        json={"title": "Test Thread", "format": "Comic", "issues_remaining": 5},
    )
    assert create_response.status_code == 201
    thread_id = create_response.json()["id"]

    delete_response = await auth_client.delete(f"/api/threads/{thread_id}")
    assert delete_response.status_code == 204

    result = await async_db.execute(select(Event).where(Event.type == "delete"))
    final_delete_count = len(result.scalars().all())

    assert final_delete_count == initial_delete_count + 1

    db_thread = await async_db.get(Thread, thread_id)
    assert db_thread is None


@pytest.mark.asyncio
async def test_no_duplicate_event_on_no_movement(auth_client, sample_data, async_db):
    """Test that moving to same position does not create event."""
    from app.models import Event

    thread_id = sample_data["threads"][0].id
    result = await async_db.execute(select(Event).where(Event.thread_id == thread_id))
    initial_event_count = len(result.scalars().all())

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 1}
    )
    assert response.status_code == 200

    result = await async_db.execute(select(Event).where(Event.thread_id == thread_id))
    final_event_count = len(result.scalars().all())

    assert initial_event_count == final_event_count
