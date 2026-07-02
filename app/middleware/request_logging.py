"""Request logging and request-body redaction middleware.

Provides helpers for safely reading and redacting request bodies before they
are written to logs, plus the error-only HTTP middleware that records every
request with a status code >= 400.
"""

import json
import logging
import time
from datetime import UTC, datetime

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

MAX_LOG_BODY_SIZE = 1000


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
        # Catch I/O errors (body already consumed, network issues), RuntimeError from Starlette, and timeouts
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

    # Avoid leaking potentially sensitive request context.
    trimmed = dict(log_data)
    for key in ("request_body", "query_params", "session_id", "body"):
        trimmed.pop(key, None)
    return trimmed


def add_request_logging_middleware(app: FastAPI, environment: str) -> None:
    """Register the error-only request logging middleware on the app.

    The middleware records every request whose response status code is >= 400,
    attaching redacted request context (body, headers, query params) in
    non-production environments.

    Args:
        app: FastAPI application instance to wire the middleware onto.
        environment: Current application environment.
    """

    @app.middleware("http")
    async def log_errors_middleware(request: Request, call_next):
        """Log all requests with status codes >= 400.

        Args:
            request: FastAPI request object.
            call_next: Next middleware/route handler.

        Returns:
            HTTP response from the next handler.
        """
        start_time = time.time()

        if environment != "production":
            body = await _safe_get_request_body(request)
            if body:
                request.state.request_body = body

        response = await call_next(request)
        process_time = time.time() - start_time
        status_code = response.status_code

        if status_code >= 400:
            log_data = {
                "timestamp": datetime.now(UTC).isoformat(),
                "method": request.method,
                "path": request.url.path,
                "query_params": str(request.url.query) if request.url.query else None,
                "status_code": status_code,
                "process_time_ms": round(process_time * 1000, 2),
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "headers": redact_headers(dict(request.headers)),
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
            else:
                logger.warning(
                    f"Client Error: {request.method} {request.url.path} - {status_code}",
                    extra={**log_data, "level": "WARNING"},
                )

        return response
