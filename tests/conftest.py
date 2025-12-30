"""Shared pytest fixtures."""

from collections.abc import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Event, Thread, User
from app.models import Session as SessionModel

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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


@pytest.fixture(scope="function")
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
def sample_data(db: Session) -> dict[str, Thread | SessionModel | Event | User | list]:
    """Create sample threads, sessions for testing."""
    user = User(id=1, username="test_user")
    db.add(user)
    db.commit()

    threads = [
        Thread(
            id=1,
            title="Superman",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=1,
        ),
        Thread(
            id=2,
            title="Batman",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=1,
        ),
        Thread(
            id=3,
            title="Wonder Woman",
            format="Comic",
            issues_remaining=0,
            queue_position=3,
            status="completed",
            user_id=1,
        ),
        Thread(
            id=4,
            title="Flash",
            format="Comic",
            issues_remaining=15,
            queue_position=4,
            status="active",
            user_id=1,
        ),
        Thread(
            id=5,
            title="Aquaman",
            format="Comic",
            issues_remaining=8,
            queue_position=5,
            status="active",
            user_id=1,
        ),
    ]

    for thread in threads:
        db.add(thread)
    db.commit()

    sessions = [
        SessionModel(
            id=1,
            start_die=6,
            user_id=1,
        ),
        SessionModel(
            id=2,
            start_die=8,
            user_id=1,
        ),
    ]

    for sess in sessions:
        db.add(sess)
    db.commit()

    events = [
        Event(
            id=1,
            type="roll",
            die=6,
            result=4,
            selected_thread_id=1,
            selection_method="random",
            session_id=1,
            thread_id=1,
        ),
        Event(
            id=2,
            type="rate",
            rating=4.5,
            issues_read=1,
            queue_move="back",
            die_after=8,
            session_id=1,
            thread_id=1,
        ),
    ]

    for event in events:
        db.add(event)
    db.commit()

    return {"threads": threads, "sessions": sessions, "events": events, "user": user}
