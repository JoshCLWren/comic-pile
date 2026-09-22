"""Regression tests for database unavailability error contract (issue #2830).

Covers the acceptance criteria for classifying database dependency failures
as a stable 503 instead of generic 500.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DatabaseUnavailableError
from app.main import create_app


class _FakeSessionContext:
    """Minimal async context manager mirroring AsyncSession semantics."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        await self._session.close()


class InsufficientResourcesError(Exception):
    """Mock asyncpg InsufficientResourcesError for testing."""
    sqlstate = "53300"


def _make_insufficient_resources_error() -> sqlalchemy_exc.DBAPIError:
    """Build a DBAPIError wrapping asyncpg InsufficientResourcesError.

    This simulates the production incident where Neon Free-plan
    data-transfer quota was exhausted.
    """
    orig_error = InsufficientResourcesError("Neon data transfer quota exhausted")

    return sqlalchemy_exc.DBAPIError(
        "connection",
        {},
        orig_error,
    )


def _make_programming_error() -> sqlalchemy_exc.ProgrammingError:
    """Build a SQLAlchemy ProgrammingError for a query bug.

    This should remain a 500, not be classified as database unavailability.
    """
    return sqlalchemy_exc.ProgrammingError(
        "SELECT * FROM nonexistent_table",
        {},
        Exception("relation \"nonexistent_table\" does not exist"),
    )


def _make_integrity_error() -> sqlalchemy_exc.IntegrityError:
    """Build a SQLAlchemy IntegrityError for a constraint violation.

    This should remain a 500, not be classified as database unavailability.
    """
    return sqlalchemy_exc.IntegrityError(
        "INSERT INTO users ...",
        {},
        Exception("duplicate key value violates unique constraint"),
    )


@pytest.mark.asyncio
async def test_insufficient_resources_error_produces_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulated Neon/Postgres connection-resource exhaustion produces HTTP 503.

    This test covers the exact production incident class: asyncpg
    InsufficientResourcesError wrapped in SQLAlchemy DBAPIError.
    """
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-db-error")
    async def test_db_error(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        await db.execute("SELECT 1")
        return {"status": "ok"}

    # Mock the session factory to return a session that fails on execute
    error = _make_insufficient_resources_error()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    session.connection = AsyncMock()
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-db-error")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "database_unavailable"
    assert data["error"]["status"] == "SERVICE_UNAVAILABLE"
    assert "temporarily unavailable" in data["error"]["message"].lower()
    # Should NOT contain raw error details
    assert "quota" not in response.text.lower()
    assert "neon" not in response.text.lower()
    # Retry-After header should be present and bounded
    assert "Retry-After" in response.headers
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= 60  # Bounded window
    # Request ID should be present
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_programming_error_produces_500_not_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary programming/query error produces 500, not mislabeled as 503.

    Query bugs should remain 500s so they are not hidden as infrastructure incidents.
    """
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-db-error")
    async def test_db_error(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        await db.execute("SELECT 1")
        return {"status": "ok"}

    # Mock the session factory to return a session that fails with programming error
    error = _make_programming_error()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    session.connection = AsyncMock()
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-db-error")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    data = response.json()
    assert data["detail"] == "Internal server error"
    # Should NOT have database_unavailable code
    assert "error" not in data or data.get("error", {}).get("code") != "database_unavailable"


@pytest.mark.asyncio
async def test_integrity_error_produces_500_not_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integrity/constraint violation produces 500, not mislabeled as 503."""
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-db-error")
    async def test_db_error(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        await db.execute("SELECT 1")
        return {"status": "ok"}

    error = _make_integrity_error()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    session.connection = AsyncMock()
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-db-error")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    data = response.json()
    assert data["detail"] == "Internal server error"


@pytest.mark.asyncio
async def test_acquisition_failure_insufficient_resources_produces_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection acquisition failure with InsufficientResourcesError produces 503."""
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-db-error")
    async def test_db_error(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        return {"status": "ok"}

    # Mock the session factory to fail on connection()
    error = _make_insufficient_resources_error()
    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = error
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-db-error")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert data["error"]["code"] == "database_unavailable"
    assert "Retry-After" in response.headers


@pytest.mark.asyncio
async def test_acquisition_failure_programming_error_produces_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection acquisition failure with programming error produces 500.

    Although rare at acquisition, this ensures we don't misclassify.
    """
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-db-error")
    async def test_db_error(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        return {"status": "ok"}

    error = _make_programming_error()
    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = error
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-db-error")

    # Programming errors at acquisition should still be 500
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_auth_endpoint_database_unavailability_not_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authentication endpoints do not translate database unavailability into 401/403."""
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-auth")
    async def test_auth(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        await db.execute("SELECT 1")
        return {"status": "authenticated"}

    error = _make_insufficient_resources_error()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    session.connection = AsyncMock()
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-auth")

    # Must be 503, not 401 or 403
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.status_code not in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
    data = response.json()
    assert data["error"]["code"] == "database_unavailable"


@pytest.mark.asyncio
async def test_health_live_endpoint_remains_dependency_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/health/live remains dependency-free liveness endpoint."""
    test_app = create_app(serve_frontend=False)

    # Even if database is completely broken, /health/live should work
    def fail_db() -> AsyncIterator[AsyncSession]:
        raise RuntimeError("Database completely broken")

    test_app.dependency_overrides[get_db] = fail_db

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_legacy_health_endpoint_remains_dependency_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/health (legacy) remains dependency-free liveness endpoint."""
    test_app = create_app(serve_frontend=False)

    def fail_db() -> AsyncIterator[AsyncSession]:
        raise RuntimeError("Database completely broken")

    test_app.dependency_overrides[get_db] = fail_db

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_database_unavailable_error_log_context() -> None:
    """DatabaseUnavailableError.to_log_context returns structured info."""
    # Test with asyncpg-style error
    class MockInsufficientResourcesError(Exception):
        sqlstate = "53300"

    orig_error = MockInsufficientResourcesError("quota exhausted")
    orig_error.__class__.__name__ = "InsufficientResourcesError"

    db_error = sqlalchemy_exc.DBAPIError("stmt", {}, orig_error)
    exc = DatabaseUnavailableError(
        "Database temporarily unavailable",
        original_error=db_error,
        error_class="InsufficientResourcesError",
        sqlstate="53300",
    )

    ctx = exc.to_log_context()
    assert ctx["error_class"] == "InsufficientResourcesError"
    assert ctx["sqlstate"] == "53300"
    assert "temporarily unavailable" in ctx["message"]


@pytest.mark.asyncio
async def test_database_unavailable_error_without_original() -> None:
    """DatabaseUnavailableError works without original error."""
    exc = DatabaseUnavailableError(
        "Database temporarily unavailable",
        error_class="CircuitOpen",
    )

    ctx = exc.to_log_context()
    assert ctx["error_class"] == "CircuitOpen"
    assert ctx["sqlstate"] is None
    assert "temporarily unavailable" in ctx["message"]


@pytest.mark.asyncio
async def test_retry_after_header_bounded() -> None:
    """Retry-After header is present and bounded."""
    from app.exception_handlers import RETRY_AFTER_SECONDS

    assert RETRY_AFTER_SECONDS > 0
    assert RETRY_AFTER_SECONDS <= 60  # Bounded to reasonable window


@pytest.mark.asyncio
async def test_database_unavailable_response_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the complete response structure for database unavailability."""
    test_app = create_app(serve_frontend=False)

    @test_app.get("/test-db-error")
    async def test_db_error(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        await db.execute("SELECT 1")
        return {"status": "ok"}

    error = _make_insufficient_resources_error()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = error
    session.connection = AsyncMock()
    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", lambda: _FakeSessionContext(session)
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-db-error")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()

    # Google-style error envelope
    assert "error" in data
    error_obj = data["error"]
    assert error_obj["code"] == "database_unavailable"
    assert error_obj["status"] == "SERVICE_UNAVAILABLE"
    assert isinstance(error_obj["message"], str)
    assert len(error_obj["message"]) > 0

    # Headers
    assert "Retry-After" in response.headers
    assert "X-Request-ID" in response.headers

    # No sensitive data leaked
    response_text = response.text.lower()
    assert "password" not in response_text
    assert "secret" not in response_text
    assert "token" not in response_text
    assert "neon" not in response_text
    assert "quota" not in response_text


@pytest.mark.asyncio
async def test_dependency_health_endpoint_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/api/v1/health/dependencies continues to be the explicit dependency-aware probe."""
    from app.services import health_probe

    test_app = create_app(serve_frontend=False)

    async def healthy_cache() -> None:
        return None

    async def unavailable_database(_: AsyncSession) -> None:
        raise health_probe.ProbeUnavailableError("database offline")

    monkeypatch.setattr(health_probe, "database_probe", unavailable_database)
    monkeypatch.setattr(health_probe, "cache_probe", healthy_cache)
    # The token gate only applies once a token is configured.
    monkeypatch.setenv("HEALTH_CHECK_TOKEN", "test-token")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without auth token, should 404
        response = await client.get("/api/v1/health/dependencies")
        assert response.status_code == 404

        # With token, should return 503 for unhealthy
        response = await client.get(
            "/api/v1/health/dependencies", headers={"X-Health-Token": "test-token"}
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        payload = response.json()
        assert payload["status"] == "unhealthy"
        assert payload["database"]["status"] == "unavailable"


# Cleanup fixture to reset database circuit between tests
@pytest.fixture(autouse=True)
def _reset_database_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep process-local circuit state isolated between tests."""
    import app.database as database_module

    monkeypatch.setattr(database_module, "_database_circuit_open_until", 0.0)