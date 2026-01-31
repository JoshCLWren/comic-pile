"""Playwright integration test fixtures."""

import asyncio
import os
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from datetime import UTC, datetime
from socket import socket

if not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"

import pytest
import pytest_asyncio
import requests
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession as SQLAlchemyAsyncSession,
)
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.auth import create_access_token, hash_password
from app.config import clear_settings_cache
from app.database import Base, get_db, get_db_async
from app.main import app
from app.models import User


def _ensure_default_user(db: Session) -> User:
    """Ensure default user exists in database (user_id=1 for API compatibility)."""
    from app.auth import hash_password

    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if not user:
        user = User(
            id=1,
            username="test_user@example.com",
            email="test_user@example.com",
            password_hash=hash_password("testpassword"),
            created_at=datetime.now(UTC),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif (
        not user.password_hash
        or user.username != "test_user@example.com"
        or user.email != "test_user@example.com"
    ):
        # First, delete any other users with this email to avoid unique constraint violation
        db.execute(select(User).where(User.email == "test_user@example.com").where(User.id != 1))
        for other_user in db.scalars(
            select(User).where(User.email == "test_user@example.com").where(User.id != 1)
        ).all():
            db.delete(other_user)
        db.commit()

        user.username = "test_user@example.com"
        user.email = "test_user@example.com"
        user.password_hash = hash_password("testpassword")
        user.is_admin = False
        db.commit()
        db.refresh(user)
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
        return "postgresql://postgres:postgres@postgres:5432/comic_pile_test"
    raise ValueError(
        "No PostgreSQL test database configured. "
        "Set TEST_DATABASE_URL or DATABASE_URL environment variable."
    )


def get_sync_test_database_url() -> str:
    """Get sync test database URL from environment (PostgreSQL only)."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        if test_db_url.startswith("postgresql+asyncpg://"):
            return test_db_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        elif test_db_url.startswith("postgresql+aiosqlite://"):
            return test_db_url.replace("postgresql+aiosqlite://", "sqlite:///", 1)
        elif test_db_url.startswith("postgresql://"):
            return test_db_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return test_db_url
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql+asyncpg://"):
            return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql+psycopg://"):
            return database_url
    if os.getenv("CI") == "true":
        return "postgresql+psycopg://postgres:postgres@postgres:5432/comic_pile_test"
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


@pytest.fixture(scope="function")
def db() -> Generator[Session]:
    """Create test database for tests (PostgreSQL only)."""
    database_url = get_sync_test_database_url()

    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(bind=engine)

    connection = engine.connect()
    connection.execute(
        text(
            "TRUNCATE TABLE users, sessions, events, threads, snapshots, revoked_tokens "
            "RESTART IDENTITY CASCADE;"
        )
    )
    connection.commit()
    connection.close()

    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()

    try:
        _ensure_default_user(session)
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(db: Session) -> Generator[Session]:
    """Get database session for tests (alias for db)."""
    yield db


@pytest_asyncio.fixture(scope="function")
async def async_db() -> AsyncIterator[SQLAlchemyAsyncSession]:
    """Create async test database with transaction rollback (PostgreSQL)."""
    database_url = get_test_database_url()

    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    connection = await engine.connect()

    async with connection.begin():
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

    await connection.close()
    await engine.dispose()


@pytest.fixture(scope="session")
def test_server_url():
    """Launch test server for browser tests with seeded sample data."""
    from uvicorn import Config, Server

    original_db_url = os.environ.get("DATABASE_URL")
    test_db_url = get_sync_test_database_url()
    os.environ["DATABASE_URL"] = test_db_url

    test_engine = create_engine(test_db_url)
    Base.metadata.create_all(bind=test_engine)

    with test_engine.connect() as conn:
        _ensure_default_user(Session(bind=conn))

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
            conn.execute(
                text(
                    "INSERT INTO threads (title, format, issues_remaining, queue_position, status, is_test, created_at, user_id) VALUES (:title, :format, :issues_remaining, :queue_position, :status, :is_test, :created_at, :user_id)"
                ),
                {
                    "title": thread.title,
                    "format": thread.format,
                    "issues_remaining": thread.issues_remaining,
                    "queue_position": thread.queue_position,
                    "status": thread.status,
                    "is_test": thread.is_test,
                    "created_at": thread.created_at,
                    "user_id": thread.user_id,
                },
            )

        session = SessionModel(start_die=6, user_id=1, started_at=datetime.now(UTC))
        conn.execute(
            text(
                "INSERT INTO sessions (start_die, user_id, started_at) VALUES (:start_die, :user_id, :started_at)"
            ),
            {
                "start_die": session.start_die,
                "user_id": session.user_id,
                "started_at": session.started_at,
            },
        )
        conn.commit()

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

    try:
        asyncio.run(shutdown_server())
    except RuntimeError:
        pass
    thread.join(timeout=5)
    test_engine.dispose()

    if original_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original_db_url


@pytest_asyncio.fixture(scope="function")
async def api_client(db: Session) -> AsyncGenerator[AsyncClient]:
    """API client using ASGITransport for direct app calls."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_api_client(db: Session) -> AsyncGenerator[AsyncClient]:
    """API client with authentication using ASGITransport for direct app calls."""
    from app.models import User

    def override_get_db():
        try:
            yield db
        finally:
            pass

    async def override_get_db_async():
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
            AsyncSession as SQLAlchemyAsyncSession,
        )

        test_db_url = get_test_database_url()
        async_engine = create_async_engine(test_db_url, echo=False)
        async_session_maker = async_sessionmaker(
            bind=async_engine,
            expire_on_commit=False,
            class_=SQLAlchemyAsyncSession,
        )
        async with async_session_maker() as async_session:
            try:
                yield async_session
            finally:
                await async_session.close()
        await async_engine.dispose()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_async] = override_get_db_async
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        user = db.execute(
            select(User).where(User.username == "test_user@example.com")
        ).scalar_one_or_none()
        if not user:
            user = User(
                username="test_user@example.com",
                email="test_user@example.com",
                password_hash=hash_password("testpassword"),
                created_at=datetime.now(UTC),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        token = create_access_token(data={"sub": user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_api_client_async(async_db: SQLAlchemyAsyncSession) -> AsyncGenerator[AsyncClient]:
    """API client with authentication using async DB session."""
    from app.auth import create_access_token, hash_password
    from app.database import get_db_async

    async def override_get_db_async():
        yield async_db

    app.dependency_overrides[get_db_async] = override_get_db_async
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


@pytest.fixture(scope="function")
def browser_page(page):
    """Playwright page fixture with localStorage cleared after each test."""
    yield page
    try:
        page.evaluate("localStorage.clear()")
    except Exception:
        pass
