"""Playwright integration test fixtures."""

import asyncio
import os
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from socket import socket

import pytest
import pytest_asyncio
import requests
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession as SQLAlchemyAsyncSession,
)
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import clear_settings_cache
from app.database import Base, get_db
from app.main import app
from app.models import User


load_dotenv()

if not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_database_tables():
    """Create database tables using asyncpg (ASYNC ONLY - no sync psycopg2).

    This session-scoped async fixture runs once per test session,
    creating tables if they don't exist. Uses asyncpg ONLY.
    """
    database_url = get_test_database_url()
    engine = create_async_engine(database_url, echo=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
    yield


async def _ensure_default_user(async_db: SQLAlchemyAsyncSession) -> User:
    """Ensure default user exists in database (user_id=1 for API compatibility)."""
    from app.auth import hash_password

    result = await async_db.execute(select(User).where(User.id == 1))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            id=1,
            username="test_user@example.com",
            email="test_user@example.com",
            password_hash=hash_password("testpassword"),
            created_at=datetime.now(UTC),
        )
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)
    elif (
        not user.password_hash
        or user.username != "test_user@example.com"
        or user.email != "test_user@example.com"
    ):
        # First, delete any other users with this email to avoid unique constraint violation
        await async_db.execute(
            select(User).where(User.email == "test_user@example.com").where(User.id != 1)
        )
        result = await async_db.execute(
            select(User).where(User.email == "test_user@example.com").where(User.id != 1)
        )
        for other_user in result.scalars().all():
            await async_db.delete(other_user)
        await async_db.commit()

        user.username = "test_user@example.com"
        user.email = "test_user@example.com"
        user.password_hash = hash_password("testpassword")
        user.is_admin = False
        await async_db.commit()
        await async_db.refresh(user)
    return user


def get_test_database_url() -> str:
    """Get test database URL from environment (PostgreSQL only)."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    if os.getenv("CI") == "true":
        return "postgresql+asyncpg://postgres:postgres@postgres:5432/comic_pile_test"
    raise ValueError(
        "No PostgreSQL test database configured. "
        "Set TEST_DATABASE_URL or DATABASE_URL environment variable."
    )


def _find_free_port():
    """Find a free port to run the test server on."""
    with socket() as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


TEST_SERVER_PORT = _find_free_port()


@pytest.fixture(scope="function", autouse=True)
def set_skip_worktree_check():
    """Skip worktree validation in tests."""
    original_value = os.getenv("SKIP_WORKTREE_CHECK")
    os.environ["SKIP_WORKTREE_CHECK"] = "true"
    yield
    if original_value is None:
        os.environ.pop("SKIP_WORKTREE_CHECK", None)
    else:
        os.environ["SKIP_WORKTREE_CHECK"] = original_value


@pytest.fixture(scope="function")
def enable_internal_ops():
    """Enable internal ops routes for tests that access admin endpoints."""
    old_value = os.environ.get("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"
    clear_settings_cache()
    yield
    if old_value is None:
        os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
    else:
        os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = old_value
    clear_settings_cache()


@pytest_asyncio.fixture(scope="function")
async def async_db() -> AsyncIterator[SQLAlchemyAsyncSession]:
    """Create isolated async test database with transaction rollback.

    Uses asyncpg ONLY (async PostgreSQL). Tables created by module-scoped
    _create_database_tables fixture.
    """
    database_url = get_test_database_url()

    engine = create_async_engine(
        database_url,
        echo=False,
        poolclass=NullPool,
    )

    connection = await engine.connect()
    transaction = await connection.begin()

    async_session_maker = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        class_=SQLAlchemyAsyncSession,
    )

    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()


@pytest.fixture(scope="function")
def db(async_db):
    """Synchronous wrapper for async_db for use in non-async tests."""

    class SyncDB:
        """Synchronous wrapper for async database operations."""

        def __init__(self, async_session):
            self._async_session = async_session

        def add(self, obj):
            """Add object to session."""
            asyncio.run(self._async_session.add(obj))

        def commit(self):
            """Commit session."""
            asyncio.run(self._async_session.commit())

        def refresh(self, obj):
            """Refresh object."""
            asyncio.run(self._async_session.refresh(obj))

        def execute(self, stmt):
            """Execute a statement."""
            return asyncio.run(self._async_session.execute(stmt))

        def close(self):
            """Close session (no-op for sync wrapper)."""
            pass

    return SyncDB(async_db)


@pytest.fixture(scope="session")
def test_server_url():
    """Launch test server for browser tests with seeded sample data."""
    import asyncio
    from uvicorn import Config, Server

    original_db_url = os.environ.get("DATABASE_URL")
    test_db_url = get_test_database_url()
    os.environ["DATABASE_URL"] = test_db_url

    async def setup_test_data():
        """Setup test database with sample data using asyncpg.

        Creates tables using asyncpg (async-only, NO sync psycopg2),
        then seeds sample data for E2E tests.
        """
        test_engine = create_async_engine(test_db_url)

        # Create tables using asyncpg (async-only)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session_maker = async_sessionmaker(
            bind=test_engine,
            expire_on_commit=False,
            class_=SQLAlchemyAsyncSession,
        )

        async with test_engine.begin():
            async with async_session_maker() as session:
                await _ensure_default_user(session)

                from app.models import Session as SessionModel, Thread

                threads = [
                    Thread(
                        title="Superman",
                        format="Comic",
                        issues_remaining=10,
                        queue_position=1,
                        status="active",
                        is_test=True,
                        created_at=datetime.now(UTC),
                        user_id=1,
                    ),
                    Thread(
                        title="Batman",
                        format="Comic",
                        issues_remaining=5,
                        queue_position=2,
                        status="active",
                        is_test=True,
                        created_at=datetime.now(UTC),
                        user_id=1,
                    ),
                    Thread(
                        title="Wonder Woman",
                        format="Comic",
                        issues_remaining=0,
                        queue_position=3,
                        status="completed",
                        is_test=True,
                        created_at=datetime.now(UTC),
                        user_id=1,
                    ),
                ]
                for thread in threads:
                    session.add(thread)
                await session.flush()

                session_obj = SessionModel(start_die=6, user_id=1, started_at=datetime.now(UTC))
                session.add(session_obj)
                await session.commit()

        await test_engine.dispose()

    asyncio.run(setup_test_data())

    config = Config(app=app, host="127.0.0.1", port=TEST_SERVER_PORT, log_level="warning")
    server = Server(config)

    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    server_ready = False
    for _ in range(100):
        try:
            response = requests.get(f"http://127.0.0.1:{TEST_SERVER_PORT}/health", timeout=1)
            if response.status_code == 200:
                server_ready = True
                break
        except requests.exceptions.RequestException:
            time.sleep(0.1)

    if not server_ready:
        raise RuntimeError(
            f"Test server failed to start on port {TEST_SERVER_PORT}. "
            f"Check if database is running and accessible."
        )

    yield f"http://127.0.0.1:{TEST_SERVER_PORT}"

    async def shutdown_server():
        server.should_exit = True
        await server.shutdown()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(shutdown_server())
    except RuntimeError:
        pass
    finally:
        loop.close()
    thread.join(timeout=5)

    if original_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original_db_url


@pytest_asyncio.fixture(scope="function")
async def auth_api_client(async_db: SQLAlchemyAsyncSession) -> AsyncGenerator[AsyncClient]:
    """API client using ASGITransport for direct app calls."""

    async def override_get_db():
        try:
            yield async_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_api_client_async(async_db: SQLAlchemyAsyncSession) -> AsyncGenerator[AsyncClient]:
    """API client with authentication using async DB session."""
    from app.auth import create_access_token, hash_password
    from app.database import get_db

    async def override_get_db():
        yield async_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        result = await async_db.execute(
            select(User).where(User.username == "test_user@example.com")
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username="test_user@example.com",
                email="test_user@example.com",
                password_hash=hash_password("testpassword"),
                created_at=datetime.now(UTC),
            )
            async_db.add(user)
            await async_db.commit()
            await async_db.refresh(user)

        token = create_access_token(data={"sub": user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def browser_page(page):
    """Async Playwright page fixture with localStorage cleared after each test."""
    yield page
    try:
        await page.evaluate("localStorage.clear()")
    except Exception:
        pass
