"""Tests for request and database performance diagnostics."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import AsyncSessionLocal, async_engine
from app.middleware.request_logging import add_request_logging_middleware
from app.performance_diagnostics import (
    begin_request_diagnostics,
    end_request_diagnostics,
    get_request_diagnostics,
    identity_database_query_scope,
    record_database_query,
)


@pytest.mark.asyncio
async def test_request_middleware_emits_performance_headers() -> None:
    """Responses should expose a request ID and timing breakdown."""
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/diagnostics")
    async def diagnostics_route() -> dict[str, str]:
        """Return a response after recording synthetic request activity."""
        record_database_query(8.25)
        return {"status": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/diagnostics")

    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 32
    assert response.headers["x-app-db-queries"] == "1"
    assert response.headers["x-app-auth-db-queries"] == "0"
    server_timing = response.headers["server-timing"]
    assert "app;dur=" in server_timing
    assert 'db;dur=8.25;desc="1 queries"' in server_timing


@pytest.mark.asyncio
async def test_request_middleware_exposes_identity_query_subset() -> None:
    """Responses expose identity SQL separately from total request SQL."""
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/identity-diagnostics")
    async def identity_diagnostics_route() -> dict[str, str]:
        """Return after recording one business and two identity statements."""
        record_database_query(1.0)
        with identity_database_query_scope():
            record_database_query(2.0)
            record_database_query(3.0)
        return {"status": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/identity-diagnostics")

    assert response.status_code == 200
    assert response.headers["x-app-db-queries"] == "3"
    assert response.headers["x-app-auth-db-queries"] == "2"


@pytest.mark.asyncio
async def test_database_events_record_a_real_async_query() -> None:
    """SQLAlchemy execution events should update the active request context."""
    async_engine.sync_engine.dispose(close=False)
    token = begin_request_diagnostics()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        diagnostics = get_request_diagnostics()
    finally:
        await async_engine.dispose()
        end_request_diagnostics(token)

    assert diagnostics.database_queries >= 1
    assert diagnostics.database_time_ms >= 0
