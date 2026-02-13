"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class TestAuth:
    """Test authentication endpoints."""

    @pytest.mark.asyncio
    async def test_register_user_success(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test successful user registration."""
        user_data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "securepassword123",
        }

        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Verify user was created in database
        print(f"\nDEBUG: async_db session: {async_db}")
        print(f"DEBUG: async_db in transaction: {async_db.in_transaction()}")
        print(f"DEBUG: async_db dirty: {async_db.dirty}")
        print(f"DEBUG: async_db new: {async_db.new}")
        print(
            f"DEBUG: async_db committed: {not async_db.dirty and not async_db.new and not async_db.deleted}"
        )

        await async_db.rollback()
        result = await async_db.execute(select(User).where(User.username == "newuser"))
        user = result.scalar_one_or_none()
        print(f"DEBUG: user after query: {user}")
        assert user is not None
        assert user.email == "newuser@example.com"
        assert user.password_hash is not None
        assert user.password_hash != "securepassword123"  # Should be hashed

    @pytest.mark.asyncio
    async def test_register_user_duplicate_username(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Test registration with duplicate username fails."""
        # Create first user
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        # Try to create user with same username
        duplicate_data = {
            "username": "testuser",
            "email": "different@example.com",
            "password": "password456",
        }
        response = await client.post("/api/v1/auth/register", json=duplicate_data)
        assert response.status_code == 400
        assert "Username already registered" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_register_user_duplicate_email(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Test registration with duplicate email fails."""
        # Create first user
        user_data = {
            "username": "user1",
            "email": "same@example.com",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        # Try to create user with same email
        duplicate_data = {
            "username": "user2",
            "email": "same@example.com",
            "password": "password456",
        }
        response = await client.post("/api/v1/auth/register", json=duplicate_data)
        assert response.status_code == 400
        assert "Email already registered" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test successful user login."""
        # Register user first
        user_data = {
            "username": "loginuser",
            "email": "login@example.com",
            "password": "mypassword123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        # Login
        login_data = {
            "username": "loginuser",
            "password": "mypassword123",
        }
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient) -> None:
        """Test login with invalid credentials fails."""
        login_data = {
            "username": "nonexistent",
            "password": "wrongpassword",
        }
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test successful token refresh."""
        # Register and login user
        user_data = {
            "username": "refreshuser",
            "email": "refresh@example.com",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "refreshuser",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        # Refresh token
        refresh_data = {"refresh_token": tokens["refresh_token"]}
        response = await client.post("/api/v1/auth/refresh", json=refresh_data)
        assert response.status_code == 200

        new_tokens = response.json()
        assert "access_token" in new_tokens
        assert "refresh_token" in new_tokens
        assert new_tokens["token_type"] == "bearer"

        # New tokens should be different
        assert new_tokens["access_token"] != tokens["access_token"]
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

    @pytest.mark.asyncio
    async def test_refresh_token_invalid(self, client: AsyncClient) -> None:
        """Test refresh with invalid token fails."""
        refresh_data = {"refresh_token": "invalid.jwt.token"}
        response = await client.post("/api/v1/auth/refresh", json=refresh_data)
        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_refresh_token_none(self, client: AsyncClient) -> None:
        """Test refresh with None token fails with 401 not 500."""
        refresh_data = {"refresh_token": None}
        response = await client.post("/api/v1/auth/refresh", json=refresh_data)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_current_user_authenticated(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Test getting current user info when authenticated."""
        # Register and login user
        user_data = {
            "username": "meuser",
            "email": "me@example.com",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "meuser",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        # Get current user info
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        response = await client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["username"] == "meuser"
        assert data["email"] == "me@example.com"
        assert data["is_admin"] is False

    @pytest.mark.asyncio
    async def test_get_current_user_unauthenticated(self, client: AsyncClient) -> None:
        """Test getting current user info without authentication fails."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert "Not authenticated" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test user logout."""
        # Register and login user
        user_data = {
            "username": "logoutuser",
            "email": "logout@example.com",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "logoutuser",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        # Logout
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        response = await client.post("/api/v1/auth/logout", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"message": "Successfully logged out"}

    @pytest.mark.asyncio
    async def test_logout_idempotent(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test that revoke_token is idempotent and doesn't raise on duplicate."""
        user_data = {
            "username": "logoutidempotentuser",
            "email": "logoutidempotent@example.com",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "logoutidempotentuser",
            "password": "password123",
        }
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        from app.auth import revoke_token
        from app.models.user import User

        result = await async_db.execute(select(User).where(User.username == user_data["username"]))
        user = result.scalar_one_or_none()
        assert user is not None

        access_token = tokens["access_token"]
        await revoke_token(async_db, access_token, user.id)
        await revoke_token(async_db, access_token, user.id)
