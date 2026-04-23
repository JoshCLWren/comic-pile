"""Tests for debug endpoints."""

import os
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password
from app.models.user import User


@pytest.mark.asyncio
async def test_debug_log_admin_success(auth_client: AsyncClient) -> None:
    """Test that admin users can access debug log endpoint."""
    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await auth_client.post(
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


@pytest.mark.asyncio
async def test_debug_log_non_admin_forbidden(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test that non-admin users get 403 when accessing debug log endpoint."""
    # Create a non-admin user
    result = await async_db.execute(select(User).where(User.username == "testuser"))
    user = result.scalar_one_or_none()
    if not user:
        # Create test user if not exists
        test_user = User(
            username="testuser",
            email="test@example.com",
            password_hash=hash_password("password123"),
            is_admin=False,
        )
        async_db.add(test_user)
        await async_db.commit()
        await async_db.refresh(test_user)

    # Login as non-admin user
    access_token = create_access_token(data={"sub": "testuser", "jti": "test-non-admin"})

    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await auth_client.post(
            "/api/debug/log",
            json={"level": "INFO", "message": "test message"},
            headers={"Authorization": f"Bearer {access_token}"},
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
async def test_debug_log_anonymous_unauthorized(client: AsyncClient) -> None:
    """Test that anonymous users get 401 when accessing debug log endpoint."""
    # Ensure we're in non-production environment for debug routes to be mounted
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "development"

    try:
        response = await client.post(
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
async def test_debug_log_disabled_in_production(auth_client: AsyncClient) -> None:
    """Test that debug routes return 404 when ENABLE_DEBUG_ROUTES is disabled (production)."""
    # Set environment to production
    original_env = os.environ.get("ENVIRONMENT", "")
    os.environ["ENVIRONMENT"] = "production"

    try:
        response = await auth_client.post(
            "/api/debug/log", json={"level": "INFO", "message": "test message"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Not found"
    finally:
        # Restore original environment
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        else:
            os.environ.pop("ENVIRONMENT", None)
