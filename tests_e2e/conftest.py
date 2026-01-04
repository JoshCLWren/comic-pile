"""Playwright integration test fixtures."""

import os
import tempfile
import threading
from collections.abc import AsyncGenerator, Generator
from socket import socket

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from playwright.async_api import async_playwright
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import uvicorn

from app.database import Base, get_db
from app.main import app

test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db_file.close()
TEST_DATABASE_URL = f"sqlite:///{test_db_file.name}"

test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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
    """Create in-memory SQLite database for tests."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session(db: Session) -> Generator[Session]:
    """Get database session for tests (alias for db)."""
    yield db


@pytest.fixture(scope="session")
def test_server():
    """Base URL for test server."""
    yield "http://test"

    # @pytest.fixture(scope="session", autouse=True)
    # def live_server():
    """Start a live test server for e2e browser tests."""
    import subprocess

    original_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    Base.metadata.create_all(bind=test_engine)

    proc = subprocess.Popen(
        [
            ".venv/bin/python",
            "-m",
            "uvicorn",
            "app.main:app",
            f"--host=127.0.0.1",
            f"--port={TEST_SERVER_PORT}",
            "--log-level=error",
        ],
        env=os.environ.copy(),
    )

    import time

    time.sleep(2)

    yield

    proc.terminate()
    proc.wait(timeout=5)

    if original_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original_db_url


@pytest_asyncio.fixture(scope="session")
async def browser():
    """Shared browser for all integration tests."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture(scope="function")
async def browser_page(browser):
    """New page per test."""
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await context.close()


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
