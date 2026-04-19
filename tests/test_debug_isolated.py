"""Isolated tests for debug endpoints that don't depend on complex fixtures."""

import os

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from app.api.debug import router
from app.auth import get_current_user
from app.main import app


@pytest.fixture
async def isolated_client():
    """Create an isolated test client for debug routes."""

    # Create a mock non-admin user
    class MockUser:
        def __init__(self):
            self.id = 1
            self.username = "testuser"
            self.is_admin = False

    # Override the get_current_user dependency
    def mock_get_current_user():
        return MockUser()

    app.include_router(router, prefix="/api/debug")
    app.dependency_overrides[get_current_user] = mock_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    # Clean up
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_debug_log_non_admin_forbidden(isolated_client: AsyncClient):
    """Test that non-admin users get 403 when accessing debug log endpoint."""
    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await isolated_client.post(
            "/api/debug/log",
            json={"level": "INFO", "message": "test message"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions"
    finally:
        # Restore original environment
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)


@pytest.mark.asyncio
async def test_debug_log_admin_success(isolated_client: AsyncClient):
    """Test that admin users can access debug log endpoint."""

    # Create a mock admin user
    class MockAdminUser:
        def __init__(self):
            self.id = 1
            self.username = "admin"
            self.is_admin = True

    # Override the get_current_user dependency for admin
    def mock_get_current_admin_user():
        return MockAdminUser()

    app.dependency_overrides[get_current_user] = mock_get_current_admin_user

    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await isolated_client.post(
            "/api/debug/log",
            json={"level": "INFO", "message": "test message"},
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
