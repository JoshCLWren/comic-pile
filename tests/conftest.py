"""Shared pytest fixtures."""

import os
import tempfile
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Event, Task, Thread, User
from app.models import Session as SessionModel

test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db_file.close()
TEST_DATABASE_URL = f"sqlite:///{test_db_file.name}"

test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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
    """Create in-memory SQLite database for tests."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


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
