"""Integration coverage for startup and first-request observability."""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.request_logging import (
    _sanitize_log_path,
    add_request_logging_middleware,
    sanitize_for_logging,
)
from app.startup_diagnostics import reset_startup_diagnostics_for_test


@pytest.mark.asyncio
async def test_first_request_is_correlated_with_startup_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Startup and HTTP responses retain process-level timing context.

    Args:
        monkeypatch: Pytest environment patch helper.
        caplog: Pytest log capture fixture.

    Returns:
        None.
    """
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "100000")
    reset_startup_diagnostics_for_test()

    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/fast")
    async def fast_route() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/missing")
    async def missing_route() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="not found")

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/fast")
            second = await client.get("/fast")
            error = await client.get("/missing")

    assert first.headers["X-App-Cold-Request"] == "1"
    assert second.headers["X-App-Cold-Request"] == "0"
    assert error.status_code == 404
    assert error.headers["X-App-Cold-Request"] == "0"
    assert len(error.headers["X-Request-ID"]) == 32
    assert "Server-Timing" in error.headers
    assert "X-App-DB-Queries" in error.headers
    assert "X-App-Cache" in error.headers

    startup_records = [
        record for record in caplog.records if getattr(record, "event", None) == "application_startup"
    ]
    assert len(startup_records) == 1
    startup_record = startup_records[0]
    assert startup_record.__dict__["startup_duration_ms"] >= 0
    assert startup_record.__dict__["process_started_at_ns"] > 0

    cold_records = [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_logging"
        and record.getMessage().startswith("Cold HTTP request:")
    ]
    assert len(cold_records) == 1
    cold_record = cold_records[0]
    assert cold_record.__dict__["cold_request"] is True
    assert cold_record.__dict__["process_request_number"] == 1
    assert cold_record.__dict__["startup_complete"] is True
    assert cold_record.__dict__["startup_duration_ms"] is not None
    assert len(cold_record.__dict__["request_id"]) == 32


def test_production_sanitization_removes_user_request_context() -> None:
    """Production sanitization removes private request identity and payload data.

    Args:
        None.

    Returns:
        None.
    """
    sanitized = sanitize_for_logging(
        {
            "cold_request": True,
            "process_started_at_ns": 1,
            "request_body": {"comic": "private"},
            "query_params": "token=secret",
            "session_id": "private-session",
            "user_id": 42,
            "client_host": "203.0.113.9",
        },
        "production",
    )

    assert sanitized == {"cold_request": True, "process_started_at_ns": 1}


def test_log_path_neutralizes_record_splitting_characters() -> None:
    """Request paths cannot inject carriage returns or new log lines.

    Args:
        None.

    Returns:
        None.
    """
    sanitized = _sanitize_log_path("/comics\r\nforged=true")

    assert sanitized == "/comics\\r\\nforged=true"
    assert "\r" not in sanitized
    assert "\n" not in sanitized
