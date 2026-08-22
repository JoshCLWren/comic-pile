"""Phase 5 reading-mode acceptance tests: canonical mode state, manual switching,
random escape hatch, and Snooze correction guidance (#1734)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.models import Session as SessionModel


async def _current_session(async_db: AsyncSession) -> SessionModel:
    result = await async_db.execute(
        select(SessionModel)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
    )
    return result.scalars().first()


async def _latest_event(async_db: AsyncSession, event_type: str) -> Event:
    result = await async_db.execute(
        select(Event)
        .where(Event.type == event_type)
        .order_by(Event.id.desc())
        .limit(1)
    )
    return result.scalars().first()


@pytest.mark.asyncio
async def test_bootstrap_returns_default_mode(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Roll bootstrap exposes one canonical bandwidth + intent object."""
    _ = sample_data
    response = await auth_client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200

    data = response.json()
    assert "session_mode" in data
    mode = data["session_mode"]
    assert mode["bandwidth"] == "balanced"
    assert mode["intent"] == "balanced"
    assert mode["bandwidth_source"] == "inferred"
    assert mode["intent_source"] == "inferred"
    assert mode["mode_version"] == 1


@pytest.mark.asyncio
async def test_manual_switch_updates_both_dimensions(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """POST /roll/session-mode switches bandwidth and intent in one call."""
    _ = sample_data
    response = await auth_client.post(
        "/api/v1/roll/session-mode",
        json={"bandwidth": "light", "intent": "momentum"},
    )
    assert response.status_code == 200

    mode = response.json()
    assert mode["bandwidth"] == "light"
    assert mode["intent"] == "momentum"
    assert mode["bandwidth_source"] == "manual"
    assert mode["intent_source"] == "manual"
    assert mode["bandwidth_confidence"] == 1.0
    assert mode["mode_version"] == 2

    bootstrap = await auth_client.get("/api/v1/roll/bootstrap")
    assert bootstrap.status_code == 200
    refreshed = bootstrap.json()["session_mode"]
    assert refreshed["bandwidth"] == "light"
    assert refreshed["intent"] == "momentum"


@pytest.mark.asyncio
async def test_partial_change_preserves_other_dimension(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Changing intent must not reset bandwidth state."""
    _ = sample_data
    first = await auth_client.post(
        "/api/v1/roll/session-mode", json={"bandwidth": "deep"}
    )
    assert first.status_code == 200
    assert first.json()["bandwidth"] == "deep"

    second = await auth_client.post("/api/v1/roll/session-mode", json={"intent": "explore"})
    assert second.status_code == 200
    mode = second.json()
    assert mode["intent"] == "explore"
    assert mode["intent_source"] == "manual"
    # Untouched dimension keeps its value, source, and confidence.
    assert mode["bandwidth"] == "deep"
    assert mode["bandwidth_source"] == "manual"
    assert mode["bandwidth_confidence"] == 1.0


@pytest.mark.asyncio
async def test_invalid_bandwidth_rejected(auth_client: AsyncClient, sample_data: dict) -> None:
    """Enum violations return validation errors."""
    _ = sample_data
    response = await auth_client.post(
        "/api/v1/roll/session-mode", json={"bandwidth": "cozy"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_empty_update_rejected(auth_client: AsyncClient, sample_data: dict) -> None:
    """A mode update that changes nothing is invalid."""
    _ = sample_data
    response = await auth_client.post("/api/v1/roll/session-mode", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_random_intent_uses_legacy_unweighted_control_path(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Random intent rolls still select unweighted inside the bounded die pool."""
    _ = sample_data
    switch = await auth_client.post("/api/v1/roll/session-mode", json={"intent": "random"})
    assert switch.status_code == 200

    roll = await auth_client.post("/api/v1/roll/")
    assert roll.status_code == 200

    event = await _latest_event(async_db, "roll")
    assert event is not None
    assert event.context is not None
    assert event.context["intent"] == "random"
    assert event.context["control_path"] == "random_escape_hatch"


@pytest.mark.asyncio
async def test_roll_records_updated_mode_after_switch(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Subsequent rolls carry the updated canonical mode in their context."""
    _ = sample_data
    switch = await auth_client.post(
        "/api/v1/roll/session-mode",
        json={"bandwidth": "light", "intent": "familiar"},
    )
    assert switch.status_code == 200

    roll = await auth_client.post("/api/v1/roll/")
    assert roll.status_code == 200

    event = await _latest_event(async_db, "roll")
    assert event.context["bandwidth"] == "light"
    assert event.context["intent"] == "familiar"


@pytest.mark.asyncio
async def test_mode_change_event_recorded(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Manual changes record a compact mode_change event for analytics."""
    _ = sample_data
    response = await auth_client.post(
        "/api/v1/roll/session-mode", json={"intent": "momentum"}
    )
    assert response.status_code == 200

    event = await _latest_event(async_db, "mode_change")
    assert event is not None
    assert event.session_id is not None
    assert event.context["source"] == "manual"
    assert event.context["changed"]["intent"]["to"] == "momentum"


@pytest.mark.asyncio
async def test_normal_snooze_does_not_suggest_correction(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """One snooze never asks for correction; it stays interruption-free."""
    _ = sample_data
    roll = await auth_client.post("/api/v1/roll/")
    assert roll.status_code == 200

    snooze = await auth_client.post("/api/snooze/")
    assert snooze.status_code == 200

    data = snooze.json()
    guidance = data.get("correction_guidance")
    assert guidance is not None
    assert guidance["suggest_correction"] is False
    assert guidance["options"] == []


@pytest.mark.asyncio
async def test_repeated_snooze_offers_canonical_correction_options(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Consecutive snoozes surface backend correction guidance with options."""
    _ = sample_data
    for _ in range(2):
        roll = await auth_client.post("/api/v1/roll/")
        assert roll.status_code == 200
        snooze = await auth_client.post("/api/snooze/")
        assert snooze.status_code == 200

    guidance = snooze.json()["correction_guidance"]
    assert guidance["suggest_correction"] is True
    option_ids = {option["id"] for option in guidance["options"]}
    assert option_ids == {"easier", "keep_level", "familiar", "different", "pure_random"}

    pure_random = next(o for o in guidance["options"] if o["id"] == "pure_random")
    assert pure_random["intent"] == "random"

    easier = next(o for o in guidance["options"] if o["id"] == "easier")
    assert easier["bandwidth"] == "light"


@pytest.mark.asyncio
async def test_correction_choice_updates_canonical_session_state(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Applying a correction option's values updates the canonical session."""
    _ = sample_data
    for _ in range(2):
        await auth_client.post("/api/v1/roll/")
        await auth_client.post("/api/snooze/")

    apply_choice = await auth_client.post(
        "/api/v1/roll/session-mode",
        json={"intent": "random"},
    )
    assert apply_choice.status_code == 200
    assert apply_choice.json()["intent"] == "random"

    bootstrap = await auth_client.get("/api/v1/roll/bootstrap")
    mode = bootstrap.json()["session_mode"]
    assert mode["intent"] == "random"
    assert mode["intent_source"] == "manual"


@pytest.mark.asyncio
async def test_rating_resets_snooze_streak(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """A durable rating clears the consecutive-snooze mismatch streak."""
    _ = sample_data
    for _ in range(2):
        await auth_client.post("/api/v1/roll/")
        await auth_client.post("/api/snooze/")

    session = await _current_session(async_db)
    assert session.consecutive_snoozes == 2

    await auth_client.post("/api/v1/roll/")
    rate = await auth_client.post("/api/rate/", json={"rating": 4.0})
    assert rate.status_code == 200

    await async_db.refresh(session)
    assert session.consecutive_snoozes == 0
