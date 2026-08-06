"""Regression coverage for bounded database dependency acquisition."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
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
    session = AsyncMock(spec=AsyncSession)
    session.connection.side_effect = lambda: asyncio.sleep(0.02)
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
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = lambda *_: asyncio.sleep(0.02)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(database, "DATABASE_DEPENDENCY_TIMEOUT_SECONDS", 0.01)

    assert await database.test_database_connection() is False
