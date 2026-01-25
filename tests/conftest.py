"""Shared pytest fixtures."""

import os
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession as SQLAlchemyAsyncSession,
)
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Event, Thread, User
from app.models import Session as SessionModel


load_dotenv()

if not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"

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


@pytest.fixture(scope="session", autouse=True)
def ensure_test_schema() -> None:
    """Ensure test DB schema matches current SQLAlchemy models.

    Tests use Base.metadata.create_all(), which does not alter existing tables. When a
    persistent Postgres test DB lags behind the models (e.g., missing users.email),
    we rebuild the schema once per run.

    This is only allowed for databases whose name contains 'test'.
    """
    database_url = get_sync_test_database_url()
    if database_url in _SCHEMA_PREPARED:
        return

    engine = create_engine(database_url, echo=False)
    with engine.begin() as conn:
        if _missing_model_columns(conn):
            if not _looks_like_test_database(database_url):
                raise RuntimeError(
                    "Refusing to reset schema on non-test database. "
                    f"Database '{make_url(database_url).database}' must include 'test'."
                )
            Base.metadata.drop_all(bind=conn)
        Base.metadata.create_all(bind=conn)

    engine.dispose()
    _SCHEMA_PREPARED.add(database_url)


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


def get_or_create_user(db: Session, username: str = "test_user") -> User:
    """Get or create user with given username."""
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not user:
        user = User(username=username, created_at=datetime.now(UTC))
        db.add(user)
        try:
            db.commit()
        except Exception:
            db.rollback()
            user = db.execute(select(User).where(User.username == username)).scalar_one()
        else:
            db.refresh(user)
    return user


@pytest.fixture(scope="function")
def default_user(db: Session) -> User:
    """Get or create default test user."""
    return _ensure_default_user(db)


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


def get_sync_test_database_url() -> str:
    """Get sync test database URL from environment (PostgreSQL only)."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        if test_db_url.startswith("postgresql+asyncpg://"):
            return test_db_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        return test_db_url

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if database_url.startswith("postgresql+asyncpg://"):
            return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        if database_url.startswith("postgresql+psycopg://"):
            return database_url

    raise ValueError(
        "No PostgreSQL test database configured. "
        "Set TEST_DATABASE_URL or DATABASE_URL environment variable (or add them to .env)."
    )


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


@pytest.fixture(scope="function")
def db() -> Generator[Session]:
    """Create test database with transaction rollback (PostgreSQL)."""
    database_url = get_sync_test_database_url()

    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    connection.execute(
        text(
            "TRUNCATE TABLE sessions, events, threads, snapshots, revoked_tokens, users "
            "RESTART IDENTITY CASCADE;"
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


def _create_db_override(db: Session):
    """Create dependency override for get_db using provided session."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    return override_get_db


@pytest_asyncio.fixture(scope="function")
async def client(db: Session) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient for API tests."""
    app.dependency_overrides[get_db] = _create_db_override(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_client(db: Session) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient with authentication headers for API tests."""
    from app.auth import create_access_token

    app.dependency_overrides[get_db] = _create_db_override(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
        if not user:
            user = User(username="test_user", created_at=datetime.now(UTC))
            db.add(user)
            db.commit()
            db.refresh(user)

        token = create_access_token(data={"sub": user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def safe_mode_auth_client(db: Session, safe_mode_user: User) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient authenticated as safe_mode_user for safe mode tests."""
    from app.auth import create_access_token

    app.dependency_overrides[get_db] = _create_db_override(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = create_access_token(data={"sub": safe_mode_user.username, "jti": "test"})
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def session(db: Session) -> Generator[Session]:
    """Get database session for tests."""
    yield db


@pytest.fixture(scope="function")
def sample_data(db: Session) -> dict[str, Thread | SessionModel | Event | User | list]:
    """Create sample threads, sessions for testing."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", id=1, created_at=now)
        db.add(user)
        db.commit()
        db.refresh(user)

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
        db.add(thread)
    db.flush()

    for thread in threads:
        db.refresh(thread)

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
        db.add(sess)
    db.flush()

    for sess in sessions:
        db.refresh(sess)

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
        db.add(event)
    db.flush()

    for event in events:
        db.refresh(event)

    return {"threads": threads, "sessions": sessions, "events": events, "user": user}


@pytest.fixture(scope="function")
def enable_internal_ops():
    """Enable internal ops routes for tests that access admin endpoints."""
    old_value = os.environ.get("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"
    yield
    if old_value is None:
        os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
    else:
        os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = old_value


@pytest.fixture(scope="function", autouse=True)
def clear_config_cache():
    """Clear cached settings before and after each test to prevent test pollution."""
    from app.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()
