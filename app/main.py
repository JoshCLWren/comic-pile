"""FastAPI application factory and configuration."""

import json
import logging
import os
import subprocess
import time
import traceback
from datetime import UTC, datetime

from dotenv import load_dotenv  # noqa: E402
from fastapi import Depends, FastAPI, Request, status  # noqa: E402

load_dotenv()
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from app.api import admin, error_handler, queue, rate, retros, roll, session, tasks, thread, undo  # noqa: E402
from app.api.tasks import health_router  # noqa: E402
from app.database import Base, engine, get_db  # noqa: E402
from app.models.session import Session as SessionModel  # noqa: E402
from app.middleware import limiter  # noqa: E402

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_errors_middleware(request: Request, call_next):
        """Log all requests with status codes >= 400."""
        start_time = time.time()

        try:
            if request.method in ("POST", "PUT", "PATCH"):
                body = await request.body()
                if body:
                    try:
                        body_str = body.decode("utf-8")
                        if len(body_str) <= 1000:
                            body_json = json.loads(body_str)
                            if "password" in body_json or "secret" in body_json:
                                request.state.request_body = "[REDACTED: contains sensitive data]"
                            else:
                                request.state.request_body = body_json
                        else:
                            request.state.request_body = f"[TRUNCATED: {len(body_str)} bytes]"
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        if len(body) <= 1000:
                            request.state.request_body = body.decode("utf-8", errors="replace")
                        else:
                            request.state.request_body = f"[BINARY DATA: {len(body)} bytes]"
        except Exception:
            pass

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
            "level": "ERROR",
        }

        try:
            if request.method in ("POST", "PUT", "PATCH"):
                body = await request.body()
                if body:
                    try:
                        body_str = body.decode("utf-8")
                        if len(body_str) <= 1000:
                            body_json = json.loads(body_str)
                            if "password" in body_json or "secret" in body_json:
                                error_data["request_body"] = "[REDACTED: contains sensitive data]"
                            else:
                                error_data["request_body"] = body_json
                        else:
                            error_data["request_body"] = f"[TRUNCATED: {len(body_str)} bytes]"
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        if len(body) <= 1000:
                            error_data["request_body"] = body.decode("utf-8", errors="replace")
                        else:
                            error_data["request_body"] = f"[BINARY DATA: {len(body)} bytes]"
        except Exception:
            pass

        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

        error_handler.handle_5xx_error(exc, request)

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
        }

        if hasattr(request.state, "request_body"):
            error_data["request_body"] = request.state.request_body
        if hasattr(request.state, "user_id"):
            error_data["user_id"] = request.state.user_id
        if hasattr(request.state, "session_id"):
            error_data["session_id"] = request.state.session_id

        if exc.status_code >= 500:
            error_data["level"] = "ERROR"
            mock_exc = Exception(f"HTTP {exc.status_code}: {exc.detail}")
            error_handler.handle_5xx_error(mock_exc, request)
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

    app.include_router(thread.router, prefix="/threads", tags=["threads"])
    app.include_router(roll.router, prefix="/api/roll", tags=["roll"])
    app.include_router(rate.router, prefix="/rate", tags=["rate"])
    app.include_router(queue.router, prefix="/queue", tags=["queue"])
    app.include_router(session.router, tags=["session"])
    app.include_router(admin.router, tags=["admin"])
    app.include_router(tasks.router, prefix="/api", tags=["tasks"])
    app.include_router(retros.router, prefix="/api", tags=["retros"])
    app.include_router(health_router, prefix="/api")
    app.include_router(undo.router, prefix="/undo", tags=["undo"])

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/react", StaticFiles(directory="static/react", html=True), name="react")
    app.mount("/", StaticFiles(directory="static/react", html=True), name="root")

    @app.get("/health")
    async def health_check(db: Session = Depends(get_db)):
        """Health check endpoint that verifies database connectivity."""
        try:
            db.execute(select(SessionModel).limit(1))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "unhealthy", "database": "disconnected", "error": str(e)},
            )

    @app.get("/debug/5xx-stats")
    async def get_5xx_error_stats():
        """Debug endpoint to show 5xx error statistics."""
        return error_handler.get_error_stats()

    @app.get("/debug/trigger-500")
    async def trigger_500_error():
        """Debug endpoint to trigger a 500 error for testing."""
        raise Exception("OperationalError: test database connection failed")

    @app.on_event("startup")
    async def startup_event():
        """Initialize database on application startup."""
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully")

            backup_enabled = os.getenv("AUTO_BACKUP_ENABLED", "true").lower() == "true"
            if backup_enabled:
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

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    return app


app = create_app()
