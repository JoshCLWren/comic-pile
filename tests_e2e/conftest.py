"""Playwright integration test fixtures."""

import os
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from datetime import UTC, datetime
from socket import socket

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

from app.database import Base, get_db
from app.main import app
from app.models import User


def _ensure_default_user(db: Session) -> User:
    """Ensure default user exists in database (user_id=1 for API compatibility)."""
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if not user:
        user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
        if not user:
            user = User(username="test_user", created_at=datetime.now(UTC))
            db.add(user)
            try:
                db.commit()
            except Exception:
                db.rollback()
                user = db.execute(select(User).where(User.username == "test_user")).scalar_one()
            else:
                db.refresh(user)
    return user


def get_test_database_url() -> str:
    """Get test database URL from environment or use PostgreSQL default."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    use_sqlite = os.getenv("USE_SQLITE_FOR_TESTS", "").lower() in ("1", "true", "yes")
    if use_sqlite:
        return "sqlite+aiosqlite:///:memory:"
    raise ValueError(
        "No PostgreSQL test database configured. "
        "Set TEST_DATABASE_URL or DATABASE_URL environment variable, "
        "or set USE_SQLITE_FOR_TESTS=true for SQLite."
    )


def get_sync_test_database_url() -> str:
    """Get sync test database URL from environment or use PostgreSQL default."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    use_sqlite = os.getenv("USE_SQLITE_FOR_TESTS", "").lower() in ("1", "true", "yes")
    if use_sqlite:
        return "sqlite:///:memory:"
    raise ValueError(
        "No PostgreSQL test database configured. "
        "Set TEST_DATABASE_URL or DATABASE_URL environment variable, "
        "or set USE_SQLITE_FOR_TESTS=true for SQLite."
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
def db() -> Generator[Session]:
    """Create test database for tests (PostgreSQL or SQLite)."""
    database_url = get_sync_test_database_url()

    if database_url.startswith("sqlite"):
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        connection = engine.connect()
        transaction = connection.begin()
        session = sessionmaker(autocommit=False, autoflush=False, bind=connection)()
    else:
        engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(bind=engine)
        connection = engine.connect()
        connection.execute(
            text(
                "TRUNCATE TABLE sessions, events, tasks, threads, snapshots, settings, users RESTART IDENTITY CASCADE;"
            )
        )
        connection.commit()
        transaction = None
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()

    try:
        _ensure_default_user(session)
        yield session
    finally:
        session.close()
        if transaction is not None:
            transaction.rollback()
        connection.close()
        engine.dispose()


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
    """Launch test server for browser tests with seeded sample data."""
    from uvicorn import Config, Server

    original_db_url = os.environ.get("DATABASE_URL")
    test_db_url = get_sync_test_database_url()
    os.environ["DATABASE_URL"] = test_db_url

    test_engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False} if test_db_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(bind=test_engine)

    with test_engine.connect() as conn:
        _ensure_default_user(Session(bind=conn))

        from app.models import Event, Session as SessionModel, Thread

        threads = [
            Thread(
                title="Superman",
                format="Comic",
                issues_remaining=10,
                queue_position=1,
                status="active",
                user_id=1,
            ),
            Thread(
                title="Batman",
                format="Comic",
                issues_remaining=5,
                queue_position=2,
                status="active",
                user_id=1,
            ),
            Thread(
                title="Wonder Woman",
                format="Comic",
                issues_remaining=0,
                queue_position=3,
                status="completed",
                user_id=1,
            ),
        ]
        for thread in threads:
            conn.execute(
                text(
                    "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id) VALUES (:title, :format, :issues_remaining, :queue_position, :status, :user_id)"
                ),
                {
                    "title": thread.title,
                    "format": thread.format,
                    "issues_remaining": thread.issues_remaining,
                    "queue_position": thread.queue_position,
                    "status": thread.status,
                    "user_id": thread.user_id,
                },
            )

        session = SessionModel(start_die=6, user_id=1)
        conn.execute(
            text("INSERT INTO sessions (start_die, user_id) VALUES (:start_die, :user_id)"),
            {"start_die": session.start_die, "user_id": session.user_id},
        )
        conn.commit()

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
