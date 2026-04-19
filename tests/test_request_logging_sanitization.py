"""Tests for environment-aware request logging sanitization."""

import logging
import os

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient


def _find_client_error_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    for record in caplog.records:
        if record.name == "app.main" and record.getMessage().startswith("Client Error:"):
            return record
    raise AssertionError("Expected a 'Client Error' log record from app.main")


@pytest.mark.asyncio
async def test_development_logs_include_request_body_and_session_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """In development, request logging should include request context for debugging."""
    os.environ["ENVIRONMENT"] = "development"

    from app.main import create_app

    test_app = create_app(serve_frontend=False)
    test_app.router.on_startup.clear()
    test_app.router.on_shutdown.clear()

    @test_app.post("/test-error")
    async def test_error(request: Request):
        request.state.session_id = "session-123"
        request.state.user_id = 42
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": "nope"})

    caplog.set_level(logging.WARNING, logger="app.main")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/test-error", json={"hello": "world"})
        assert response.status_code == 400

    record = _find_client_error_record(caplog)
    assert record.__dict__["request_body"] == {"hello": "world"}
    assert record.__dict__["session_id"] == "session-123"
    assert record.__dict__["user_id"] == 42


@pytest.mark.asyncio
async def test_production_logs_drop_request_body_query_params_and_session_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """In production, request logging should avoid leaking request context."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com"

    from app.main import create_app

    test_app = create_app(serve_frontend=False)
    test_app.router.on_startup.clear()
    test_app.router.on_shutdown.clear()

    @test_app.post("/test-error")
    async def test_error(request: Request):
        request.state.session_id = "session-123"
        request.state.user_id = 42
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": "nope"})

    caplog.set_level(logging.WARNING, logger="app.main")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/test-error?foo=bar", json={"hello": "world"})
        assert response.status_code == 400

    record = _find_client_error_record(caplog)

    assert "request_body" not in record.__dict__
    assert "query_params" not in record.__dict__
    assert "session_id" not in record.__dict__
    assert record.__dict__["user_id"] == 42
