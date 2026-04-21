"""Tests for authentication endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database import get_db
from app.main import app
from app.models.user import User
from tests.conftest import TRUNCATE_TEST_DATA_SQL


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

        response = await client.post("/api/auth/register", json=user_data)
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
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123",
        }
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        duplicate_data = {
            "username": "testuser",
            "email": "different@example.com",
            "password": "password456",
        }
        response = await client.post("/api/auth/register", json=duplicate_data)
        assert response.status_code == 400
        assert "Username already registered" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_user_duplicate_email(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Test registration with duplicate email fails."""
        user_data = {
            "username": "user1",
            "email": "same@example.com",
            "password": "password123",
        }
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        duplicate_data = {
            "username": "user2",
            "email": "same@example.com",
            "password": "password456",
        }
        response = await client.post("/api/auth/register", json=duplicate_data)
        assert response.status_code == 400
        assert "Email already registered" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test successful user login."""
        user_data = {
            "username": "loginuser",
            "email": "login@example.com",
            "password": "mypassword123",
        }
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "loginuser",
            "password": "mypassword123",
        }
        response = await client.post("/api/auth/login", json=login_data)
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
        response = await client.post("/api/auth/login", json=login_data)
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test successful token refresh."""
        user_data = {
            "username": "refreshuser",
            "email": "refresh@example.com",
            "password": "password123",
        }
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "refreshuser",
            "password": "password123",
        }
        response = await client.post("/api/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        refresh_data = {"refresh_token": tokens["refresh_token"]}
        response = await client.post("/api/auth/refresh", json=refresh_data)
        assert response.status_code == 200

        new_tokens = response.json()
        assert "access_token" in new_tokens
        assert "refresh_token" in new_tokens
        assert new_tokens["token_type"] == "bearer"

        assert new_tokens["access_token"] != tokens["access_token"]
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

    @pytest.mark.asyncio
    async def test_login_sets_refresh_cookie(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Login sets refresh token in HttpOnly cookie."""
        user_data = {
            "username": "cookieuser",
            "email": "cookie@example.com",
            "password": "password123",
        }
        register_response = await client.post("/api/auth/register", json=user_data)
        assert register_response.status_code == 200

        login_data = {"username": "cookieuser", "password": "password123"}
        login_response = await client.post("/api/auth/login", json=login_data)
        assert login_response.status_code == 200

        set_cookie = login_response.headers.get("set-cookie", "")
        assert "refresh_token=" in set_cookie
        assert "HttpOnly" in set_cookie

    @pytest.mark.asyncio
    async def test_refresh_token_success_with_cookie(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Refresh endpoint accepts refresh token from HttpOnly cookie."""
        user_data = {
            "username": "cookie_refresh_user",
            "email": "cookie_refresh@example.com",
            "password": "password123",
        }
        register_response = await client.post("/api/auth/register", json=user_data)
        assert register_response.status_code == 200

        login_data = {"username": "cookie_refresh_user", "password": "password123"}
        login_response = await client.post("/api/auth/login", json=login_data)
        assert login_response.status_code == 200
        assert client.cookies.get("refresh_token") is not None

        refresh_response = await client.post("/api/auth/refresh")
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert "access_token" in refreshed
        assert "refresh_token" in refreshed

    @pytest.mark.asyncio
    async def test_refresh_token_invalid(self, client: AsyncClient) -> None:
        """Test refresh with invalid token fails."""
        refresh_data = {"refresh_token": "invalid.jwt.token"}
        response = await client.post("/api/auth/refresh", json=refresh_data)
        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_token_none(self, client: AsyncClient) -> None:
        """Test refresh with None token fails with 401 not 500."""
        refresh_data = {"refresh_token": None}
        response = await client.post("/api/auth/refresh", json=refresh_data)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_current_user_authenticated(
        self, client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Test getting current user info when authenticated."""
        user_data = {
            "username": "meuser",
            "email": "me@example.com",
            "password": "password123",
        }
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "meuser",
            "password": "password123",
        }
        response = await client.post("/api/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        response = await client.get("/api/auth/me", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["username"] == "meuser"
        assert data["email"] == "me@example.com"
        assert data["is_admin"] is False

    @pytest.mark.asyncio
    async def test_get_current_user_unauthenticated(self, client: AsyncClient) -> None:
        """Test getting current user info without authentication fails."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient, async_db: AsyncSession) -> None:
        """Test user logout."""
        user_data = {
            "username": "logoutuser",
            "email": "logout@example.com",
            "password": "password123",
        }
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "logoutuser",
            "password": "password123",
        }
        response = await client.post("/api/auth/login", json=login_data)
        assert response.status_code == 200
        tokens = response.json()

        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        response = await client.post("/api/auth/logout", headers=headers)
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
        response = await client.post("/api/auth/register", json=user_data)
        assert response.status_code == 200

        login_data = {
            "username": "logoutidempotentuser",
            "password": "password123",
        }
        response = await client.post("/api/auth/login", json=login_data)
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


@asynccontextmanager
async def _create_committed_client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Build an AsyncClient backed by fresh committed DB sessions per request."""
    session_maker = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as setup_session:
        await setup_session.execute(TRUNCATE_TEST_DATA_SQL)
        await setup_session.commit()

    async def override():
        async with session_maker() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with session_maker() as cleanup_session:
            await cleanup_session.execute(TRUNCATE_TEST_DATA_SQL)
            await cleanup_session.commit()


class TestAccountLockout:
    """Test account lockout after failed login attempts."""

    @pytest.mark.asyncio
    async def test_username_lockout_after_five_failures(self, db_engine: AsyncEngine) -> None:
        """Five wrong-password attempts lock the username; 6th fails even with correct pw."""
        async with _create_committed_client(db_engine) as client:
            user_data = {
                "username": "lockoutuser",
                "email": "lockout@example.com",
                "password": "password123",
            }
            reg = await client.post("/api/auth/register", json=user_data)
            assert reg.status_code == 200

            wrong = {"username": "lockoutuser", "password": "wrongpw"}
            for i in range(5):
                resp = await client.post("/api/auth/login", json=wrong)
                assert resp.status_code == 401, f"Attempt {i + 1} should be 401"

            correct = {"username": "lockoutuser", "password": "password123"}
            locked = await client.post("/api/auth/login", json=correct)
            assert locked.status_code == 401
            assert "Incorrect username or password" in locked.json()["detail"]

    @pytest.mark.asyncio
    async def test_success_clears_counter(self, db_engine: AsyncEngine) -> None:
        """A successful login resets the failure counter for that username."""
        async with _create_committed_client(db_engine) as client:
            user_data = {
                "username": "resetworks",
                "email": "reset@example.com",
                "password": "password123",
            }
            reg = await client.post("/api/auth/register", json=user_data)
            assert reg.status_code == 200

            wrong = {"username": "resetworks", "password": "wrong"}
            for _ in range(4):
                resp = await client.post("/api/auth/login", json=wrong)
                assert resp.status_code == 401

            correct = {"username": "resetworks", "password": "password123"}
            ok = await client.post("/api/auth/login", json=correct)
            assert ok.status_code == 200

            for _ in range(4):
                resp = await client.post("/api/auth/login", json=wrong)
                assert resp.status_code == 401

            ok2 = await client.post("/api/auth/login", json=correct)
            assert ok2.status_code == 200

    @pytest.mark.asyncio
    async def test_lockout_is_per_username(self, db_engine: AsyncEngine) -> None:
        """Locking one username does not affect a different username."""
        async with _create_committed_client(db_engine) as client:
            user_a = {"username": "user_a", "email": "a@example.com", "password": "pw123"}
            user_b = {"username": "user_b", "email": "b@example.com", "password": "pw456"}
            reg_a = await client.post("/api/auth/register", json=user_a)
            assert reg_a.status_code == 200, f"user_a register: {reg_a.text}"
            reg_b = await client.post("/api/auth/register", json=user_b)
            assert reg_b.status_code == 200, f"user_b register: {reg_b.text}"

            wrong_a = {"username": "user_a", "password": "wrong"}
            for _ in range(5):
                resp = await client.post("/api/auth/login", json=wrong_a)
                assert resp.status_code == 401

            locked = await client.post("/api/auth/login", json=wrong_a)
            assert locked.status_code == 401

            correct_b = {"username": "user_b", "password": "pw456"}
            ok = await client.post("/api/auth/login", json=correct_b)
            assert ok.status_code == 200

    @pytest.mark.asyncio
    async def test_lockout_returns_generic_error(self, db_engine: AsyncEngine) -> None:
        """Lockout response does not reveal whether the username exists."""
        async with _create_committed_client(db_engine) as client:
            user_data = {
                "username": "genericerr",
                "email": "generic@example.com",
                "password": "password123",
            }
            await client.post("/api/auth/register", json=user_data)

            wrong = {"username": "genericerr", "password": "wrong"}
            for _ in range(5):
                await client.post("/api/auth/login", json=wrong)

            locked = await client.post("/api/auth/login", json=wrong)
            assert locked.status_code == 401
            assert locked.json()["detail"] == "Incorrect username or password"

    @pytest.mark.asyncio
    async def test_nonexistent_user_records_failure(self, db_engine: AsyncEngine) -> None:
        """Attempts against a non-existent username still count toward IP lockout."""
        async with _create_committed_client(db_engine) as client:
            for _ in range(9):
                resp = await client.post(
                    "/api/auth/login",
                    json={"username": f"noexist_{_}", "password": "wrong"},
                )
                assert resp.status_code == 401

            user_data = {
                "username": "lateuser",
                "email": "late@example.com",
                "password": "password123",
            }
            await client.post("/api/auth/register", json=user_data)

            resp = await client.post(
                "/api/auth/login",
                json={"username": "lateuser", "password": "wrong"},
            )
            assert resp.status_code == 401

            correct = {"username": "lateuser", "password": "password123"}
            locked = await client.post("/api/auth/login", json=correct)
            assert locked.status_code == 401
