"""Shared pytest fixtures.

This module contains pytest fixtures that are shared across multiple test files.
It provides database setup, test data creation, and authentication utilities.
"""

import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import UniqueConstraint, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession as SQLAlchemyAsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.pool import NullPool

from app.database import Base, get_db
from app.main import app
from app.models import Event, Issue, Thread, User
from app.models import Session as SessionModel

load_dotenv(".env.test")

# Set TEST_ENVIRONMENT before importing app modules
# This must be done before app.main is imported to disable rate limiting
if not os.getenv("TEST_ENVIRONMENT"):
    os.environ["TEST_ENVIRONMENT"] = "true"

if not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"


TRUNCATE_TEST_DATA_SQL = text(
    "TRUNCATE TABLE sessions, events, threads, issues, snapshots, dependencies, "
    "revoked_tokens, users RESTART IDENTITY CASCADE;"
)
_SHARED_TEST_ENGINE: AsyncEngine | None = None


@pytest.fixture(autouse=True, scope="session")
def set_test_environment() -> Iterator[None]:
    """Set TEST_ENVIRONMENT for all tests to disable rate limiting."""
    original_value = os.environ.get("TEST_ENVIRONMENT")
    os.environ["TEST_ENVIRONMENT"] = "true"
    yield
    if original_value is None:
        os.environ.pop("TEST_ENVIRONMENT", None)
    else:
        os.environ["TEST_ENVIRONMENT"] = original_value


@pytest.fixture(autouse=True)
def enable_rate_limiting_for_tests(request: pytest.FixtureRequest) -> Iterator[None]:
    """Enable rate limiting only for the dedicated rate-limit test module."""
    original_value = os.environ.get("ENABLE_RATE_LIMITING_IN_TESTS")
    if request.node.nodeid.startswith("tests/test_rate_limit"):
        os.environ["ENABLE_RATE_LIMITING_IN_TESTS"] = "true"
    else:
        os.environ.pop("ENABLE_RATE_LIMITING_IN_TESTS", None)
    yield
    if original_value is None:
        os.environ.pop("ENABLE_RATE_LIMITING_IN_TESTS", None)
    else:
        os.environ["ENABLE_RATE_LIMITING_IN_TESTS"] = original_value


def _looks_like_test_database(database_url: str) -> bool:
    url = make_url(database_url)
    db_name = (url.database or "").lower()

    allow_list = {"test", "ci", "dev", "comic_pile_test"}
    if db_name in allow_list:
        return True

    for prefix in allow_list:
        if db_name.startswith(f"{prefix}_") or db_name.startswith(f"{prefix}-"):
            return True

    # Also allow any database name containing "test" (for SQLite test.db, etc.)
    if "test" in db_name:
        return True

    return db_name.endswith("_test") or db_name.endswith("-test")


def _has_schema_drift(conn: Connection) -> bool:
    inspector = inspect(conn)

    required_table_names = {
        "users",
        "sessions",
        "threads",
        "issues",
        "dependencies",
        "events",
        "snapshots",
        "revoked_tokens",
    }

    for table_name in required_table_names:
        if not inspector.has_table(table_name):
            return True

        table = Base.metadata.tables[table_name]

        existing_columns = {str(col["name"]) for col in inspector.get_columns(table_name)}
        expected_columns = {col.name for col in table.columns}
        if not expected_columns.issubset(existing_columns):
            return True

        existing_indexes = {str(index["name"]) for index in inspector.get_indexes(table_name)}
        expected_indexes = {index.name for index in table.indexes if index.name is not None}
        if not expected_indexes.issubset(existing_indexes):
            return True

        existing_unique_constraints = {
            str(constraint["name"])
            for constraint in inspector.get_unique_constraints(table_name)
            if constraint.get("name") is not None
        }
        expected_unique_constraints = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint) and constraint.name is not None
        }
        if not expected_unique_constraints.issubset(existing_unique_constraints):
            return True

    return False


def _default_test_username() -> str:
    return f"test_user_{os.getpid()}"


async def _sync_id_sequence(db: SQLAlchemyAsyncSession, table_name: str) -> None:
    """Advance a table's id sequence to the current max id after explicit inserts."""
    await db.execute(
        text(
            "SELECT setval("
            f"pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
        )
    )


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Create and prepare the shared async engine for backend tests."""
    global _SHARED_TEST_ENGINE

    database_url = get_test_database_url()
    engine = create_async_engine(database_url, echo=False, poolclass=NullPool)

    async with engine.begin() as conn:

        def _check_and_drop(sync_conn: Connection) -> None:
            if _has_schema_drift(sync_conn):
                if not _looks_like_test_database(database_url):
                    raise RuntimeError(
                        "Refusing to reset schema on non-test database. "
                        f"Database '{make_url(database_url).database}' must include 'test'."
                    )
                sync_conn.exec_driver_sql("DROP SCHEMA public CASCADE")
                sync_conn.exec_driver_sql("CREATE SCHEMA public")
                Base.metadata.create_all(bind=sync_conn)

        await conn.run_sync(_check_and_drop)
        await conn.execute(TRUNCATE_TEST_DATA_SQL)

    _SHARED_TEST_ENGINE = engine
    try:
        yield engine
    finally:
        _SHARED_TEST_ENGINE = None
        await engine.dispose()


async def _ensure_default_user_async(db: SQLAlchemyAsyncSession) -> User:
    """Ensure default user exists in database (user_id=1 for API compatibility)."""
    username = _default_test_username()
    result = await db.execute(select(User).where(User.id == 1))
    user = result.scalar_one_or_none()
    if not user:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            user = User(id=1, username=username, created_at=datetime.now(UTC))
            db.add(user)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                result = await db.execute(select(User).where(User.username == username))
                user = result.scalar_one()
        else:
            await db.refresh(user)
    else:
        await db.refresh(user)
    await _sync_id_sequence(db, "users")
    return user


async def get_or_create_user_async(db: SQLAlchemyAsyncSession, username: str | None = None) -> User:
    """Get or create user with given username (async)."""
    if username is None:
        username = _default_test_username()
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        user_kwargs: dict[str, object] = {
            "username": username,
            "created_at": datetime.now(UTC),
        }
        if username == _default_test_username():
            user_kwargs["id"] = 1
        user = User(**user_kwargs)
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one()
        else:
            await db.refresh(user)
    if username == _default_test_username():
        await _sync_id_sequence(db, "users")
    return user


@pytest_asyncio.fixture(scope="function")
async def default_user(async_db: SQLAlchemyAsyncSession) -> User:
    """Get or create default test user."""
    return await _ensure_default_user_async(async_db)


@pytest.fixture(scope="session")
def test_username() -> str:
    """Get process-specific test username for direct database queries."""
    return _default_test_username()


def get_test_database_url() -> str:
    """Get test database URL from environment (PostgreSQL only)."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url

    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url

    # Fallback to an in‑memory SQLite database for local testing when no PostgreSQL URL is provided.
    return "sqlite+aiosqlite:///test.db"


@pytest.fixture(scope="function", autouse=True)
def set_skip_worktree_check() -> Iterator[None]:
    """Skip worktree validation in tests."""
    original_value = os.getenv("SKIP_WORKTREE_CHECK")
    os.environ["SKIP_WORKTREE_CHECK"] = "true"
    yield
    if original_value is None:
        os.environ.pop("SKIP_WORKTREE_CHECK", None)
    else:
        os.environ["SKIP_WORKTREE_CHECK"] = original_value


@pytest_asyncio.fixture(scope="function")
async def async_db(db_engine: AsyncEngine) -> AsyncIterator[SQLAlchemyAsyncSession]:
    """Create an async test session isolated by per-test transaction rollback."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = SQLAlchemyAsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


@pytest_asyncio.fixture(scope="function")
async def async_db_committed(db_engine: AsyncEngine) -> AsyncIterator[SQLAlchemyAsyncSession]:
    """Create an async test session that uses real commits across connections."""
    session_maker = async_sessionmaker(
        bind=db_engine,
        expire_on_commit=False,
        class_=SQLAlchemyAsyncSession,
    )

    async with session_maker() as session:
        await session.execute(TRUNCATE_TEST_DATA_SQL)
        await session.commit()
        yield session

    async with session_maker() as cleanup_session:
        await cleanup_session.execute(TRUNCATE_TEST_DATA_SQL)
        await cleanup_session.commit()


@pytest.fixture(scope="function")
def clear_config_cache() -> Iterator[None]:
    """Clear cached settings before and after each test to prevent test pollution."""
    from app.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()


async def _create_async_db_override(
    async_session: SQLAlchemyAsyncSession | None = None,
) -> Callable[[], AsyncIterator[SQLAlchemyAsyncSession]]:
    """Create dependency override for get_db using provided async session or fresh session."""

    async def override_get_db() -> AsyncIterator[SQLAlchemyAsyncSession]:
        if async_session is not None:
            yield async_session
            return

        database_url = get_test_database_url()
        engine = _SHARED_TEST_ENGINE
        created_engine = False
        if engine is None:
            engine = create_async_engine(database_url, echo=False, pool_size=1, max_overflow=0)
            created_engine = True
        connection = await engine.connect()
        async_session_maker = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=SQLAlchemyAsyncSession,
        )
        async with async_session_maker() as session:
            yield session
            await connection.close()
            if created_engine:
                await engine.dispose()

    return override_get_db


@pytest_asyncio.fixture(scope="function")
async def sample_data(
    async_db: SQLAlchemyAsyncSession,
) -> dict[str, Thread | SessionModel | Event | User | list]:
    """Create sample threads, sessions for async testing."""
    now = datetime.now(UTC)
    username = _default_test_username()
    user = await async_db.execute(select(User).where(User.username == username))
    user = user.scalar_one_or_none()
    if not user:
        user = User(username=username, id=1, created_at=now)
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)
        await _sync_id_sequence(async_db, "users")

    threads = [
        Thread(
            id=1,
            title="Superman",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
            id=2,
            title="Batman",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=user.id,
            created_at=now,
            total_issues=10,
            reading_progress="in_progress",
        ),
        Thread(
            id=3,
            title="Wonder Woman",
            format="Comic",
            issues_remaining=0,
            queue_position=3,
            status="completed",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
            id=4,
            title="Flash",
            format="Comic",
            issues_remaining=15,
            queue_position=4,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
            id=5,
            title="Aquaman",
            format="Comic",
            issues_remaining=8,
            queue_position=5,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
    ]

    for thread in threads:
        async_db.add(thread)
        await async_db.flush()

    for thread in threads:
        await async_db.refresh(thread)

    # Create Issue records for migrated threads (Batman only)
    # Batman: 10 total, issues 1-5 read, 6-10 unread (5 remaining)
    batman_issues = []
    for i in range(1, 11):
        issue = Issue(
            id=i,
            thread_id=threads[1].id,
            issue_number=str(i),
            position=i,
            status="read" if i <= 5 else "unread",
            read_at=now if i <= 5 else None,
        )
        async_db.add(issue)
        batman_issues.append(issue)
    await async_db.flush()
    for issue in batman_issues:
        await async_db.refresh(issue)
    threads[1].next_unread_issue_id = batman_issues[5].id

    await async_db.flush()

    sessions = [
        SessionModel(
            id=1,
            start_die=6,
            user_id=user.id,
            started_at=now,
        ),
        SessionModel(
            id=2,
            start_die=8,
            user_id=user.id,
            started_at=now,
        ),
    ]

    for sess in sessions:
        async_db.add(sess)
        await async_db.flush()

    for sess in sessions:
        await async_db.refresh(sess)

    events = [
        Event(
            id=1,
            type="roll",
            die=6,
            result=4,
            selected_thread_id=threads[0].id,
            selection_method="random",
            session_id=sessions[0].id,
            thread_id=threads[0].id,
            timestamp=now,
        ),
        Event(
            id=2,
            type="rate",
            rating=4.5,
            issues_read=1,
            queue_move="back",
            die_after=8,
            session_id=sessions[0].id,
            thread_id=threads[0].id,
            timestamp=now,
        ),
    ]

    for event in events:
        async_db.add(event)
        await async_db.flush()

    for event in events:
        await async_db.refresh(event)

    await _sync_id_sequence(async_db, "threads")
    await _sync_id_sequence(async_db, "issues")
    await _sync_id_sequence(async_db, "sessions")
    await _sync_id_sequence(async_db, "events")

    return {"threads": threads, "sessions": sessions, "events": events, "user": user}


@pytest_asyncio.fixture(scope="function")
async def client(async_db: SQLAlchemyAsyncSession) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient for API tests."""
    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_client(
    async_db: SQLAlchemyAsyncSession, test_username: str
) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient with authentication headers for API tests."""
    from app.auth import create_access_token

    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        result = await async_db.execute(select(User).where(User.username == test_username))
        user = result.scalar_one_or_none()
        if not user:
            # Generate a unique ID for the test user to avoid conflicts
            result = await async_db.execute(text("SELECT MAX(id) FROM users"))
            max_id = result.scalar() or 0
            user_id = max_id + 1
            user = User(id=user_id, username=test_username, created_at=datetime.now(UTC))
            async_db.add(user)
            await async_db.flush()
            await async_db.refresh(user)
            await _sync_id_sequence(async_db, "users")

        token = create_access_token(data={"sub": user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def enable_internal_ops() -> Iterator[None]:
    """Enable internal ops routes for tests that access admin endpoints."""
    old_value = os.environ.get("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"
    yield
    if old_value is None:
        os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
    else:
        os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = old_value
