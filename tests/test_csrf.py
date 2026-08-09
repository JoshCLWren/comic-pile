"""Tests for CSRF protection on mutating API requests."""

import os
from collections.abc import Generator

import pytest
from httpx import AsyncClient

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


@pytest.fixture(autouse=True)
def _enable_csrf_for_tests() -> Generator[None]:
    """Override TEST_ENVIRONMENT so CSRF protection is active during these tests.

    The global conftest sets TEST_ENVIRONMENT=true which skips CSRF middleware.
    These tests specifically verify CSRF behavior, so we need it active.
    """
    original = os.environ.pop("TEST_ENVIRONMENT", None)
    yield
    if original is not None:
        os.environ["TEST_ENVIRONMENT"] = original


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

    response = await auth_client.get("/api/v1/auth/me")

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api/auth", "/api/v1/auth"])
async def test_csrf_bootstrap_endpoint_sets_cookie(
    client: AsyncClient, prefix: str
) -> None:
    """Both auth aliases bootstrap the same readable CSRF cookie.

    Args:
        client: Unauthenticated HTTP client for making requests.
        prefix: Auth route prefix to test ("/api/auth" or "/api/v1/auth").

    Returns:
        None: Assertions verify CSRF bootstrap behavior.
    """
    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    response = await client.get(f"{prefix}/csrf")

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert token
    assert client.cookies.get(CSRF_COOKIE_NAME) == token


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api/auth", "/api/v1/auth"])
async def test_login_register_and_refresh_are_exempt_from_csrf(
    client: AsyncClient,
    prefix: str,
) -> None:
    """Canonical and legacy first-time auth flows share the same CSRF contract.

    Args:
        client: Unauthenticated HTTP client for making requests.
        prefix: Auth route prefix to test ("/api/auth" or "/api/v1/auth").

    Returns:
        None: Assertions verify login/register/refresh are CSRF-exempt.
    """
    username = "csrf-user-v1" if "/v1/" in prefix else "csrf-user-legacy"
    email = f"{username}@example.com"

    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    register_response = await client.post(
        f"{prefix}/register",
        json={
            "username": username,
            "email": email,
            "password": "password123",
        },
    )
    assert register_response.status_code == 200
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None

    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    login_response = await client.post(
        f"{prefix}/login",
        json={"username": username, "password": "password123"},
    )
    assert login_response.status_code == 200
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None

    client.headers.pop(CSRF_HEADER_NAME, None)
    client.cookies.delete(CSRF_COOKIE_NAME)

    refresh_response = await client.post(f"{prefix}/refresh")
    assert refresh_response.status_code == 200
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api/auth", "/api/v1/auth"])
async def test_logout_remains_protected_by_csrf(
    auth_client: AsyncClient, prefix: str
) -> None:
    """Both logout aliases require CSRF because they mutate server-side auth state.

    Args:
        auth_client: Authenticated HTTP client for making requests.
        prefix: Auth route prefix to test ("/api/auth" or "/api/v1/auth").

    Returns:
        None: Assertions verify logout requires CSRF token.
    """
    auth_client.headers.pop(CSRF_HEADER_NAME, None)
    auth_client.cookies.delete(CSRF_COOKIE_NAME)

    response = await auth_client.post(f"{prefix}/logout")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}
