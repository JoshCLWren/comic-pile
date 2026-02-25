"""Shared pytest fixtures."""

import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession as SQLAlchemyAsyncSession,
)
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import Connection, make_url

from app.database import Base, get_db
from app.main import app
from app.models import Event, Issue, Thread, User
from app.models import Session as SessionModel


load_dotenv()

if not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"


@pytest.fixture(scope="session", autouse=True)
def enable_rate_limiting_for_tests() -> Iterator[None]:
    """Enable rate limiting for rate limit tests."""
    original_value = os.environ.get("ENABLE_RATE_LIMITING_IN_TESTS")
    yield
    if original_value is None:
        os.environ.pop("ENABLE_RATE_LIMITING_IN_TESTS", None)
    else:
        os.environ["ENABLE_RATE_LIMITING_IN_TESTS"] = original_value


_SCHEMA_PREPARED: set[str] = set()


def _looks_like_test_database(database_url: str) -> bool:
    url = make_url(database_url)
    db_name = (url.database or "").lower()

    allow_list = {"test", "ci", "dev", "comic_pile_test"}
    if db_name in allow_list:
        return True

    for prefix in allow_list:
        if db_name.startswith(f"{prefix}_") or db_name.startswith(f"{prefix}-"):
            return True

    return db_name.endswith("_test") or db_name.endswith("-test")


def _missing_model_columns(conn: Connection) -> bool:
    inspector = inspect(conn)

    required_table_names = {
        "users",
        "sessions",
        "threads",
        "events",
        "snapshots",
        "revoked_tokens",
    }

    for table_name in required_table_names:
        if not inspector.has_table(table_name):
            return True

        existing = {str(col["name"]) for col in inspector.get_columns(table_name)}
        expected = {col.name for col in Base.metadata.tables[table_name].columns}
        if not expected.issubset(existing):
            return True

    return False


@pytest_asyncio.fixture(scope="session", autouse=True)
async def ensure_test_schema() -> None:
    """Ensure test DB schema matches current SQLAlchemy models.

    Tests use Base.metadata.create_all(), which does not alter existing tables. When a
    persistent Postgres test DB lags behind the models (e.g., missing users.email),
    we rebuild the schema once per run.

    This is only allowed for databases whose name contains 'test'.
    """
    database_url = get_test_database_url()
    if database_url in _SCHEMA_PREPARED:
        return

    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:

        def _check_and_drop(conn: Connection) -> None:
            if _missing_model_columns(conn):
                if not _looks_like_test_database(database_url):
                    raise RuntimeError(
                        "Refusing to reset schema on non-test database. "
                        f"Database '{make_url(database_url).database}' must include 'test'."
                    )
                Base.metadata.drop_all(bind=conn)
            Base.metadata.create_all(bind=conn)

        await conn.run_sync(_check_and_drop)

    await engine.dispose()
    _SCHEMA_PREPARED.add(database_url)


async def _ensure_default_user_async(db: SQLAlchemyAsyncSession) -> User:
    """Ensure default user exists in database (user_id=1 for API compatibility)."""
    result = await db.execute(select(User).where(User.id == 1))
    user = result.scalar_one_or_none()
    if not user:
        username = f"test_user_{os.getpid()}"
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            user = User(username=username, created_at=datetime.now(UTC))
            db.add(user)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                result = await db.execute(select(User).where(User.username == username))
                user = result.scalar_one()
            else:
                await db.refresh(user)
    return user


async def get_or_create_user_async(db: SQLAlchemyAsyncSession, username: str | None = None) -> User:
    """Get or create user with given username (async)."""
    if username is None:
        username = f"test_user_{os.getpid()}"
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username=username, created_at=datetime.now(UTC))
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one()
        else:
            await db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def default_user(async_db: SQLAlchemyAsyncSession) -> User:
    """Get or create default test user."""
    return await _ensure_default_user_async(async_db)


@pytest.fixture(scope="session")
def test_username() -> str:
    """Get process-specific test username for direct database queries."""
    return f"test_user_{os.getpid()}"


def get_test_database_url() -> str:
    """Get test database URL from environment (PostgreSQL only)."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url

    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url

    raise ValueError(
        "No PostgreSQL test database configured. "
        "Set TEST_DATABASE_URL or DATABASE_URL environment variable (or add them to .env)."
    )


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
async def async_db() -> AsyncIterator[SQLAlchemyAsyncSession]:
    """Create async test database with transaction rollback (PostgreSQL)."""
    database_url = get_test_database_url()

    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_maker = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=SQLAlchemyAsyncSession,
    )

    async with async_session_maker() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE sessions, events, threads, snapshots, revoked_tokens, users "
                "RESTART IDENTITY CASCADE;"
            )
        )
        await session.commit()
        yield session

    await engine.dispose()


async def _create_async_db_override(
    async_session: SQLAlchemyAsyncSession | None = None,
) -> Callable[[], AsyncIterator[SQLAlchemyAsyncSession]]:
    """Create dependency override for get_db using provided async session or fresh session."""

    async def override_get_db() -> AsyncIterator[SQLAlchemyAsyncSession]:
        if async_session is not None:
            yield async_session
            return

        database_url = get_test_database_url()
        engine = create_async_engine(database_url, echo=False, pool_size=1, max_overflow=0)
        connection = await engine.connect()
        async_session_maker = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=SQLAlchemyAsyncSession,
        )
        async with async_session_maker() as session:
            yield session
        await connection.close()
        await engine.dispose()

    return override_get_db


@pytest_asyncio.fixture(scope="function")
async def sample_data(
    async_db: SQLAlchemyAsyncSession,
) -> dict[str, Thread | SessionModel | Event | User | list]:
    """Create sample threads, sessions for async testing."""
    import os

    now = datetime.now(UTC)
    username = f"test_user_{os.getpid()}"
    user = await async_db.execute(select(User).where(User.username == username))
    user = user.scalar_one_or_none()
    if not user:
        user = User(username=username, id=1, created_at=now)
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    threads = [
        Thread(
            title="Superman",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
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
            title="Wonder Woman",
            format="Comic",
            issues_remaining=0,
            queue_position=3,
            status="completed",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
            title="Flash",
            format="Comic",
            issues_remaining=15,
            queue_position=4,
            status="active",
            user_id=user.id,
            created_at=now,
        ),
        Thread(
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
            thread_id=threads[1].id,
            issue_number=str(i),
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
            start_die=6,
            user_id=user.id,
            started_at=now,
        ),
        SessionModel(
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
            user = User(username=test_username, created_at=datetime.now(UTC))
            async_db.add(user)
            await async_db.flush()
            await async_db.refresh(user)

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


@pytest.fixture(scope="function", autouse=True)
def clear_config_cache() -> Iterator[None]:
    """Clear cached settings before and after each test to prevent test pollution."""
    from app.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()
