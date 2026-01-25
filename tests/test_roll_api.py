"""Tests for roll API endpoints."""

import pytest
from sqlalchemy import select



@pytest.mark.asyncio
async def test_roll_success(auth_client, sample_data):
    """POST /roll/ returns valid thread."""
    response = await auth_client.post("/api/roll/")
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
async def test_roll_override(auth_client, sample_data):
    """POST /roll/override/ sets specific thread."""
    thread_id = 1
    response = await auth_client.post("/api/roll/override", json={"thread_id": thread_id})
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["title"] == "Superman"
    assert data["die_size"] == 8
    assert data["result"] == 0


@pytest.mark.asyncio
async def test_roll_no_pool(auth_client, db):
    """Returns error if no active threads."""
    from tests.conftest import get_or_create_user

    get_or_create_user(db)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 400
    assert "No active threads" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_overflow(auth_client, db):
    """Roll works correctly when thread count < die size."""
    from app.models import Thread
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread.id
    assert 1 <= data["result"] <= 1


@pytest.mark.asyncio
async def test_roll_override_nonexistent(auth_client, sample_data):
    """Override returns 404 for non-existent thread."""
    response = await auth_client.post("/api/roll/override", json={"thread_id": 999})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_set_manual_die(auth_client, sample_data, db):
    """POST /roll/set-die sets manual_die on session."""
    response = await auth_client.post("/api/roll/set-die?die=20")
    assert response.status_code == 200
    assert response.text == "d20"

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    assert session_data["manual_die"] == 20


@pytest.mark.asyncio
async def test_clear_manual_die(auth_client, sample_data, db):
    """POST /roll/clear-manual-die clears manual_die and returns to auto mode."""
    from app.models import Session as SessionModel

    session = (
        db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalars().first()
    )
    assert session is not None

    session.manual_die = 12
    db.commit()

    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text == "d8"

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    assert session_data["manual_die"] is None


@pytest.mark.asyncio
async def test_clear_manual_die_with_no_manual_set(auth_client, sample_data):
    """POST /roll/clear-manual-die works even when manual_die is not set."""
    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text == "d8"


@pytest.mark.asyncio
async def test_clear_manual_die_returns_correct_current_die_regression(
    auth_client, sample_data, db
):
    """Regression test for bug where clearing manual die returned wrong die value.

    When manual mode is disengaged by clicking auto, the endpoint should return
    the correct current die from the dice ladder, not a stale cached value.
    """
    from app.models import Session as SessionModel

    session = (
        db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalars().first()
    )
    assert session is not None

    session.manual_die = 20
    db.commit()

    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    assert session_data["manual_die"] is None
    assert response.text == f"d{session_data['current_die']}"
