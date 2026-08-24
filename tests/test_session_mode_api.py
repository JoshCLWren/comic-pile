"""Tests for the canonical session-mode API used by the reading quiz (#1736)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as SessionModel
from app.models import User
from tests.conftest import get_or_create_user_async


async def _create_session(async_db: AsyncSession, user_id: int) -> SessionModel:
    """Create and persist a fresh active session for a user."""
    session = SessionModel(start_die=6, user_id=user_id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)
    return session


@pytest.mark.asyncio
async def test_quiz_submission_sets_session_mode(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A full quiz submission persists bandwidth/intent with source=quiz."""
    user = await get_or_create_user_async(async_db)
    session = await _create_session(async_db, user.id)

    response = await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"bandwidth": "light", "intent": "momentum", "source": "quiz"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "session_id": session.id,
        "bandwidth": "light",
        "intent": "momentum",
        "source": "quiz",
    }

    persisted = await async_db.get(SessionModel, session.id)
    assert persisted is not None
    assert persisted.reading_bandwidth == "light"
    assert persisted.reading_intent == "momentum"
    assert persisted.reading_mode_source == "quiz"


@pytest.mark.asyncio
async def test_get_mode_returns_persisted_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """GET returns the stored mode values for an owned session."""
    user = await get_or_create_user_async(async_db)
    session = await _create_session(async_db, user.id)

    empty = await auth_client.get(f"/api/sessions/{session.id}/mode")
    assert empty.status_code == 200
    assert empty.json()["bandwidth"] is None
    assert empty.json()["intent"] is None

    await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"bandwidth": "deep", "intent": "explore"},
    )

    filled = await auth_client.get(f"/api/sessions/{session.id}/mode")
    assert filled.status_code == 200
    data = filled.json()
    assert data["bandwidth"] == "deep"
    assert data["intent"] == "explore"
    assert data["source"] == "quiz"


@pytest.mark.asyncio
async def test_partial_update_preserves_other_axis(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Updating one axis leaves the other untouched."""
    user = await get_or_create_user_async(async_db)
    session = await _create_session(async_db, user.id)

    await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"bandwidth": "balanced", "intent": "familiar"},
    )
    response = await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"intent": "random", "source": "manual"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["bandwidth"] == "balanced"
    assert data["intent"] == "random"
    assert data["source"] == "manual"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"bandwidth": "spicy", "intent": "momentum"},
        {"bandwidth": "light", "intent": "chaotic"},
        {"source": "quiz"},
        {"bandwidth": None, "intent": None, "source": "quiz"},
    ],
)
async def test_invalid_payloads_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    payload: dict[str, object],
) -> None:
    """Invalid mode values or missing axes return 422 and persist nothing."""
    user = await get_or_create_user_async(async_db)
    session = await _create_session(async_db, user.id)

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/mode", json=payload)
    assert response.status_code == 422

    persisted = await async_db.get(SessionModel, session.id)
    assert persisted is not None
    assert persisted.reading_bandwidth is None
    assert persisted.reading_intent is None


@pytest.mark.asyncio
async def test_unknown_session_returns_404(auth_client: AsyncClient) -> None:
    """Modes cannot be read or set for sessions that do not exist."""
    get_response = await auth_client.get("/api/v1/sessions/999999/mode")
    assert get_response.status_code == 404

    post_response = await auth_client.post(
        "/api/v1/sessions/999999/mode",
        json={"bandwidth": "light", "intent": "momentum"},
    )
    assert post_response.status_code == 404


@pytest.mark.asyncio
async def test_other_users_session_returns_404(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A session owned by a different user is invisible to the caller."""
    import time

    other_user = User(username=f"mode_other_user_{time.time_ns()}")
    async_db.add(other_user)
    await async_db.commit()
    await async_db.refresh(other_user)

    session = await _create_session(async_db, other_user.id)

    response = await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"bandwidth": "light", "intent": "momentum"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ended_session_returns_409(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Reading mode is ephemeral; ended sessions can no longer be changed."""
    from datetime import UTC, datetime

    user = await get_or_create_user_async(async_db)
    session = SessionModel(
        start_die=6,
        user_id=user.id,
        ended_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"bandwidth": "light", "intent": "momentum"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_bootstrap_reflects_updated_mode_for_subsequent_rolls(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """After the quiz, the Roll bootstrap exposes the new mode to later rolls."""
    user = await get_or_create_user_async(async_db)
    session = await _create_session(async_db, user.id)

    before = await auth_client.get("/api/roll/bootstrap")
    assert before.status_code == 200
    assert before.json()["bandwidth"] is None
    assert before.json()["intent"] is None

    set_response = await auth_client.post(
        f"/api/v1/sessions/{session.id}/mode",
        json={"bandwidth": "deep", "intent": "random", "source": "quiz"},
    )
    assert set_response.status_code == 200

    after = await auth_client.get("/api/roll/bootstrap")
    assert after.status_code == 200
    after_data = after.json()
    assert after_data["bandwidth"] == "deep"
    assert after_data["intent"] == "random"
    assert after_data["session_id"] == session.id


@pytest.mark.asyncio
async def test_mode_endpoint_not_mounted_under_bare_legacy_prefix(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """New client resources live only under /api/v1 (API versioning convention)."""
    user = await get_or_create_user_async(async_db)
    session = await _create_session(async_db, user.id)

    response = await auth_client.post(
        f"/api/sessions/{session.id}/mode",
        json={"bandwidth": "light", "intent": "explore", "source": "quiz"},
    )
    assert response.status_code == 404

    rows = await async_db.execute(
        select(SessionModel).where(SessionModel.id == session.id)
    )
    persisted = rows.scalar_one()
    assert persisted.reading_bandwidth is None
    assert persisted.reading_intent is None
