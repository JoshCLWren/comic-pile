"""FastAPI application factory and configuration."""

import json
import logging
import os
import subprocess
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, analytics, auth, queue, rate, roll, session, snooze, thread, undo
from app.config import get_app_settings
from app.database import Base, engine, SessionLocal
from app.middleware import limiter

logger = logging.getLogger(__name__)

MAX_LOG_BODY_SIZE = 1000


def contains_sensitive_keys(body_json: dict | list) -> bool:
    """Check if body contains sensitive keys recursively."""
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
    """Check if path is an auth-related route."""
    auth_paths = ("/api/auth/", "/api/login", "/api/register", "/api/logout")
    return any(path.startswith(auth_path) for auth_path in auth_paths)


async def _safe_get_request_body(request: Request) -> str | dict | None:
    """Safely read and redact request body for logging."""
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
    except Exception as e:
        logger.debug(f"Failed to read request body: {e}")
        return None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app_settings = get_app_settings()

    if not logging.getLogger().hasHandlers():
        if os.getenv("APP_ENV") == "development" or os.getenv("ENV") == "development":
            logging.basicConfig(level=logging.DEBUG)

    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        cast(Callable[[Request, Any], Awaitable[Response]], _rate_limit_exceeded_handler),
    )

    app_settings.validate_production_cors()
    cors_origins = app_settings.cors_origins_list

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def redact_headers(headers: dict) -> dict:
        """Redact sensitive headers from logging."""
        sensitive_headers = {"authorization", "cookie", "set-cookie"}
        redacted = {}
        for key, value in headers.items():
            if key.lower() in sensitive_headers:
                redacted[key] = f"[REDACTED: {key}]"
            else:
                redacted[key] = value
        return redacted

    @app.middleware("http")
    async def log_errors_middleware(request: Request, call_next):
        """Log all requests with status codes >= 400."""
        start_time = time.time()

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

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions with full stacktrace logging."""
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

        body = await _safe_get_request_body(request)
        if body:
            error_data["request_body"] = body

        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

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
        """Handle HTTP exceptions with contextual logging."""
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

        body = await _safe_get_request_body(request)
        if body:
            error_data["request_body"] = body
        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

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
        """Handle validation errors with detailed logging."""
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

        error_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.url.query) if request.url.query else None,
            "status_code": 422,
            "validation_errors": errors,
            "body": exc.body,
            "client_host": request.client.host if request.client else None,
            "level": "WARNING",
        }

        if hasattr(request.state, "request_body"):
            error_data["request_body"] = request.state.request_body
        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

        logger.warning(
            f"Validation Error: {errors}",
            extra=error_data,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Validation failed",
                "errors": errors,
                "body": exc.body,
            },
        )

    app.include_router(roll.router, prefix="/api/roll", tags=["roll"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(analytics.router, prefix="/api", tags=["analytics"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(thread.router, prefix="/api/threads", tags=["threads"])
    app.include_router(rate.router, prefix="/api/rate", tags=["rate"])
    app.include_router(queue.router, prefix="/api/queue", tags=["queue"])
    app.include_router(session.router, prefix="/api", tags=["session"])
    app.include_router(snooze.router, prefix="/api/snooze", tags=["snooze"])
    app.include_router(undo.router, prefix="/api/undo", tags=["undo"])

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def api_not_found(path: str) -> JSONResponse:
        """Return a JSON 404 for unknown API routes."""
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not Found"})

    # Mount static files only if directories exist (for CI/testing environments)
    if Path("static").exists():
        app.mount("/static", StaticFiles(directory="static"), name="static")

    if Path("static/react/assets").exists():
        app.mount("/assets", StaticFiles(directory="static/react/assets"), name="assets")

    @app.get("/vite.svg")
    async def serve_vite_svg():
        """Serve vite favicon."""
        from fastapi.responses import FileResponse

        return FileResponse("static/vite.svg", media_type="image/svg+xml")

    @app.get("/")
    async def serve_root():
        """Serve React app at root URL."""
        from fastapi.responses import FileResponse

        return FileResponse("static/react/index.html")

    @app.get("/react")
    async def serve_react_redirect():
        """Redirect /react to / for consistent routing."""
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/", status_code=301)

    @app.get("/react/")
    async def serve_react_redirect_slash():
        """Redirect /react/ to / for consistent routing."""
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/", status_code=301)

    @app.get("/health")
    async def health_check():
        """Health check endpoint that verifies basic application functionality."""
        from sqlalchemy import text

        from app.config import get_database_settings

        # Check if DATABASE_URL is set (validated at config load time)
        try:
            get_database_settings()
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "unhealthy",
                    "database": "not_configured",
                    "error": "DATABASE_URL not set",
                },
            )

        # Try to connect to database
        try:
            db = SessionLocal()
            try:
                db.execute(text("SELECT 1"))
                return {"status": "healthy", "database": "connected"}
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Health check database connection failed: {e}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "unhealthy", "database": "disconnected", "error": str(e)},
            )

    @app.get("/{full_path:path}")
    async def serve_react_spa(full_path: str):
        """Serve the React SPA for non-API routes.

        The React app owns routing for paths like /rate, /queue, /history, etc.
        """
        from fastapi.responses import FileResponse

        blocked_prefixes = ("api", "static", "assets", "debug")
        blocked_exact = {"health", "openapi.json", "docs", "redoc", "vite.svg"}

        if (
            full_path in blocked_exact
            or full_path in blocked_prefixes
            or any(full_path.startswith(prefix + "/") for prefix in blocked_prefixes)
        ):
            raise StarletteHTTPException(status_code=404, detail="Not Found")

        return FileResponse("static/react/index.html")

    @app.on_event("startup")
    async def startup_event():
        """Initialize database on application startup."""
        import time
        from sqlalchemy import text

        max_retries = 5
        retry_delay = 5  # seconds

        database_ready = False
        for attempt in range(1, max_retries + 1):
            try:
                db = SessionLocal()
                try:
                    db.execute(text("SELECT 1"))
                    database_ready = True
                    logger.info("Database connection established successfully")
                    break
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error("All database connection attempts failed")

        if database_ready:
            if app_settings.environment == "production":
                logger.info("Production mode: Skipping table creation (migrations required)")
            else:
                try:
                    Base.metadata.create_all(bind=engine)
                    logger.info("Database tables created successfully")
                except Exception as e:
                    logger.error(f"Failed to create database tables: {e}")

            if app_settings.auto_backup_enabled:
                try:
                    logger.info("Starting automatic database backup...")
                    result = subprocess.run(
                        ["python", "-m", "scripts.backup_database"],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if result.returncode == 0:
                        logger.info(f"Database backup completed:\n{result.stdout}")
                    else:
                        logger.warning(f"Database backup warning:\n{result.stderr}")
                except subprocess.TimeoutExpired:
                    logger.error("Database backup timed out after 60 seconds")
                except Exception as backup_error:
                    logger.error(f"Database backup failed: {backup_error}")
            else:
                logger.info("Automatic backup disabled (AUTO_BACKUP_ENABLED=false)")
        else:
            logger.warning("Skipping database initialization and backups due to connection failure")

    return app


app = create_app()
