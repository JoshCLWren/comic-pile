"""Tests for the manual session-mode change endpoint."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Event,
    RecommendationContext,
    Session as SessionModel,
    Thread,
)
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_update_session_mode_bandwidth_only(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PATCH bandwidth only; intent stays at its current value."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        user_id=user.id,
        title="Mode Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(
        user_id=user.id,
        start_die=6,
        started_at=datetime.now(UTC),
        active_intent="explore",
        predicted_intent="explore",
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)
    session_id = session.id

    response = await auth_client.patch(
        "/api/roll/session-mode",
        json={"bandwidth": "light"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["active_bandwidth"] == "light"
    assert data["predicted_bandwidth"] == "light"
    assert data["bandwidth_source"] == "manual"
    assert data["bandwidth_version"] is not None
    assert data["active_intent"] == "explore"
    assert data["predicted_intent"] == "explore"
    assert data["intent_source"] is None

    db_session = await async_db.get(SessionModel, session_id)
    assert db_session is not None
    assert db_session.active_bandwidth == "light"
    assert db_session.bandwidth_source == "manual"
    assert db_session.active_intent == "explore"


@pytest.mark.asyncio
async def test_update_session_mode_intent_only(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PATCH intent only; bandwidth stays at its current value."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        user_id=user.id,
        title="Mode Thread 2",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(
        user_id=user.id,
        start_die=6,
        started_at=datetime.now(UTC),
        active_bandwidth="balanced",
        predicted_bandwidth="balanced",
        bandwidth_confidence=0.9,
        bandwidth_source="inferred",
        bandwidth_version="infer-v1",
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.patch(
        "/api/roll/session-mode",
        json={"intent": "random"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["active_intent"] == "random"
    assert data["predicted_intent"] == "random"
    assert data["intent_source"] == "manual"
    assert data["intent_version"] is not None
    assert data["active_bandwidth"] == "balanced"
    assert data["predicted_bandwidth"] == "balanced"
    assert data["bandwidth_source"] == "inferred"


@pytest.mark.asyncio
async def test_update_session_mode_both_dimensions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PATCH both bandwidth and intent updates the session correctly."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        user_id=user.id,
        title="Mode Thread 3",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(
        user_id=user.id,
        start_die=6,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.patch(
        "/api/roll/session-mode",
        json={"bandwidth": "deep", "intent": "familiar"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["active_bandwidth"] == "deep"
    assert data["predicted_bandwidth"] == "deep"
    assert data["bandwidth_source"] == "manual"
    assert data["active_intent"] == "familiar"
    assert data["predicted_intent"] == "familiar"
    assert data["intent_source"] == "manual"


@pytest.mark.asyncio
async def test_update_session_mode_empty_body_is_noop(
    auth_client: AsyncClient,
) -> None:
    """An empty body is a no-op and returns a current default mode."""
    response = await auth_client.patch("/api/roll/session-mode", json={})
    assert response.status_code == 200

    data = response.json()
    assert "active_bandwidth" in data
    assert "bandwidth_source" in data
    assert "active_intent" in data
    assert "intent_source" in data


@pytest.mark.asyncio
async def test_update_session_mode_invalid_value_rejected(
    auth_client: AsyncClient,
) -> None:
    """Invalid enum values produce a 422 validation error."""
    response = await auth_client.patch(
        "/api/roll/session-mode",
        json={"bandwidth": "ultra_light"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_random_intent_activates_unweighted_bypass(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A manual 'random' intent makes the next roll use unweighted control."""
    user = await get_or_create_user_async(async_db)
    for i in range(3):
        async_db.add(
            Thread(
                user_id=user.id,
                title=f"Random Thread {i}",
                format="Comic",
                issues_remaining=3,
                queue_position=i + 1,
                status="active",
                created_at=datetime.now(UTC),
            )
        )
    await async_db.commit()

    response = await auth_client.patch(
        "/api/roll/session-mode",
        json={"intent": "random"},
    )
    assert response.status_code == 200
    assert response.json()["active_intent"] == "random"

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200

    # The decision must honor the session mode: the roll is flagged as the
    # documented unweighted random bypass and the recorded intent is "random".
    rec_context = (
        await async_db.execute(
            select(RecommendationContext).order_by(RecommendationContext.id.desc()).limit(1)
        )
    ).scalar_one()
    assert rec_context.intent == "random"
    assert rec_context.random_bypass is True

    roll_event = (
        await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
        )
    ).scalar_one()
    assert roll_event.selection_method == "random"


@pytest.mark.asyncio
async def test_session_mode_event_records_manual_source(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The mode-change event records a manual source so history stays separable."""
    user = await get_or_create_user_async(async_db)
    async_db.add(
        Thread(
            user_id=user.id,
            title="Mode Event Thread",
            format="Comic",
            issues_remaining=3,
            queue_position=1,
            status="active",
            created_at=datetime.now(UTC),
        )
    )
    await async_db.commit()

    response = await auth_client.patch(
        "/api/roll/session-mode",
        json={"bandwidth": "deep"},
    )
    assert response.status_code == 200

    event = (
        await async_db.execute(
            select(Event).where(Event.type == "session_mode").order_by(Event.id.desc()).limit(1)
        )
    ).scalar_one()
    assert event.context is not None
    assert event.context.get("source") == "manual"
    assert event.context.get("changed") == ["bandwidth"]
    assert event.context.get("bandwidth") == "deep"
