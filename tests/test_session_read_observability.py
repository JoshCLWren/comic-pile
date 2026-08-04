"""Tests for current-session and History read diagnostics."""

import logging

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.middleware.security_headers import SecurityHeadersMiddleware, _session_read_operation
from app.performance_diagnostics import (
    begin_request_diagnostics,
    end_request_diagnostics,
    record_cache_operation,
    record_database_query,
)


def _request(path: str, method: str = "GET") -> Request:
    """Build a minimal Starlette request for middleware tests."""
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
        }
    )


def test_session_read_operation_classifies_only_bounded_list_reads() -> None:
    """Current-session and History lists are instrumented without detail noise."""
    assert _session_read_operation("/api/sessions/current/", "GET") == "current-session"
    assert _session_read_operation("/api/v1/sessions/current", "GET") == "current-session"
    assert _session_read_operation("/api/sessions/", "GET") == "history-list"
    assert _session_read_operation("/api/v1/sessions", "GET") == "history-list"
    assert _session_read_operation("/api/sessions/42", "GET") is None
    assert _session_read_operation("/api/sessions/current/", "POST") is None


@pytest.mark.asyncio
async def test_current_session_response_exposes_phase_and_query_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful current-session reads expose structured timing evidence."""
    middleware = SecurityHeadersMiddleware(app=lambda scope, receive, send: None)
    request = _request("/api/sessions/current/")
    request.state.request_id = "request-123"
    token = begin_request_diagnostics()

    async def call_next(_request: Request) -> JSONResponse:
        record_database_query(12.5)
        record_database_query(7.5)
        record_cache_operation("hit", 2.0)
        return JSONResponse({"id": 1})

    try:
        with caplog.at_level(logging.WARNING):
            response = await middleware.dispatch(request, call_next)
    finally:
        end_request_diagnostics(token)

    assert response.headers["X-Session-Read-Operation"] == "current-session"
    assert response.headers["X-Session-Read-DB-Ms"] == "20.00"
    assert response.headers["X-Session-Read-DB-Queries"] == "2"
    assert response.headers["X-Session-Read-Cache-Ms"] == "2.00"
    assert response.headers["X-Session-Read-Cache-Calls"] == "1"
    assert float(response.headers["X-Session-Read-Total-Ms"]) >= 0
    assert float(response.headers["X-Session-Read-App-Ms"]) >= 0
    assert "Session read diagnostics: current-session" in caplog.text


@pytest.mark.asyncio
async def test_history_detail_response_does_not_emit_list_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Session details keep ordinary headers without list-pipeline diagnostics."""
    middleware = SecurityHeadersMiddleware(app=lambda scope, receive, send: None)
    request = _request("/api/sessions/42/")
    token = begin_request_diagnostics()

    async def call_next(_request: Request) -> JSONResponse:
        record_database_query(1.0)
        return JSONResponse({"id": 42})

    try:
        with caplog.at_level(logging.WARNING):
            response = await middleware.dispatch(request, call_next)
    finally:
        end_request_diagnostics(token)

    assert "X-Session-Read-Operation" not in response.headers
    assert "Session read diagnostics" not in caplog.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
