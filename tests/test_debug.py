"""Tests for debug endpoints."""

import os

import pytest
from httpx import AsyncClient

from app.main import app


class _MockAdminUser:
    """Mock user with admin privileges for test purposes."""

    def __init__(self) -> None:
        self.id = 1
        self.username = "admin"
        self.is_admin = True


class _MockRegularUser:
    """Mock regular user without admin privileges for test purposes."""

    def __init__(self) -> None:
        self.id = 2
        self.username = "regular"
        self.is_admin = False


@pytest.mark.asyncio
async def test_debug_log_admin_success(client: AsyncClient) -> None:
    """Test that admin users can access debug log endpoint."""
    from app.auth import get_current_user

    def _override() -> _MockAdminUser:
        return _MockAdminUser()

    app.dependency_overrides[get_current_user] = _override

    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 200
        assert response.json() == {"status": "logged"}
    finally:
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_debug_log_non_admin_forbidden(client: AsyncClient) -> None:
    """Test that non-admin users get 403 when accessing debug log endpoint."""
    from app.auth import get_current_user

    def _override() -> _MockRegularUser:
        return _MockRegularUser()

    app.dependency_overrides[get_current_user] = _override

    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await client.post(
            "/api/debug/log",
            json={"level": "INFO", "message": "test message"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions"
    finally:
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_debug_log_anonymous_unauthorized(client: AsyncClient) -> None:
    """Test that anonymous users get 401 when accessing debug log endpoint."""
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"
    finally:
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)


@pytest.mark.asyncio
async def test_debug_log_disabled_in_production(client: AsyncClient) -> None:
    """Test that debug routes return 404 in production."""
    from app.auth import get_current_user

    def _override() -> _MockAdminUser:
        return _MockAdminUser()

    app.dependency_overrides[get_current_user] = _override

    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "production"

    try:
        response = await client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Not found"
    finally:
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
        app.dependency_overrides.pop(get_current_user, None)
