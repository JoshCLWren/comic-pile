"""Tests for session mode API endpoints (#1767).

Verifies the PATCH /api/roll/session-mode endpoint correctly updates
bandwidth and intent, including the random intent bypass.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_update_session_mode_bandwidth_only(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Updating only bandwidth preserves intent and returns updated mode."""
    _ = sample_data

    user_id = sample_data["user"].id
    result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id, SessionModel.ended_at.is_(None))
    )
    session = result.scalars().first()
    assert session is not None
    original_intent = session.active_intent

    response = await auth_client.patch("/api/roll/session-mode", json={"bandwidth": "deep"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_bandwidth"] == "deep"
    assert data["bandwidth_source"] == "manual"
    assert data["active_intent"] == original_intent
    assert data["intent_source"] == "inferred"  # Unchanged


@pytest.mark.asyncio
async def test_update_session_mode_intent_only(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Updating only intent preserves bandwidth and returns updated mode."""
    _ = sample_data

    user_id = sample_data["user"].id
    result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id, SessionModel.ended_at.is_(None))
    )
    session = result.scalars().first()
    assert session is not None
    original_bandwidth = session.active_bandwidth

    response = await auth_client.patch("/api/roll/session-mode", json={"intent": "momentum"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_intent"] == "momentum"
    assert data["intent_source"] == "manual"
    assert data["active_bandwidth"] == original_bandwidth
    assert data["bandwidth_source"] == "inferred"  # Unchanged


@pytest.mark.asyncio
async def test_update_session_mode_random_intent(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Setting intent to 'random' enables the user-level bypass."""
    _ = sample_data

    response = await auth_client.patch("/api/roll/session-mode", json={"intent": "random"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_intent"] == "random"
    assert data["intent_source"] == "manual"


@pytest.mark.asyncio
async def test_update_session_mode_both_dimensions(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Updating both bandwidth and intent in one request."""
    _ = sample_data

    response = await auth_client.patch(
        "/api/roll/session-mode", json={"bandwidth": "light", "intent": "explore"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["active_bandwidth"] == "light"
    assert data["bandwidth_source"] == "manual"
    assert data["active_intent"] == "explore"
    assert data["intent_source"] == "manual"


@pytest.mark.asyncio
async def test_update_session_mode_noop_returns_current(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Omitting both dimensions returns current mode unchanged."""
    _ = sample_data

    user_id = sample_data["user"].id
    result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id, SessionModel.ended_at.is_(None))
    )
    session = result.scalars().first()
    assert session is not None

    response = await auth_client.patch("/api/roll/session-mode", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["active_bandwidth"] == session.active_bandwidth
    assert data["active_intent"] == session.active_intent


@pytest.mark.asyncio
async def test_update_session_mode_invalid_bandwidth_rejected(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Invalid bandwidth value is rejected with 422."""
    _ = sample_data

    response = await auth_client.patch("/api/roll/session-mode", json={"bandwidth": "invalid"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_session_mode_invalid_intent_rejected(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Invalid intent value is rejected with 422."""
    _ = sample_data

    response = await auth_client.patch("/api/roll/session-mode", json={"intent": "invalid"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_session_mode_records_event(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Session mode change records a session_mode event."""
    _ = sample_data

    from app.models import Event

    response = await auth_client.patch("/api/roll/session-mode", json={"bandwidth": "deep"})
    assert response.status_code == 200

    user_id = sample_data["user"].id
    result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id, SessionModel.ended_at.is_(None))
    )
    session = result.scalars().first()
    assert session is not None

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "session_mode")
        .order_by(Event.id.desc())
    )
    mode_event = result.scalars().first()
    assert mode_event is not None
    assert mode_event.type == "session_mode"