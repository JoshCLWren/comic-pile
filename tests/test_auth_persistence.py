"""Regression coverage for browser authentication persistence."""

import pytest
from httpx import AsyncClient

from app.auth import REFRESH_TOKEN_EXPIRE_DAYS, refresh_cookie_max_age_seconds


def test_refresh_cookie_max_age_matches_refresh_jwt_lifetime() -> None:
    """Refresh cookie lifetime must follow REFRESH_TOKEN_EXPIRE_DAYS, not a hard-coded 30d."""
    assert refresh_cookie_max_age_seconds() == REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    assert refresh_cookie_max_age_seconds() != 60 * 60 * 24 * 30


@pytest.mark.asyncio
async def test_v1_auth_refresh_cookie_survives_access_token_expiry(client: AsyncClient) -> None:
    """The browser refresh cookie must be sent to the versioned auth endpoints."""
    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "persistent-session-user",
            "email": "persistent-session@example.com",
            "password": "password123",
        },
    )
    assert register_response.status_code == 200

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "persistent-session-user", "password": "password123"},
    )
    assert login_response.status_code == 200
    set_cookie = login_response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "Path=/api" in set_cookie
    assert "HttpOnly" in set_cookie
    expected_max_age = refresh_cookie_max_age_seconds()
    assert expected_max_age == REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    assert f"Max-Age={expected_max_age}" in set_cookie
    assert "Max-Age=2592000" not in set_cookie

    refresh_response = await client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 200
    assert refresh_response.json()["access_token"]


@pytest.mark.asyncio
async def test_v1_logout_clears_persistent_refresh_cookie(client: AsyncClient) -> None:
    """Logging out must clear the same cookie scope used for persistent sessions."""
    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "persistent-logout-user",
            "email": "persistent-logout@example.com",
            "password": "password123",
        },
    )
    assert register_response.status_code == 200
    access_token = register_response.json()["access_token"]

    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_response.status_code == 200
    set_cookie = logout_response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "Path=/api" in set_cookie
    assert "Max-Age=0" in set_cookie
