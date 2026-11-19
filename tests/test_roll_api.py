"""Tests for roll API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_retired_set_die_endpoint_not_found(auth_client: AsyncClient) -> None:
    """POST /api/v1/roll/set-die was retired (#4352). Returns 404."""
    response = await auth_client.post("/api/v1/roll/set-die?die=20")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retired_clear_manual_die_endpoint_not_found(auth_client: AsyncClient) -> None:
    """POST /api/v1/roll/clear-manual-die was retired (#4353). Returns 404."""
    response = await auth_client.post("/api/v1/roll/clear-manual-die")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retired_session_mode_endpoint_not_found(auth_client: AsyncClient) -> None:
    """PATCH /api/v1/roll/session-mode was retired (#4354). Returns 404."""
    response = await auth_client.patch(
        "/api/v1/roll/session-mode",
        json={"bandwidth": "momentum"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/roll/", "/api/roll/"])
async def test_retired_roll_mutation_endpoint_not_found(
    auth_client: AsyncClient, path: str
) -> None:
    """POST /api/v1/roll/ was retired (#4336). Both aliases return 404."""
    response = await auth_client.post(path)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/roll/", "post"),
        ("/api/v1/roll/set-die", "post"),
        ("/api/v1/roll/clear-manual-die", "post"),
        ("/api/v1/roll/session-mode", "patch"),
    ],
)
async def test_retired_roll_mutation_absent_from_openapi(
    auth_client: AsyncClient, path: str, method: str
) -> None:
    """Retired Roll mutations are no longer advertised as active capabilities."""
    response = await auth_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert method not in paths.get(path, {})
