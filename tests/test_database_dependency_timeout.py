"""Regression coverage for bounded database dependency acquisition.

Covers the issue #1590/#1578 acceptance contract: transient database
unavailability (Neon scale-to-zero wakes, stale pooled connections) recovers
inside the same foreground request within a bounded budget, sustained failure
stays bounded behind a process-local circuit, route mutations are never
replayed, and genuine unavailability still returns a clear 503.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.ext.asyncio import AsyncSession

from app import database


class _FakeSessionContext:
    """Minimal async context manager mirroring ``AsyncSession`` semantics.

    The real ``AsyncSession.__aexit__`` closes the session, so the fake must do
    the same for teardown assertions to stay meaningful.
    """

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


@pytest.fixture(autouse=True)
def _reset_database_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep process-local circuit state isolated between tests."""
    monkeypatch.setattr(database, "_database_circuit_open_until", 0.0)


def _stale_connection_error() -> sqlalchemy_exc.DBAPIError:
    """Build the DBAPI failure class raised when a pooled connection died."""
    return sqlalchemy_exc.OperationalError(
        "SELECT 1",
        {},
        RuntimeError("server closed the connection unexpectedly"),
    )


@pytest.mark.asyncio
async def test_get_db_times_out_stalled_first_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled first connection fails explicitly instead of hanging the request."""

    async def stalled_connection() -> None:
        await asyncio.sleep(0.02)

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = stalled_connection
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 0.01)

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Database temporarily unavailable"


@pytest.mark.asyncio
async def test_get_db_does_not_time_out_route_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """The acquisition boundary must not impose a deadline on ordinary route work."""
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 0.01)

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    yielded_session = await anext(dependency)
    assert yielded_session is session

    await asyncio.sleep(0.02)
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_recovers_stale_connection_with_delayed_fresh_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale pooled connection recovers within the same request.

    The first acquisition fails fast with a dead-connection DBAPI error, then a
    delayed-but-successful fresh connection (a Neon wake finishing) is used for
    the same foreground request instead of surfacing a 503.
    """
    stale_session = AsyncMock(spec=AsyncSession)
    stale_session.connection.side_effect = _stale_connection_error()

    async def delayed_successful_connection() -> None:
        await asyncio.sleep(0.05)

    recovered_session = AsyncMock(spec=AsyncSession)
    recovered_session.connection.side_effect = delayed_successful_connection

    sessions = iter((stale_session, recovered_session))
    created: list[AsyncMock] = []

    def session_factory() -> _FakeSessionContext:
        session = next(sessions)
        created.append(session)
        return _FakeSessionContext(session)

    monkeypatch.setattr(database, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(database, "DATABASE_RETRY_BACKOFF_SECONDS", 0.0)

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    yielded_session = await anext(dependency)
    assert yielded_session is recovered_session

    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert len(created) == 2
    stale_session.close.assert_awaited_once()
    recovered_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_sustained_failure_is_bounded_and_opens_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exhaustion retries finitely, then the local circuit rejects further requests."""
    sessions: list[AsyncMock] = []

    def session_factory() -> _FakeSessionContext:
        session = AsyncMock(spec=AsyncSession)
        session.connection.side_effect = _stale_connection_error()
        sessions.append(session)
        return _FakeSessionContext(session)

    monkeypatch.setattr(database, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(database, "DATABASE_ACQUISITION_ATTEMPTS", 2)
    monkeypatch.setattr(database, "DATABASE_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(database, "DATABASE_CIRCUIT_COOLDOWN_SECONDS", 10.0)

    with pytest.raises(HTTPException) as first_error:
        await anext(database.get_db())
    assert first_error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert len(sessions) == 2

    with pytest.raises(HTTPException) as second_error:
        await anext(database.get_db())
    assert second_error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_get_db_circuit_closes_after_cooldown_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the cooldown expires a fresh request can succeed and reset the circuit."""
    failing_session = AsyncMock(spec=AsyncSession)
    failing_session.connection.side_effect = _stale_connection_error()
    healthy_session = AsyncMock(spec=AsyncSession)

    attempts = iter((failing_session, healthy_session))

    def session_factory() -> _FakeSessionContext:
        return _FakeSessionContext(next(attempts))

    monkeypatch.setattr(database, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(database, "DATABASE_ACQUISITION_ATTEMPTS", 1)
    monkeypatch.setattr(database, "DATABASE_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(database, "DATABASE_CIRCUIT_COOLDOWN_SECONDS", 0.05)

    with pytest.raises(HTTPException):
        await anext(database.get_db())

    await asyncio.sleep(0.06)

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    yielded_session = await anext(dependency)
    assert yielded_session is healthy_session
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert database._database_circuit_open_until == 0.0


@pytest.mark.asyncio
async def test_get_db_post_open_database_error_returns_503_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route-work failures are never replayed; they surface one clear 503."""
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(database, "DATABASE_ACQUISITION_ATTEMPTS", 2)

    dependency: AsyncGenerator[AsyncSession] = database.get_db()
    yielded_session = await anext(dependency)
    assert yielded_session is session

    with pytest.raises(HTTPException) as exc_info:
        await dependency.athrow(_stale_connection_error())

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Database temporarily unavailable"
    session.connection.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_connection_probe_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnostic probe returns false when its database command times out."""

    async def stalled_execute(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.02)

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = stalled_execute
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 0.01)

    assert await database.test_database_connection() is False


def test_recovery_constants_are_bounded() -> None:
    """Recovery tuning must stay bounded so outages cannot create retry storms."""
    assert 1 <= database.DATABASE_ACQUISITION_ATTEMPTS <= 5
    assert 0 <= database.DATABASE_RETRY_BACKOFF_SECONDS <= 1.0
    assert 0 < database.DATABASE_CIRCUIT_COOLDOWN_SECONDS <= 60.0
    assert database.DATABASE_RETRY_BACKOFF_SECONDS < database.DATABASE_DEPENDENCY_TIMEOUT_SECONDS
