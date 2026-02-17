"""FastAPI application factory and configuration."""

import json
import logging
import os
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, analytics, auth, queue, rate, roll, session, snooze, thread, undo
from app.config import get_app_settings, get_database_settings
from app.database import Base, AsyncSessionLocal, get_db
from app.middleware import limiter

logger = logging.getLogger(__name__)

# Log database URL at startup (with password redacted)
_db_settings = get_database_settings()
_redacted_url = make_url(_db_settings.database_url).render_as_string(hide_password=True)
logger.info(f"Starting with DATABASE_URL: {_redacted_url}")

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app_settings = get_app_settings()

    if not logging.getLogger().hasHandlers():
        if os.getenv("APP_ENV") == "development" or os.getenv("ENV") == "development":
            logging.basicConfig(level=logging.DEBUG)

    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )

    # Register rate limiter (will be no-op in test environments)
    app.state.limiter = limiter
    if os.getenv("TEST_ENVIRONMENT") != "true":
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
        """Handle validation errors with detailed logging.

        Args:
            request: FastAPI request object.
            exc: Validation error that was raised.

        Returns:
            JSON response with 422 status code and validation errors.
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

    def _assert_production_frontend_assets() -> None:
        """Ensure required frontend artifacts exist in production.

        Raises:
            RuntimeError: If required built frontend artifacts are missing.
        """
        if app_settings.environment != "production":
            return

        spa_index = Path("static/react/index.html")
        assets_dir = Path("static/react/assets")
        has_js = any(assets_dir.glob("*.js")) if assets_dir.exists() else False
        has_css = any(assets_dir.glob("*.css")) if assets_dir.exists() else False

        if not spa_index.exists() or not assets_dir.exists() or not has_js or not has_css:
            raise RuntimeError(
                "Missing built frontend artifacts in production. "
                "Expected static/react/index.html and static/react/assets with JS/CSS files."
            )

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def api_not_found(path: str) -> JSONResponse:
        """Return a JSON 404 for unknown API routes.

        Args:
            path: API path that was not found.

        Returns:
            JSON response with 404 status code.
        """
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not Found"})

    # Mount static files. In production, artifact presence is enforced at startup.
    if app_settings.environment == "production":
        app.mount("/static", StaticFiles(directory="static"), name="static")
        app.mount("/assets", StaticFiles(directory="static/react/assets"), name="assets")
    else:
        if Path("static").exists():
            app.mount("/static", StaticFiles(directory="static"), name="static")
        if Path("static/react/assets").exists():
            app.mount("/assets", StaticFiles(directory="static/react/assets"), name="assets")

    @app.get("/vite.svg")
    async def serve_vite_svg():
        """Serve vite favicon.

        Returns:
            FileResponse with vite.svg file.
        """
        from fastapi.responses import FileResponse

        return FileResponse("static/vite.svg", media_type="image/svg+xml")

    def _serve_spa_index_response() -> Response:
        """Serve SPA index file when available, else return fallback HTML.

        Returns:
            FileResponse for the built SPA index, or fallback HTMLResponse in test environments.
        """
        from fastapi.responses import FileResponse, HTMLResponse

        spa_index = Path("static/react/index.html")
        cache_headers = {"Cache-Control": "no-store, no-cache, must-revalidate"}
        if spa_index.exists():
            return FileResponse(str(spa_index), headers=cache_headers)
        if app_settings.environment == "production":
            raise StarletteHTTPException(status_code=503, detail="Frontend assets unavailable")
        fallback_html = (
            "<!doctype html><html><body>"
            "<div id='root'></div>"
            "</body></html>"
        )
        return HTMLResponse(fallback_html, headers=cache_headers)

    @app.get("/")
    async def serve_root():
        """Serve React app at root URL.

        Returns:
            FileResponse with React index.html.
        """
        return _serve_spa_index_response()

    @app.get("/react")
    async def serve_react_redirect():
        """Redirect /react to / for consistent routing.

        Returns:
            RedirectResponse to root URL.
        """
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/", status_code=301)

    @app.get("/react/")
    async def serve_react_redirect_slash():
        """Redirect /react/ to / for consistent routing.

        Returns:
            RedirectResponse to root URL.
        """
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/", status_code=301)

    @app.get("/health", response_model=None)
    async def health_check(db: AsyncSession = Depends(get_db)) -> dict | JSONResponse:
        """Health check endpoint that verifies basic application functionality.

        Returns:
            JSON response with health status and database connection state.
        """
        from sqlalchemy import text

        try:
            await db.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except sqlalchemy_exc.DBAPIError as e:
            logger.error(f"Health check database connection failed: {e}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "unhealthy", "database": "disconnected", "error": str(e)},
            )

    @app.get("/{full_path:path}")
    async def serve_react_spa(full_path: str):
        """Serve the React SPA for non-API routes.

        The React app owns routing for paths like /rate, /queue, /history, etc.

        Args:
            full_path: The path to serve.

        Returns:
            FileResponse with React index.html.

        Raises:
            StarletteHTTPException: If path is blocked.
        """
        blocked_prefixes = ("api", "static", "assets", "debug")
        blocked_exact = {"health", "openapi.json", "docs", "redoc", "vite.svg"}

        if (
            full_path in blocked_exact
            or full_path in blocked_prefixes
            or any(full_path.startswith(prefix + "/") for prefix in blocked_prefixes)
        ):
            raise StarletteHTTPException(status_code=404, detail="Not Found")

        return _serve_spa_index_response()

    @app.on_event("startup")
    async def startup_event():
        """Initialize database on application startup.

        Attempts to connect to database and optionally creates tables
        in non-production environments.
        """
        import asyncio
        from sqlalchemy import text

        _assert_production_frontend_assets()

        max_retries = 3
        retry_delay = 1

        database_ready = False
        for attempt in range(1, max_retries + 1):
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(text("SELECT 1"))
                    database_ready = True
                    logger.info("Database connection established successfully")
                    break
            except sqlalchemy_exc.DBAPIError as e:
                # Catch database connection and execution errors (OperationalError, InterfaceError, etc.)
                logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error("All database connection attempts failed")

        if database_ready:
            if app_settings.environment == "production":
                logger.info("Production mode: Skipping table creation (migrations required)")
            else:
                try:
                    from app.database import async_engine

                    async with async_engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                    logger.info("Database tables created successfully")
                except sqlalchemy_exc.DBAPIError as e:
                    # Catch database errors during table creation (OperationalError, ProgrammingError, etc.)
                    logger.error(f"Failed to create database tables: {e}")
                    sys.exit(1)
        else:
            logger.warning("Skipping database initialization due to connection failure")

    return app


app = create_app()
