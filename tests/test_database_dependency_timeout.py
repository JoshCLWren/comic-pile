"""Regression coverage for bounded database dependency acquisition."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

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
        await self._session.close()


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
async def test_get_db_retries_acquisition_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient acquisition failure opens a fresh session within the budget."""
    first_session = AsyncMock(spec=AsyncSession)
    first_session.connection.side_effect = sqlalchemy_exc.TimeoutError("waking")
    recovered_session = AsyncMock(spec=AsyncSession)
    sessions = iter((first_session, recovered_session))

    monkeypatch.setattr(
        database,
        "AsyncSessionLocal",
        lambda: _FakeSessionContext(next(sessions)),
    )
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(database, "DATABASE_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(database, "_database_circuit_open_until", 0.0)

    dependency: AsyncIterator[AsyncSession] = database.get_db()
    assert await anext(dependency) is recovered_session
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    first_session.connection.assert_awaited_once()
    first_session.close.assert_awaited_once()
    recovered_session.connection.assert_awaited_once()
    recovered_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_sustained_failure_is_bounded_and_opens_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exhaustion retries finitely, then the local circuit rejects another request."""
    sessions: list[AsyncMock] = []

    def session_factory() -> _FakeSessionContext:
        session = AsyncMock(spec=AsyncSession)
        session.connection.side_effect = sqlalchemy_exc.TimeoutError("offline")
        sessions.append(session)
        return _FakeSessionContext(session)

    monkeypatch.setattr(database, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(database, "DATABASE_ACQUISITION_ATTEMPTS", 2)
    monkeypatch.setattr(database, "DATABASE_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(database, "DATABASE_CIRCUIT_COOLDOWN_SECONDS", 10.0)
    monkeypatch.setattr(database, "_database_circuit_open_until", 0.0)

    with pytest.raises(HTTPException) as first_error:
        await anext(database.get_db())
    assert first_error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert len(sessions) == 2

    with pytest.raises(HTTPException) as circuit_error:
        await anext(database.get_db())
    assert circuit_error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert len(sessions) == 2
