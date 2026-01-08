"""Tests for history event logging."""

import pytest
from datetime import UTC, datetime
from sqlalchemy import select


@pytest.mark.asyncio
async def test_queue_move_creates_event(client, sample_data, db):
    """Test that moving a thread in queue creates a reorder event."""
    from app.models import Event, Thread

    thread_id = sample_data["threads"][0].id

    response = await client.put(f"/queue/threads/{thread_id}/position/", json={"new_position": 3})
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.type == "reorder").order_by(Event.timestamp.desc()))
        .scalars()
        .all()
    )

    assert len(events) >= 1
    reorder_event = next((e for e in events if e.thread_id == thread_id), None)
    assert reorder_event is not None
    assert reorder_event.type == "reorder"


@pytest.mark.asyncio
async def test_move_to_front_creates_event(client, sample_data, db):
    """Test that moving thread to front creates a reorder event."""
    from app.models import Event, Thread

    thread_id = sample_data["threads"][1].id

    response = await client.put(f"/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.type == "reorder").order_by(Event.timestamp.desc()))
        .scalars()
        .all()
    )

    assert len(events) >= 1
    reorder_event = next((e for e in events if e.thread_id == thread_id), None)
    assert reorder_event is not None
    assert reorder_event.type == "reorder"


@pytest.mark.asyncio
async def test_move_to_back_creates_event(client, sample_data, db):
    """Test that moving thread to back creates a reorder event."""
    from app.models import Event, Thread

    thread_id = sample_data["threads"][2].id

    response = await client.put(f"/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    events = (
        db.execute(select(Event).where(Event.type == "reorder").order_by(Event.timestamp.desc()))
        .scalars()
        .all()
    )

    assert len(events) >= 1
    reorder_event = next((e for e in events if e.thread_id == thread_id), None)
    assert reorder_event is not None
    assert reorder_event.type == "reorder"


@pytest.mark.asyncio
async def test_delete_thread_creates_event(client, sample_data, db):
    """Test that deleting a thread creates a delete event."""
    from app.models import Event, Thread

    initial_delete_count = len(
        db.execute(select(Event).where(Event.type == "delete")).scalars().all()
    )

    create_response = await client.post(
        "/threads/",
        json={"title": "Test Thread", "format": "Comic", "issues_remaining": 5},
    )
    assert create_response.status_code == 201
    thread_id = create_response.json()["id"]

    delete_response = await client.delete(f"/threads/{thread_id}")
    assert delete_response.status_code == 204

    final_delete_count = len(
        db.execute(select(Event).where(Event.type == "delete")).scalars().all()
    )

    assert final_delete_count == initial_delete_count + 1

    db_thread = db.get(Thread, thread_id)
    assert db_thread is None


@pytest.mark.asyncio
async def test_no_duplicate_event_on_no_movement(client, sample_data, db):
    """Test that moving to same position does not create event."""
    from app.models import Event, Thread

    thread_id = sample_data["threads"][0].id
    initial_event_count = len(
        db.execute(select(Event).where(Event.thread_id == thread_id)).scalars().all()
    )

    response = await client.put(f"/queue/threads/{thread_id}/position/", json={"new_position": 1})
    assert response.status_code == 200

    final_event_count = len(
        db.execute(select(Event).where(Event.thread_id == thread_id)).scalars().all()
    )

    assert initial_event_count == final_event_count
