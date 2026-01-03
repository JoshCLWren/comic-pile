"""Playwright integration test fixtures."""

import os
import tempfile
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uvicorn import Config, Server

from app.database import Base, get_db
from app.main import app

test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db_file.close()
TEST_DATABASE_URL = f"sqlite:///{test_db_file.name}"

test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def test_server():
    """Start a test server for Playwright tests."""
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        try:
            session = TestSessionLocal()
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    config = Config(app=app, host="127.0.0.1", port=8766, log_level="error")
    server = Server(config)

    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    time.sleep(3)

    yield "http://127.0.0.1:8766"

    server.should_exit = True
    time.sleep(1)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    os.unlink(test_db_file.name)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    test_session = TestSessionLocal()
    try:
        yield test_session
    finally:
        test_session.close()
        test_session = TestSessionLocal()
        for table in reversed(Base.metadata.sorted_tables):
            test_session.execute(table.delete())
        test_session.commit()
        test_session.close()
