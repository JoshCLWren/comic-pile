"""Security headers and targeted session-read diagnostics middleware."""

import logging
import os
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.performance_diagnostics import get_request_diagnostics

logger = logging.getLogger(__name__)


def _session_read_operation(path: str, method: str) -> str | None:
    """Classify current-session and History list reads.

    Args:
        path: Request URL path.
        method: HTTP request method.

    Returns:
        Stable operation name for instrumented reads, otherwise ``None``.
    """
    if method != "GET":
        return None

    normalized_path = path.rstrip("/")
    prefixes = ("/api/sessions", "/api/v1/sessions")
    for prefix in prefixes:
        if normalized_path == f"{prefix}/current":
            return "current-session"
        if normalized_path == prefix:
            return "history-list"
    return None


def _add_session_read_diagnostics(
    request: Request,
    response: Response,
    operation: str,
    total_ms: float,
) -> None:
    """Expose and log bounded read-pipeline timing and query-count evidence.

    Args:
        request: Completed HTTP request.
        response: Response receiving diagnostic headers.
        operation: Stable session-read operation name.
        total_ms: Total elapsed middleware time in milliseconds.
    """
    diagnostics = get_request_diagnostics()
    application_ms = max(
        total_ms - diagnostics.database_time_ms - diagnostics.cache_time_ms,
        0.0,
    )

    response.headers["X-Session-Read-Operation"] = operation
    response.headers["X-Session-Read-Total-Ms"] = f"{total_ms:.2f}"
    response.headers["X-Session-Read-App-Ms"] = f"{application_ms:.2f}"
    response.headers["X-Session-Read-DB-Ms"] = f"{diagnostics.database_time_ms:.2f}"
    response.headers["X-Session-Read-DB-Queries"] = str(diagnostics.database_queries)
    response.headers["X-Session-Read-Cache-Ms"] = f"{diagnostics.cache_time_ms:.2f}"
    response.headers["X-Session-Read-Cache-Calls"] = str(diagnostics.cache_calls)

    logger.warning(
        "Session read diagnostics: %s completed in %.2f ms",
        operation,
        total_ms,
        extra={
            "event": "session_read_diagnostics",
            "operation": operation,
            "path": request.url.path,
            "request_id": getattr(request.state, "request_id", None),
            "status_code": response.status_code,
            "total_time_ms": round(total_ms, 2),
            "application_time_ms": round(application_ms, 2),
            "database_time_ms": round(diagnostics.database_time_ms, 2),
            "database_queries": diagnostics.database_queries,
            "cache_time_ms": round(diagnostics.cache_time_ms, 2),
            "cache_calls": diagnostics.cache_calls,
            "cache_status": diagnostics.cache_status,
        },
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers and targeted read diagnostics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add security headers and session-read diagnostics to the response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response with security and optional diagnostics headers added.
        """
        operation = _session_read_operation(request.url.path, request.method)
        started_at = time.perf_counter()
        response = await call_next(request)
        total_ms = (time.perf_counter() - started_at) * 1000

        csp_header = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' https://fonts.googleapis.com; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-src 'none';"
        )
        response.headers["Content-Security-Policy"] = csp_header

        environment = os.getenv("APP_ENV", os.getenv("ENV", "development"))
        if environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        else:
            response.headers["Strict-Transport-Security"] = "max-age=300"

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if operation is not None and response.status_code < 500:
            _add_session_read_diagnostics(request, response, operation, total_ms)

        return response
