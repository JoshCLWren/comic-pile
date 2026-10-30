"""Regression coverage for production request observability.

Issue #678: production was missing ``Server-Timing`` on Vercel (stripped by the
platform proxy for container deployments) and no structured slow-request
warnings were reaching deployment logs because the production default root log
level (``ERROR``) suppressed WARNING-level records.
"""

import asyncio
import logging
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import (
    _DiagnosticFieldsFilter,
    _configure_logging,
    _default_log_level,
    _resolve_log_level,
)
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


def _diagnostic_filter(handler: logging.Handler) -> _DiagnosticFieldsFilter:
    """Return the diagnostic filter installed on ``handler``."""
    for handler_filter in handler.filters:
        if isinstance(handler_filter, _DiagnosticFieldsFilter):
            return handler_filter
    raise AssertionError("diagnostic filter was not installed on the log handler")


def _build_diagnostic_record() -> logging.LogRecord:
    """Build a request log record carrying the production diagnostic extras."""
    record = logging.LogRecord(
        name="app.middleware.request_logging",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="API Error: GET /slow - 500",
        args=(),
        exc_info=None,
    )
    record.request_id = "abcdef0123456789abcdef0123456789"
    record.method = "GET"
    record.path = "/slow"
    record.status_code = 500
    record.process_time_ms = 123.45
    record.cpu_time_ms = 67.89
    record.database_queries = 3
    record.database_time_ms = 45.6
    record.cold_request = False
    record.deployment_id = "dep_abc123"
    record.event = "performance_budget_warning"
    return record


def test_configure_logging_prints_diagnostic_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured root handler emits structured diagnostic fields in log text.

    Regression test for Greptile finding G1 on PR #4334: basicConfig without a
    formatter dropped the ``extra`` fields (``cpu_time_ms``, ``request_id``,
    ``database_queries``, ...) so operators could not collect them from logs.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    monkeypatch.setattr(root, "hasHandlers", lambda: False)
    try:
        root.handlers.clear()
        _configure_logging("production")
        handler = root.handlers[0]
        record = _build_diagnostic_record()
        _diagnostic_filter(handler).filter(record)
        formatted = handler.format(record)
        assert "API Error: GET /slow - 500" in formatted
        assert "cpu_time_ms=67.89" in formatted
        assert "request_id='abcdef0123456789abcdef0123456789'" in formatted
        assert "database_queries=3" in formatted
        assert "process_time_ms=123.45" in formatted
        assert "cold_request=False" in formatted
        assert "deployment_id='dep_abc123'" in formatted
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def test_configure_logging_keeps_platform_handler_and_emits_diagnostic_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-installed root handler keeps its formatter yet still prints extras.

    A hosting platform may configure root logging before the application
    imports. The diagnostic filter must attach to that handler instead of
    returning early and silently dropping ``cpu_time_ms`` and friends.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    platform_handler = logging.StreamHandler()
    platform_format = logging.Formatter("%(levelname)s %(message)s")
    platform_handler.setFormatter(platform_format)
    monkeypatch.setattr(root, "hasHandlers", lambda: True)
    try:
        root.handlers[:] = [platform_handler]
        _configure_logging("production")
        assert platform_handler.formatter is platform_format
        assert len(platform_handler.filters) == 1
        record = _build_diagnostic_record()
        _diagnostic_filter(platform_handler).filter(record)
        formatted = platform_handler.format(record)
        assert formatted.startswith("WARNING API Error: GET /slow - 500")
        assert "cpu_time_ms=67.89" in formatted
        assert "database_queries=3" in formatted

        # A record passed through more than one filtered handler is not doubled.
        _diagnostic_filter(platform_handler).filter(record)
        reformatted = platform_handler.format(record)
        assert reformatted.count("cpu_time_ms=67.89") == 1
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def _find_performance_warning_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_logging"
        and record.getMessage().startswith("Performance warning:")
    ]


@pytest.mark.asyncio
async def test_middleware_emits_structured_performance_warning(
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

    records = _find_performance_warning_records(caplog)
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
async def test_middleware_reports_process_cpu_time_without_mislabeling_wall_time(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CPU time comes from process_time and is never named as wall time."""
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "1")
    readings = iter([100.0, 100.25])
    monkeypatch.setattr(time, "process_time", lambda: next(readings, 100.25))
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/cpu")
    async def cpu_route() -> dict[str, str]:
        """Return after a short sleep so the request crosses the threshold."""
        await asyncio.sleep(0.01)
        return {"status": "ok"}

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/cpu")
        assert response.status_code == 200

    records = _find_performance_warning_records(caplog)
    assert len(records) == 1
    extras = records[0].__dict__
    assert extras["cpu_time_ms"] == 250.0
    assert "wall_time_ms" not in extras
    assert extras["process_time_ms"] >= 0.0


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

    assert _find_performance_warning_records(caplog) == []


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
