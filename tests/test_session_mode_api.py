"""Tests for the session reading-mode API endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_update_mode_sets_bandwidth_and_intent(auth_client: AsyncClient) -> None:
    """Posting a full mode payload persists both dimensions as manual."""
    response = await auth_client.post(
        "/api/sessions/current/mode/",
        json={"bandwidth": "deep", "intent": "explore"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["bandwidth"] == "deep"
    assert data["intent"] == "explore"
    assert data["source"] == "manual"


@pytest.mark.asyncio
async def test_update_mode_changes_one_dimension_without_resetting_other(
    auth_client: AsyncClient,
) -> None:
    """A partial update preserves the untouched dimension."""
    first = await auth_client.post(
        "/api/sessions/current/mode/",
        json={"bandwidth": "light", "intent": "momentum"},
    )
    assert first.status_code == 200

    second = await auth_client.post("/api/sessions/current/mode/", json={"intent": "random"})
    assert second.status_code == 200

    data = second.json()
    assert data["bandwidth"] == "light"
    assert data["intent"] == "random"


@pytest.mark.asyncio
async def test_update_mode_rejects_invalid_bandwidth(auth_client: AsyncClient) -> None:
    """Unknown bandwidth values are rejected with 422."""
    response = await auth_client.post(
        "/api/sessions/current/mode/",
        json={"bandwidth": "maximum"},
    )
    assert response.status_code == 422
    assert "bandwidth" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_mode_rejects_invalid_intent(auth_client: AsyncClient) -> None:
    """Unknown intent values are rejected with 422."""
    response = await auth_client.post(
        "/api/sessions/current/mode/",
        json={"intent": "chaos"},
    )
    assert response.status_code == 422
    assert "intent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_current_session_exposes_mode_fields(auth_client: AsyncClient) -> None:
    """GET /sessions/current/ reflects the stored reading-mode state."""
    updated = await auth_client.post(
        "/api/sessions/current/mode/",
        json={"bandwidth": "balanced", "intent": "familiar"},
    )
    assert updated.status_code == 200

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["bandwidth"] == "balanced"
    assert data["intent"] == "familiar"
    assert data["mode_source"] == "manual"
