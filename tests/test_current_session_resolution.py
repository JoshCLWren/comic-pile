"""Regression coverage for authoritative current-session resolution."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as SessionModel
from app.models import Thread, User
from comic_pile.session import is_active


@pytest.mark.asyncio
async def test_current_session_prefers_older_pending_session_over_newer_blank_duplicate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The current-session endpoint must preserve active pending reading context."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)

    thread = Thread(
        title="Pending Comic",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    pending_session = SessionModel(
        started_at=now - timedelta(hours=2),
        start_die=10,
        user_id=user.id,
        pending_thread_id=thread.id,
        pending_thread_updated_at=now - timedelta(minutes=5),
    )
    newer_blank_session = SessionModel(
        started_at=now - timedelta(hours=1),
        start_die=6,
        user_id=user.id,
    )
    async_db.add_all([pending_session, newer_blank_session])
    await async_db.commit()
    await async_db.refresh(pending_session)
    await async_db.refresh(newer_blank_session)

    response = await auth_client.get("/api/sessions/current/")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == pending_session.id
    assert data["pending_thread_id"] == thread.id
    assert data["id"] != newer_blank_session.id


@pytest.mark.asyncio
async def test_current_session_creates_new_when_only_completed_sessions_exist(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The current-session endpoint creates a new session when only ended sessions exist."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    # Create only completed (ended) sessions
    old_session = SessionModel(
        started_at=datetime.now(UTC) - timedelta(hours=2),
        ended_at=datetime.now(UTC) - timedelta(hours=1),
        start_die=6,
        user_id=user.id,
    )
    async_db.add(old_session)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/current/")

    assert response.status_code == 200
    data = response.json()
    # Should have created a new session, not returned the ended one
    assert data["id"] != old_session.id
    assert data["ended_at"] is None
    assert data["start_die"] == 6  # Default start die


@pytest.mark.asyncio
async def test_is_active_rejects_timestamp_shared_by_multiple_users(
    async_db: AsyncSession,
) -> None:
    """A non-unique start timestamp must never confer cross-user session authority."""
    started_at = datetime.now(UTC) - timedelta(minutes=30)
    users = [User(username="timestamp-owner-a"), User(username="timestamp-owner-b")]
    async_db.add_all(users)
    await async_db.flush()

    sessions = [
        SessionModel(started_at=started_at, start_die=6, user_id=user.id)
        for user in users
    ]
    async_db.add_all(sessions)
    await async_db.commit()

    # Query by identity - each session should only be active for its own owner
    assert await is_active(sessions[0].id, sessions[0].user_id, async_db) is True
    assert await is_active(sessions[1].id, sessions[1].user_id, async_db) is True
    # Cross-user query should return False
    assert await is_active(sessions[0].id, sessions[1].user_id, async_db) is False
