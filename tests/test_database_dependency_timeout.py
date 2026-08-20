"""Regression coverage for bounded database dependency acquisition."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.ext.asyncio import AsyncSession

from app import database


class _FakeSessionContext:
    """Minimal async context manager used to exercise the dependency boundary."""

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
async def test_database_connection_probe_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnostic probe returns false when its database command times out."""

    async def stalled_execute(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.02)

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = stalled_execute
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 0.01)

    assert await database.test_database_connection() is False


@pytest.mark.asyncio
async def test_get_db_retries_on_transient_interface_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stale pooled connection (InterfaceError) should retry and succeed on fresh connection.

    Simulates Neon scale-to-zero wake-up: first attempt gets a stale pooled connection
    that fails with InterfaceError, second attempt establishes a fresh connection and succeeds.
    """
    attempt_count = 0

    async def connection_with_retry() -> None:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            # First attempt: simulate stale pooled connection (InterfaceError)
            orig = MagicMock()
            orig.__class__.__name__ = "InterfaceError"
            error = sqlalchemy_exc.DBAPIError("stale connection", orig=orig, params=())
            raise error
        # Second attempt: success
        return None

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = connection_with_retry
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(database, "DB_MAX_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(database, "DB_INITIAL_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(database, "DB_MAX_RETRY_DELAY_SECONDS", 0.05)
    # Reset circuit breaker
    database.get_database_circuit_breaker().reset()

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    yielded_session = await anext(dependency)

    assert yielded_session is session
    assert attempt_count == 2  # First failed, second succeeded


@pytest.mark.asyncio
async def test_get_db_retries_on_timeout_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection timeout should retry and succeed when database wakes up.

    Simulates Neon wake-up taking longer than connect timeout: first attempt times out,
    second attempt succeeds within the overall dependency budget.
    """
    attempt_count = 0

    async def connection_with_timeout() -> None:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            # First attempt: timeout
            raise TimeoutError("connection timeout")
        # Second attempt: success
        return None

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = connection_with_timeout
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(database, "DB_MAX_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(database, "DB_INITIAL_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(database, "DB_MAX_RETRY_DELAY_SECONDS", 0.05)
    database.get_database_circuit_breaker().reset()

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    yielded_session = await anext(dependency)

    assert yielded_session is session
    assert attempt_count == 2


@pytest.mark.asyncio
async def test_get_db_exhausts_retries_on_persistent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persistent connection failures should exhaust retries and return 503.

    Verifies that retries are bounded and don't create a retry storm.
    """
    attempt_count = 0

    async def always_fails() -> None:
        nonlocal attempt_count
        attempt_count += 1
        raise TimeoutError("persistent timeout")

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = always_fails
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(database, "DB_MAX_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(database, "DB_INITIAL_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(database, "DB_MAX_RETRY_DELAY_SECONDS", 0.05)
    database.get_database_circuit_breaker().reset()

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert attempt_count == 3  # All retry attempts exhausted


@pytest.mark.asyncio
async def test_get_db_circuit_breaker_opens_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Circuit breaker should open after repeated failures and block subsequent attempts.

    Verifies that sustained database outage doesn't create a retry storm.
    """
    # Reset circuit breaker
    database.get_database_circuit_breaker().reset()

    async def always_fails() -> None:
        raise TimeoutError("persistent timeout")

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = always_fails
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(database, "DB_MAX_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(database, "DB_INITIAL_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(database, "DB_MAX_RETRY_DELAY_SECONDS", 0.05)
    monkeypatch.setattr(database, "DB_CIRCUIT_FAILURE_THRESHOLD", 2)

    # First request exhausts retries and records failures
    dependency1: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException):
        await anext(dependency1)

    # Second request also exhausts retries
    dependency2: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException):
        await anext(dependency2)

    # Circuit should now be open - third request fails immediately
    dependency3: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency3)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "circuit open" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_db_non_transient_error_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-transient database errors should fail immediately without retry."""
    attempt_count = 0

    async def non_transient_error() -> None:
        nonlocal attempt_count
        attempt_count += 1
        # Simulate a non-transient error (e.g., authentication failure)
        error = sqlalchemy_exc.DBAPIError("authentication failed")
        error.orig = None  # No orig exception
        raise error

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = non_transient_error
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(database, "DB_MAX_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(database, "DB_INITIAL_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(database, "DB_MAX_RETRY_DELAY_SECONDS", 0.05)
    database.get_database_circuit_breaker().reset()

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert attempt_count == 1  # No retry for non-transient error


@pytest.mark.asyncio
async def test_get_db_respects_overall_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries should not exceed the overall dependency timeout budget."""
    attempt_count = 0

    async def slow_fail() -> None:
        nonlocal attempt_count
        attempt_count += 1
        await asyncio.sleep(0.1)  # Each attempt takes 100ms
        raise TimeoutError("timeout")

    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = slow_fail
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 0.25)  # 250ms total budget
    monkeypatch.setattr(database, "DB_MAX_RETRY_ATTEMPTS", 10)  # High retry count
    monkeypatch.setattr(database, "DB_INITIAL_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(database, "DB_MAX_RETRY_DELAY_SECONDS", 0.05)
    database.get_database_circuit_breaker().reset()

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    # Should not attempt more than budget allows (max ~2 attempts within 250ms with 100ms each + backoff)
    assert attempt_count <= 3
