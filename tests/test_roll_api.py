"""Tests for roll API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_roll_success(auth_client: AsyncClient, sample_data: dict) -> None:
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
async def test_roll_override(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/override/ sets specific thread."""
    _ = sample_data
    thread_id = 1
    response = await auth_client.post("/api/roll/override", json={"thread_id": thread_id})
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["title"] == "Superman"
    assert data["die_size"] == 8
    assert data["result"] == 0


@pytest.mark.asyncio
async def test_roll_no_pool(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Returns error if no active threads."""
    from tests.conftest import get_or_create_user_async

    await get_or_create_user_async(async_db)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 400
    assert "No active threads" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_overflow(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Roll works correctly when thread count < die size."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread.id
    assert 1 <= data["result"] <= 1


@pytest.mark.asyncio
async def test_roll_blocked_when_pending_exists(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/ returns 409 when a pending thread exists."""
    _ = sample_data

    first_response = await auth_client.post("/api/roll/")
    assert first_response.status_code == 200

    second_response = await auth_client.post("/api/roll/")
    assert second_response.status_code == 409
    assert "already pending" in second_response.json()["detail"]


@pytest.mark.asyncio
async def test_dismiss_pending_clears_pending_thread(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/dismiss-pending clears pending thread in current session."""
    _ = sample_data

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    before_session = await auth_client.get("/api/sessions/current/")
    assert before_session.status_code == 200
    assert before_session.json()["pending_thread_id"] is not None

    dismiss_response = await auth_client.post("/api/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    after_session = await auth_client.get("/api/sessions/current/")
    assert after_session.status_code == 200
    assert after_session.json()["pending_thread_id"] is None


@pytest.mark.asyncio
async def test_dismiss_pending_when_no_pending_exists(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/dismiss-pending is idempotent when no pending thread exists."""
    _ = sample_data

    before_session = await auth_client.get("/api/sessions/current/")
    assert before_session.status_code == 200
    assert before_session.json()["pending_thread_id"] is None

    dismiss_response = await auth_client.post("/api/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    after_session = await auth_client.get("/api/sessions/current/")
    assert after_session.status_code == 200
    assert after_session.json()["pending_thread_id"] is None


@pytest.mark.asyncio
async def test_roll_pending_message_does_not_leak_other_user_thread_title(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """POST /roll/ does not leak another user's thread title in pending-roll detail."""
    import os
    from datetime import UTC, datetime

    from app.models import Session as SessionModel, Thread
    from tests.conftest import get_or_create_user_async

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    current_session_id = session_response.json()["id"]

    other_user = await get_or_create_user_async(async_db, username=f"other_user_{os.getpid()}")
    private_title = "Private Other User Thread"
    private_thread = Thread(
        title=private_title,
        format="Comic",
        issues_remaining=3,
        queue_position=99,
        status="active",
        user_id=other_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(private_thread)
    await async_db.commit()
    await async_db.refresh(private_thread)

    current_session = await async_db.get(SessionModel, current_session_id)
    assert current_session is not None
    current_session.pending_thread_id = private_thread.id
    current_session.pending_thread_updated_at = datetime.now(UTC)
    await async_db.commit()

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 409
    detail = roll_response.json()["detail"]
    assert "already pending" in detail
    assert private_title not in detail


@pytest.mark.asyncio
async def test_roll_override_nonexistent(auth_client: AsyncClient, sample_data: dict) -> None:
    """Override returns 404 for non-existent thread."""
    _ = sample_data
    response = await auth_client.post("/api/roll/override", json={"thread_id": 999})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_set_manual_die(auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession) -> None:
    """POST /roll/set-die sets manual_die on session."""
    _ = sample_data
    _ = async_db
    response = await auth_client.post("/api/roll/set-die?die=20")
    assert response.status_code == 200
    assert response.text == "d20"

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    assert session_data["manual_die"] == 20


@pytest.mark.asyncio
async def test_clear_manual_die(auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession) -> None:
    """POST /roll/clear-manual-die clears manual_die and returns to auto mode."""
    _ = sample_data
    from app.models import Session as SessionModel

    result = await async_db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None)))
    session = result.scalars().first()
    assert session is not None

    session.manual_die = 12
    await async_db.commit()

    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text == "d8"

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    assert session_data["manual_die"] is None


@pytest.mark.asyncio
async def test_clear_manual_die_with_no_manual_set(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/clear-manual-die works even when manual_die is not set."""
    _ = sample_data
    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text == "d8"


@pytest.mark.asyncio
async def test_clear_manual_die_returns_correct_current_die_regression(auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession) -> None:
    """Regression test for bug where clearing manual die returned wrong die value.

    When manual mode is disengaged by clicking auto, the endpoint should return
    the correct current die from the dice ladder, not a stale cached value.
    """
    _ = sample_data
    from app.models import Session as SessionModel

    result = await async_db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None)))
    session = result.scalars().first()
    assert session is not None

    session.manual_die = 20
    await async_db.commit()

    response = await auth_client.post("/api/roll/clear-manual-die")
    assert response.status_code == 200

    session_response = await auth_client.get("/api/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    assert session_data["manual_die"] is None
    assert response.text == f"d{session_data['current_die']}"
