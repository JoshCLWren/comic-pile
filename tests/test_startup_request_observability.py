"""Integration coverage for startup and first-request observability."""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.request_logging import add_request_logging_middleware
from app.startup_diagnostics import reset_startup_diagnostics_for_test


@pytest.mark.asyncio
async def test_first_request_is_correlated_with_startup_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Startup and the first HTTP request share safe process-level timing context."""
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "100000")
    reset_startup_diagnostics_for_test()

    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/fast")
    async def fast_route() -> dict[str, str]:
        return {"status": "ok"}

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/fast")
            second = await client.get("/fast")

    assert first.headers["X-App-Cold-Request"] == "1"
    assert second.headers["X-App-Cold-Request"] == "0"

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
    """Startup fields survive production sanitization without retaining private request data."""
    from app.middleware.request_logging import sanitize_for_logging

    sanitized = sanitize_for_logging(
        {
            "cold_request": True,
            "process_started_at_ns": 1,
            "request_body": {"comic": "private"},
            "query_params": "token=secret",
            "session_id": "private-session",
        },
        "production",
    )

    assert sanitized == {"cold_request": True, "process_started_at_ns": 1}
