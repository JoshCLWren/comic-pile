"""Playwright integration test fixtures."""

import os
import tempfile
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from socket import socket

import pytest
import pytest_asyncio
import requests
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession as SQLAlchemyAsyncSession,
)
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app


def get_test_database_url() -> str:
    """Get test database URL from environment or use SQLite default."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    return "sqlite:///:memory:"


def get_sync_test_database_url() -> str:
    """Get sync test database URL from environment or use SQLite default."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    return "sqlite:///:memory:"


test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db_file.close()
TEST_DATABASE_URL = get_sync_test_database_url()

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if TEST_DATABASE_URL.startswith("sqlite") else {},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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
def db() -> Generator[Session]:
    """Create test database for tests (PostgreSQL or SQLite)."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session(db: Session) -> Generator[Session]:
    """Get database session for tests (alias for db)."""
    yield db


@pytest_asyncio.fixture(scope="function")
async def async_db() -> AsyncIterator[SQLAlchemyAsyncSession]:
    """Create async test database with transaction rollback (PostgreSQL or SQLite)."""
    database_url = get_test_database_url()

    if database_url.startswith("sqlite"):
        engine = create_async_engine(database_url, connect_args={"check_same_thread": False})
    else:
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
    """Launch test server for browser tests."""
    from uvicorn import Config, Server

    original_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = get_sync_test_database_url()

    Base.metadata.create_all(bind=test_engine)

    config = Config(app=app, host="127.0.0.1", port=TEST_SERVER_PORT, log_level="error")
    server = Server(config)

    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    for _ in range(50):
        try:
            response = requests.get(f"http://127.0.0.1:{TEST_SERVER_PORT}/health", timeout=0.5)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(0.2)

    yield f"http://127.0.0.1:{TEST_SERVER_PORT}"

    server.should_exit = True
    thread.join(timeout=5)

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
