"""Playwright integration test fixtures."""

import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uvicorn import Config, Server

from app.main import app

test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def test_server():
    """Start a test server for Playwright tests."""
    config = Config(app=app, host="127.0.0.1", port=8766, log_level="error")
    server = Server(config)

    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    time.sleep(3)

    yield "http://127.0.0.1:8766"

    server.should_exit = True
    time.sleep(1)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    test_session = TestSessionLocal()
    try:
        yield test_session
    finally:
        test_session.close()
