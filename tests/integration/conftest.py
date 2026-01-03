"""Playwright integration test fixtures."""

import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uvicorn import Config, Server

from app.database import Base, get_db
from app.main import app

test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def test_server():
    """Start a test server for Playwright tests."""

    def override_get_db():
        test_session = TestSessionLocal()
        try:
            yield test_session
        finally:
            test_session.close()

    app.dependency_overrides[get_db] = override_get_db

    config = Config(app=app, host="127.0.0.1", port=9876, log_level="error")
    server = Server(config)

    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    time.sleep(3)

    yield "http://127.0.0.1:9876"

    server.should_exit = True
    time.sleep(1)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=test_engine)
    test_session = TestSessionLocal()
    try:
        yield test_session
    finally:
        test_session.close()
        Base.metadata.drop_all(bind=test_engine)
