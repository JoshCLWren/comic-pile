"""Request logging, redaction, and lightweight performance diagnostics.

Provides helpers for safely reading and redacting request bodies before they
are written to logs. The HTTP middleware also emits request IDs, Server-Timing
metrics, cache outcomes, database query counts, slow-request logs, and the
existing error logs.
"""

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Request

from app.cache import cache
from app.performance_diagnostics import (
    begin_request_diagnostics,
    end_request_diagnostics,
    get_request_diagnostics,
    install_cache_instrumentation,
)

logger = logging.getLogger(__name__)

MAX_LOG_BODY_SIZE = 1000
_DEFAULT_SLOW_REQUEST_THRESHOLD_MS = 1000.0


def contains_sensitive_keys(body_json: dict | list) -> bool:
    """Check if body contains sensitive keys recursively.

    Args:
        body_json: JSON body to check (dict or list).

    Returns:
        True if sensitive keys found, False otherwise.
    """
    sensitive_keys = {"password", "secret", "token", "access_token", "refresh_token", "api_key"}

    if isinstance(body_json, dict):
        for key in body_json:
            if key in sensitive_keys:
                return True
        for value in body_json.values():
            if contains_sensitive_keys(value):
                return True
    elif isinstance(body_json, list):
        for item in body_json:
            if contains_sensitive_keys(item):
                return True
    return False


def is_auth_route(path: str) -> bool:
    """Check if path is an auth-related route.

    Args:
        path: Request path to check.

    Returns:
        True if path is auth-related, False otherwise.
    """
    auth_paths = ("/api/auth/", "/api/login", "/api/register", "/api/logout")
    return any(path.startswith(auth_path) for auth_path in auth_paths)


async def _safe_get_request_body(request: Request) -> str | dict | None:
    """Safely read and redact request body for logging.

    Args:
        request: FastAPI request object.

    Returns:
        Redacted body as string or dict, or None if not applicable.
    """
    try:
        if request.method not in ("POST", "PUT", "PATCH"):
            return None

        body = await request.body()
        if not body:
            return None

        if is_auth_route(request.url.path):
            content_type = request.headers.get("content-type", "unknown")
            return f"[AUTH ROUTE: {len(body)} bytes, {content_type}]"

        try:
            body_str = body.decode("utf-8")
            if len(body_str) <= MAX_LOG_BODY_SIZE:
                body_json = json.loads(body_str)
                if contains_sensitive_keys(body_json):
                    return "[REDACTED: contains sensitive data]"
                return body_json
            return f"[TRUNCATED: {len(body_str)} bytes]"
        except (json.JSONDecodeError, UnicodeDecodeError):
            if len(body) <= MAX_LOG_BODY_SIZE:
                return body.decode("utf-8", errors="replace")
            return f"[BINARY DATA: {len(body)} bytes]"
    except (OSError, RuntimeError, TimeoutError) as e:
        logger.debug(f"Failed to read request body: {e}")
        return None


def redact_headers(headers: dict) -> dict:
    """Redact sensitive headers from logging.

    Args:
        headers: Dictionary of HTTP headers.

    Returns:
        Dictionary with sensitive headers redacted.
    """
    sensitive_headers = {"authorization", "cookie", "set-cookie"}
    redacted = {}
    for key, value in headers.items():
        if key.lower() in sensitive_headers:
            redacted[key] = f"[REDACTED: {key}]"
        else:
            redacted[key] = value
    return redacted


def sanitize_for_logging(log_data: dict[str, object], environment: str) -> dict[str, object]:
    """Trim request context from logs in production and staging.

    In production and staging, avoid logging request bodies, query params, and session identifiers.

    Args:
        log_data: Log payload.
        environment: Current application environment.

    Returns:
        Possibly-trimmed log payload.
    """
    if environment not in ("production", "staging"):
        return log_data

    trimmed = dict(log_data)
    for key in ("request_body", "query_params", "session_id", "body"):
        trimmed.pop(key, None)
    return trimmed


def _slow_request_threshold_ms() -> float:
    """Resolve the threshold for structured slow-request warnings."""
    raw_value = os.getenv("SLOW_REQUEST_THRESHOLD_MS")
    if raw_value is None:
        return _DEFAULT_SLOW_REQUEST_THRESHOLD_MS

    try:
        parsed = float(raw_value)
    except ValueError:
        return _DEFAULT_SLOW_REQUEST_THRESHOLD_MS
    return parsed if parsed > 0 else _DEFAULT_SLOW_REQUEST_THRESHOLD_MS


def _server_timing_header(total_ms: float) -> str:
    """Build the Server-Timing header from the active diagnostics snapshot."""
    diagnostics = get_request_diagnostics()
    metrics = [f"app;dur={total_ms:.2f}"]

    if diagnostics.database_queries:
        metrics.append(
            f'db;dur={diagnostics.database_time_ms:.2f};desc="{diagnostics.database_queries} queries"'
        )
    if diagnostics.cache_calls:
        metrics.append(
            f'cache;dur={diagnostics.cache_time_ms:.2f};desc="{diagnostics.cache_status}"'
        )
    for name, phase in diagnostics.phases.items():
        metrics.append(f'{name};dur={phase.duration_ms:.2f};desc="{phase.query_count} queries"')
    return ", ".join(metrics)


def add_request_logging_middleware(app: FastAPI, environment: str) -> None:
    """Register request diagnostics and error logging middleware.

    Args:
        app: FastAPI application instance to wire the middleware onto.
        environment: Current application environment.
    """
    install_cache_instrumentation(cache)

    @app.middleware("http")
    async def log_errors_middleware(request: Request, call_next):
        """Add diagnostics headers and log slow or failed requests."""
        started_at = time.perf_counter()
        request_id = uuid.uuid4().hex
        diagnostics_token = begin_request_diagnostics()
        request.state.request_id = request_id

        try:
            if environment != "production":
                body = await _safe_get_request_body(request)
                if body:
                    request.state.request_body = body

            response = await call_next(request)
            process_time_ms = (time.perf_counter() - started_at) * 1000
            status_code = response.status_code
            diagnostics = get_request_diagnostics()

            response.headers["X-Request-ID"] = request_id
            response.headers["X-App-Cache"] = diagnostics.cache_status
            response.headers["X-App-DB-Queries"] = str(diagnostics.database_queries)
            response.headers["Server-Timing"] = _server_timing_header(process_time_ms)

            log_data = {
                "timestamp": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query_params": str(request.url.query) if request.url.query else None,
                "status_code": status_code,
                "process_time_ms": round(process_time_ms, 2),
                "database_queries": diagnostics.database_queries,
                "database_time_ms": round(diagnostics.database_time_ms, 2),
                "cache_status": diagnostics.cache_status,
                "cache_calls": diagnostics.cache_calls,
                "cache_time_ms": round(diagnostics.cache_time_ms, 2),
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "headers": redact_headers(dict(request.headers)),
            }

            if diagnostics.phases:
                log_data["phase_timings_ms"] = {
                    name: round(phase.duration_ms, 2) for name, phase in diagnostics.phases.items()
                }
                log_data["phase_query_counts"] = {
                    name: phase.query_count for name, phase in diagnostics.phases.items()
                }

            if hasattr(request.state, "request_body"):
                log_data["request_body"] = request.state.request_body
            if hasattr(request.state, "user_id"):
                log_data["user_id"] = request.state.user_id
            if hasattr(request.state, "session_id"):
                log_data["session_id"] = request.state.session_id

            log_data = sanitize_for_logging(log_data, environment)

            if status_code >= 500:
                logger.error(
                    f"API Error: {request.method} {request.url.path} - {status_code}",
                    extra={**log_data, "level": "ERROR"},
                )
            elif status_code >= 400:
                logger.warning(
                    f"Client Error: {request.method} {request.url.path} - {status_code}",
                    extra={**log_data, "level": "WARNING"},
                )
            elif process_time_ms >= _slow_request_threshold_ms():
                logger.warning(
                    "Slow HTTP request: %s %s completed in %.2f ms",
                    request.method,
                    request.url.path,
                    process_time_ms,
                    extra={**log_data, "level": "WARNING"},
                )

            return response
        finally:
            end_request_diagnostics(diagnostics_token)
