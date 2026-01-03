"""Tests for roll API endpoints."""

import pytest
from sqlalchemy import select

from app.models import Event


@pytest.mark.asyncio
async def test_roll_success(client, sample_data):
    """POST /roll/ returns valid thread."""
    response = await client.post("/roll/")
    assert response.status_code == 200

    data = response.json()
    assert "thread_id" in data
    assert "title" in data
    assert "die_size" in data
    assert "result" in data
    assert data["die_size"] == 8
    assert 1 <= data["result"] <= 8

    thread_ids = [t.id for t in sample_data["threads"] if t.status == "active"]
    assert data["thread_id"] in thread_ids


@pytest.mark.asyncio
async def test_roll_override(client, sample_data):
    """POST /roll/override/ sets specific thread."""
    thread_id = 1
    response = await client.post("/roll/override", json={"thread_id": thread_id})
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["title"] == "Superman"
    assert data["die_size"] == 8
    assert data["result"] == 0


@pytest.mark.asyncio
async def test_roll_no_pool(client, db):
    """Returns error if no active threads."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)
    db.commit()

    response = await client.post("/roll/")
    assert response.status_code == 400
    assert "No active threads" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_overflow(client, db):
    """Roll works correctly when thread count < die size."""
    from app.models import Thread, User

    user = User(id=1, username="test_user")
    db.add(user)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)
    db.commit()

    response = await client.post("/roll/")
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == 1
    assert 1 <= data["result"] <= 1


@pytest.mark.asyncio
async def test_roll_override_nonexistent(client, sample_data):
    """Override returns 404 for non-existent thread."""
    response = await client.post("/roll/override", json={"thread_id": 999})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reroll_success(client, sample_data, db):
    """POST /roll/reroll returns new roll with reroll selection method."""
    response = await client.post("/roll/reroll")
    assert response.status_code == 200
    html = response.text
    assert "Rerolled" in html
    assert "result-reveal" in html
    assert "rating-form-container" in html

    new_events = db.execute(select(Event).where(Event.selection_method == "reroll")).scalars().all()
    assert len(new_events) == 1
    reroll_event = new_events[0]
    assert reroll_event.type == "roll"
    assert reroll_event.selection_method == "reroll"
    assert reroll_event.session_id is not None


@pytest.mark.asyncio
async def test_reroll_no_pool(client, db):
    """Returns error if no active threads."""
    from app.models import User

    user = User(id=1, username="test_user")
    db.add(user)
    db.commit()

    response = await client.post("/roll/reroll")
    assert response.status_code == 200
    assert "No active threads" in response.text
