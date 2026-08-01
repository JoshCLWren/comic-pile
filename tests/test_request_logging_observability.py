"""Regression coverage for production request observability.

Issue #678: production was missing ``Server-Timing`` on Vercel (stripped by the
platform proxy for container deployments) and no structured slow-request
warnings were reaching deployment logs because the production default root log
level (``ERROR``) suppressed WARNING-level records.
"""

import asyncio
import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import _configure_logging, _default_log_level, _resolve_log_level
from app.middleware.request_logging import add_request_logging_middleware


def test_production_default_log_level_does_not_suppress_warnings() -> None:
    """Production should default to WARNING so slow-request logs are emitted."""
    assert _default_log_level("production") == logging.WARNING


def test_default_log_levels_match_environment_intent() -> None:
    """Each environment should retain its documented default verbosity."""
    assert _default_log_level("staging") == logging.WARNING
    assert _default_log_level("development") == logging.DEBUG
    assert _default_log_level("test") == logging.WARNING
    assert _default_log_level("unknown-environment") == logging.WARNING


def test_production_log_level_resolution_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production without LOG_LEVEL resolves to WARNING after the fix."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert _resolve_log_level("production") == logging.WARNING


def test_log_level_override_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit LOG_LEVEL should override the production default."""
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert _resolve_log_level("production") == logging.ERROR


def test_invalid_log_level_falls_back_to_environment_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognized LOG_LEVEL should fall back to the environment default."""
    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    assert _resolve_log_level("production") == logging.WARNING


def test_configure_logging_sets_production_level_when_no_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uvicorn leaves the root logger handlerless, so the production level applies."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    monkeypatch.setattr(root, "hasHandlers", lambda: False)
    try:
        root.handlers.clear()
        _configure_logging("production")
        assert root.level == logging.WARNING
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def _find_slow_request_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_logging"
        and record.getMessage().startswith("Slow HTTP request:")
    ]


@pytest.mark.asyncio
async def test_middleware_emits_structured_slow_request_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Requests past the threshold should produce a WARNING with diagnostics extras."""
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "1")
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/slow")
    async def slow_route() -> dict[str, str]:
        """Return after sleeping well past the configured threshold."""
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/slow")
        assert response.status_code == 200

    records = _find_slow_request_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert "GET /slow completed in" in record.getMessage()
    assert len(record.__dict__["request_id"]) == 32
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["path"] == "/slow"
    assert record.__dict__["status_code"] == 200
    assert record.__dict__["database_queries"] == 0


@pytest.mark.asyncio
async def test_middleware_does_not_warn_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Requests under the threshold should not emit a slow-request warning."""
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "100000")
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/fast")
    async def fast_route() -> dict[str, str]:
        """Return immediately."""
        return {"status": "ok"}

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/fast")
        assert response.status_code == 200

    assert _find_slow_request_records(caplog) == []


@pytest.mark.asyncio
async def test_middleware_emits_structured_client_error_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """4xx responses should produce a WARNING with Client Error message."""
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/existing")
    async def existing_route() -> dict[str, str]:
        """Return a normal response."""
        return {"status": "ok"}

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/nonexistent")
        assert response.status_code == 404

    client_error_records = [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_logging"
        and record.getMessage().startswith("Client Error:")
    ]
    assert len(client_error_records) == 1
    record = client_error_records[0]
    assert record.levelno == logging.WARNING
    assert "GET /nonexistent - 404" in record.getMessage()
