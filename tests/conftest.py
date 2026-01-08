"""Shared pytest fixtures."""

import os
from collections.abc import AsyncGenerator, AsyncIterator, Generator

import pytest
import pytest_asyncio
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
from app.models import Event, Task, Thread, User
from app.models import Session as SessionModel


def get_test_database_url() -> str:
    """Get test database URL from environment or use SQLite default."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    return "sqlite+aiosqlite:///:memory:"


def get_sync_test_database_url() -> str:
    """Get sync test database URL from environment or use SQLite default."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        return test_db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgresql"):
        return database_url
    return "sqlite:///:memory:"


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


@pytest.fixture(scope="function")
def db() -> Generator[Session]:
    """Create test database with transaction rollback (SQLite) or TRUNCATE (PostgreSQL)."""
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
        yield session
    finally:
        session.close()
        if transaction is not None:
            transaction.rollback()
        connection.close()
        engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db: Session) -> AsyncGenerator[AsyncClient]:
    """httpx.AsyncClient for API tests."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def session(db: Session) -> Generator[Session]:
    """Get database session for tests."""
    yield db


@pytest.fixture(scope="function")
def sample_tasks(db: Session) -> list[Task]:
    """Create sample tasks for testing."""
    from app.models import Task as TaskModel

    tasks = [
        TaskModel(
            task_id="TASK-101",
            title="Complete Narrative Session Summaries",
            description="Test description",
            instructions="Test instructions",
            priority="HIGH",
            dependencies=None,
            estimated_effort="4 hours",
            status="pending",
            completed=False,
        ),
        TaskModel(
            task_id="TASK-102",
            title="Add Staleness Awareness UI",
            description="Test description",
            instructions="Test instructions",
            priority="MEDIUM",
            dependencies=None,
            estimated_effort="3 hours",
            status="pending",
            completed=False,
        ),
    ]

    for task in tasks:
        db.add(task)
    db.commit()

    for task in tasks:
        db.refresh(task)

    return tasks


@pytest.fixture(scope="function")
def sample_data(db: Session) -> dict[str, Thread | SessionModel | Event | User | list]:
    """Create sample threads, sessions for testing."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=now)
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
    db.commit()

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
    db.commit()

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
    db.commit()

    for event in events:
        db.refresh(event)

    return {"threads": threads, "sessions": sessions, "events": events, "user": user}


@pytest.fixture(scope="function")
def task_data(db: Session) -> list:
    """Create sample tasks for testing."""
    tasks = []
    for i in range(1, 13):
        task = Task(
            task_id=f"TASK-10{i}",
            title=f"Test Task {i}",
            description=f"Description for test task {i}",
            priority="HIGH" if i < 5 else "MEDIUM" if i < 9 else "LOW",
            status="pending",
            instructions="Test instructions",
            estimated_effort="1 hour",
            completed=False,
        )
        db.add(task)
        tasks.append(task)

    db.commit()

    for task in tasks:
        db.refresh(task)

    return tasks
