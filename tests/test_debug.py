"""Tests for debug endpoints."""

import os
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from app.auth import get_current_user
from app.main import app
from app.api.debug import router


@pytest.fixture
async def debug_client():
    """Create a test client for debug routes with dependency overrides."""
    app.include_router(router, prefix="/api/debug")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    # Clean up
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_debug_log_admin_success(debug_client: AsyncClient) -> None:
    """Test that admin users can access debug log endpoint."""

    # Create a mock admin user
    class MockAdminUser:
        def __init__(self):
            self.id = 1
            self.username = "admin"
            self.is_admin = True

    # Override the get_current_user dependency
    def mock_get_current_admin_user():
        return MockAdminUser()

    app.dependency_overrides[get_current_user] = mock_get_current_admin_user

    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await debug_client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 200
        assert response.json() == {"status": "logged"}
    finally:
        # Restore original environment
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_debug_log_non_admin_forbidden(debug_client: AsyncClient) -> None:
    """Test that non-admin users get 403 when accessing debug log endpoint."""

    # Create a mock non-admin user
    class MockUser:
        def __init__(self):
            self.id = 1
            self.username = "testuser"
            self.is_admin = False

    # Override the get_current_user dependency
    def mock_get_current_user():
        return MockUser()

    app.dependency_overrides[get_current_user] = mock_get_current_user

    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await debug_client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions"
    finally:
        # Restore original environment
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_debug_log_anonymous_unauthorized(debug_client: AsyncClient) -> None:
    """Test that anonymous users get 401 when accessing debug log endpoint."""
    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await debug_client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"
    finally:
        # Restore original environment
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)


@pytest.mark.asyncio
async def test_debug_routes_disabled_in_production() -> None:
    """Test that debug routes are disabled in production environment."""
    # Import the function directly
    from app.api.debug import check_debug_routes_enabled
    from app.config import get_app_settings
    from fastapi import HTTPException

    # Clear the lru_cache to force reloading settings
    get_app_settings.cache_clear()

    # Store original environment
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "production"

    try:
        # This should raise HTTPException with 404
        with pytest.raises(HTTPException) as exc_info:
            check_debug_routes_enabled()

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Not found"
    finally:
        # Restore original environment
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
        # Clear cache again to restore original settings
        get_app_settings.cache_clear()
