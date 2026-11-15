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

    response = await auth_client.post("/api/v1/threads/", json=THREAD_PAYLOAD)

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_mismatched_csrf_token(auth_client: AsyncClient) -> None:
    """Protected mutating endpoints reject mismatched CSRF header values."""
    auth_client.headers[CSRF_HEADER_NAME] = "different-token"

    response = await auth_client.post("/api/v1/threads/", json=THREAD_PAYLOAD)

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}


@pytest.mark.asyncio
async def test_safe_methods_do_not_require_csrf_token(auth_client: AsyncClient) -> None:
    """Safe methods keep working without CSRF tokens."""
    auth_client.headers.pop(CSRF_HEADER_NAME, None)
    auth_client.cookies.delete(CSRF_COOKIE_NAME)

    response = await auth_client.get("/api/v1/sessions/current/")

    assert response.status_code == 200

