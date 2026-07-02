"""FastAPI exception handlers with environment-aware error logging."""

import logging
import traceback
from datetime import UTC, datetime

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import AppSettings
from app.middleware.request_logging import (
    _safe_get_request_body,
    redact_headers,
    sanitize_for_logging,
)

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI, app_settings: AppSettings) -> None:
    """Register global, HTTP, and validation exception handlers on the app.

    Args:
        app: FastAPI application instance.
        app_settings: Application settings used for environment-aware sanitization.
    """
    environment = app_settings.environment

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions with full stacktrace logging.

        Args:
            request: FastAPI request object.
            exc: Exception that was raised.

        Returns:
            JSON response with 500 status code.
        """
        error_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.url.query) if request.url.query else None,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "stacktrace": traceback.format_exc(),
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "headers": redact_headers(dict(request.headers)),
            "level": "ERROR",
        }

        if environment != "production":
            body = await _safe_get_request_body(request)
            if body:
                error_data["request_body"] = body

        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

        error_data = sanitize_for_logging(error_data, environment)

        logger.error(
            f"Unhandled Exception: {type(exc).__name__}",
            extra=error_data,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Handle HTTP exceptions with contextual logging.

        Args:
            request: FastAPI request object.
            exc: HTTP exception that was raised.

        Returns:
            JSON response with exception status code.
        """
        error_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.url.query) if request.url.query else None,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "headers": redact_headers(dict(request.headers)),
        }

        if environment != "production":
            body = await _safe_get_request_body(request)
            if body:
                error_data["request_body"] = body
        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

        error_data = sanitize_for_logging(error_data, environment)

        if exc.status_code >= 500:
            error_data["level"] = "ERROR"
            logger.error(
                f"HTTP Exception: {exc.status_code} - {exc.detail}",
                extra=error_data,
            )
        elif exc.status_code >= 400:
            error_data["level"] = "WARNING"
            logger.warning(
                f"HTTP Exception: {exc.status_code} - {exc.detail}",
                extra=error_data,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle validation errors with environment-aware sanitization.

        In production: Returns generic error messages to prevent information disclosure.
        In development/test: Returns detailed error messages for debugging.

        Args:
            request: FastAPI request object.
            exc: Validation error that was raised.

        Returns:
            JSON response with 422 status code and sanitized validation errors.
        """
        errors = []
        for error in exc.errors():
            field_path = ".".join(str(loc) for loc in error["loc"])
            errors.append(
                {
                    "field": field_path,
                    "message": error["msg"],
                    "type": error["type"],
                }
            )

        # Convert exc.body to a JSON-serializable format for logging
        # FormData objects are not directly JSON serializable
        body_for_log: object
        if hasattr(exc.body, "__class__") and exc.body.__class__.__name__ == "FormData":
            body_for_log = {
                k: v if isinstance(v, str) else f"<{type(v).__name__}>"
                for k, v in exc.body.multi_items()
            }
        else:
            body_for_log = exc.body

        error_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.url.query) if request.url.query else None,
            "status_code": 422,
            "validation_errors": errors,
            "body": body_for_log,
            "client_host": request.client.host if request.client else None,
            "level": "WARNING",
        }

        if hasattr(request.state, "request_body"):
            error_data["request_body"] = request.state.request_body
        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

        error_data = sanitize_for_logging(error_data, environment)

        logger.warning(
            f"Validation Error: {errors}",
            extra=error_data,
        )

        if environment == "production":
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "detail": "Validation failed",
                },
            )

        # Convert exc.body to a JSON-serializable format
        # FormData objects are not directly JSON serializable
        body_content: object
        if hasattr(exc.body, "__class__") and exc.body.__class__.__name__ == "FormData":
            body_content = {
                k: v if isinstance(v, str) else f"<{type(v).__name__}>"
                for k, v in exc.body.multi_items()
            }
        else:
            body_content = exc.body

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Validation failed",
                "errors": errors,
                "body": body_content,
            },
        )
