"""Tests for CSRF protection on mutating API requests."""

import pytest
from httpx import AsyncClient

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


THREAD_PAYLOAD = {
    "title": "CSRF Test Thread",
    "format": "Comic",
    "issues_remaining": 3,
}


@pytest.mark.asyncio
async def test_protected_endpoint_requires_csrf_token(auth_client: AsyncClient) -> None:
    """Protected mutating endpoints reject requests without a CSRF token."""
    auth_client.headers.pop(CSRF_HEADER_NAME, None)
    auth_client.cookies.delete(CSRF_COOKIE_NAME)

    response = await auth_client.post("/api/threads/", json=THREAD_PAYLOAD)

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_mismatched_csrf_token(auth_client: AsyncClient) -> None:
    """Protected mutating endpoints reject mismatched CSRF header values."""
    auth_client.headers[CSRF_HEADER_NAME] = "different-token"

    response = await auth_client.post("/api/threads/", json=THREAD_PAYLOAD)

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}


@pytest.mark.asyncio
async def test_safe_methods_do_not_require_csrf_token(auth_client: AsyncClient) -> None:
    """Safe methods keep working without CSRF tokens."""
    auth_client.headers.pop(CSRF_HEADER_NAME, None)
    auth_client.cookies.delete(CSRF_COOKIE_NAME)

    response = await auth_client.get("/api/auth/me")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_csrf_bootstrap_endpoint_sets_cookie(client: AsyncClient) -> None:
    """The CSRF bootstrap endpoint returns a token and refreshes the cookie."""
    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    response = await client.get("/api/auth/csrf")

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert token
    assert client.cookies.get(CSRF_COOKIE_NAME) == token


@pytest.mark.asyncio
async def test_login_and_refresh_are_exempt_from_csrf(client: AsyncClient) -> None:
    """First-time auth flows stay usable without a CSRF token."""
    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    register_response = await client.post(
        "/api/auth/register",
        json={
            "username": "csrf-user",
            "email": "csrf@example.com",
            "password": "password123",
        },
    )
    assert register_response.status_code == 200
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None

    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    login_response = await client.post(
        "/api/auth/login",
        json={"username": "csrf-user", "password": "password123"},
    )
    assert login_response.status_code == 200
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None

    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    refresh_response = await client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None


@pytest.mark.asyncio
async def test_logout_remains_protected_by_csrf(auth_client: AsyncClient) -> None:
    """Logout still requires CSRF because it mutates server-side auth state."""
    auth_client.headers.pop(CSRF_HEADER_NAME, None)
    auth_client.cookies.delete(CSRF_COOKIE_NAME)

    response = await auth_client.post("/api/auth/logout")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}
