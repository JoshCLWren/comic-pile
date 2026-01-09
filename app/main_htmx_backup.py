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
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from app.api import admin, error_handler, queue, rate, retros, roll, session, tasks, thread, undo  # noqa: E402
from app.api.tasks import get_coordinator_data, health_router  # noqa: E402
from app.database import Base, engine, get_db  # noqa: E402
from app.middleware import limiter  # noqa: E402
from app.models import Event  # noqa: E402
from app.models import Session as SessionModel  # noqa: E402
from app.models import Thread  # noqa: E402

logger = logging.getLogger(__name__)


_thread_cache: dict[str, tuple[list, float]] = {}
_session_cache: dict[str, tuple[dict, float]] = {}


def get_threads_cached(db: Session) -> list:
    """Get threads from cache (30 second TTL)."""
    cache_key = "all_threads"
    now = time.time()
    if cache_key in _thread_cache and now - _thread_cache[cache_key][1] < 30:
        return _thread_cache[cache_key][0]
    from app.models import Thread

    threads = list(db.execute(select(Thread).order_by(Thread.queue_position)).scalars().all())
    _thread_cache[cache_key] = (threads, now)
    return threads


def get_current_session_cached(db: Session) -> dict | None:
    """Get current session from cache (10 second TTL)."""
    cache_key = "current_session"
    now = time.time()
    if cache_key in _session_cache and now - _session_cache[cache_key][1] < 10:
        return _session_cache[cache_key][0]
    from comic_pile.session import is_active

    active_sessions = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .all()
    )
    active_session = None
    for s in active_sessions:
        if is_active(s, db):
            active_session = s
            break
    if active_session:
        from app.schemas.thread import SessionResponse
        from comic_pile.session import get_current_die
        from sqlalchemy import func
        from app.models import Snapshot

        active_thread_data = session.get_active_thread(active_session, db)

        snapshot_count = (
            db.execute(
                select(func.count())
                .select_from(Snapshot)
                .where(Snapshot.session_id == active_session.id)
            ).scalar()
            or 0
        )

        response = SessionResponse(
            id=active_session.id,
            started_at=active_session.started_at,
            ended_at=active_session.ended_at,
            start_die=active_session.start_die,
            manual_die=active_session.manual_die,
            user_id=active_session.user_id,
            ladder_path=session.build_ladder_path(active_session, db),
            active_thread=active_thread_data,
            current_die=get_current_die(active_session.id, db),
            last_rolled_result=active_thread_data.get("last_rolled_result")
            if active_thread_data
            else None,
            has_restore_point=snapshot_count > 0,
            snapshot_count=snapshot_count,
        )
        _session_cache[cache_key] = (response.model_dump(), now)
        return response.model_dump()

        snapshot_count = (
            db.execute(
                select(func.count())
                .select_from(Snapshot)
                .where(Snapshot.session_id == active_session.id)
            ).scalar()
            or 0
        )

        response = SessionResponse(
            id=active_session.id,
            started_at=active_session.started_at,
            ended_at=active_session.ended_at,
            start_die=active_session.start_die,
            manual_die=active_session.manual_die,
            user_id=active_session.user_id,
            ladder_path=session.build_ladder_path(active_session, db),
            active_thread=active_thread_data,
            current_die=get_current_die(active_session.id, db),
            last_rolled_result=active_thread_data.get("last_rolled_result")
            if active_thread_data
            else None,
            has_restore_point=snapshot_count > 0,
            snapshot_count=snapshot_count,
        )
        _session_cache[cache_key] = (response.model_dump(), now)
        return response.model_dump()
    return None


def clear_cache() -> None:
    """Clear all caches on POST/PUT/DELETE operations."""
    _thread_cache.clear()
    _session_cache.clear()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    templates = Jinja2Templates(directory="app/templates", auto_reload=True)

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

        if exc.status_code == status.HTTP_404_NOT_FOUND:
            accept_header = request.headers.get("accept", "")
            if "text/html" in accept_header:
                return templates.TemplateResponse(
                    "404.html", {"request": request}, status_code=exc.status_code
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
    app.include_router(roll.router, prefix="/roll", tags=["roll"])
    app.include_router(rate.router, prefix="/rate", tags=["rate"])
    app.include_router(queue.router, prefix="/queue", tags=["queue"])
    app.include_router(session.router, tags=["session"])
    app.include_router(admin.router, tags=["admin"])
    app.include_router(tasks.router, prefix="/api", tags=["tasks"])
    app.include_router(retros.router, prefix="/api", tags=["retros"])
    app.include_router(health_router, prefix="/api")
    app.include_router(undo.router, prefix="/undo", tags=["undo"])

    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request, db: Session = Depends(get_db)):
        """Render roll page as default home page."""
        from comic_pile.dice_ladder import DICE_LADDER
        from comic_pile.session import get_current_die, get_or_create

        current_session = get_or_create(db, user_id=1)
        current_die = get_current_die(current_session.id, db) if current_session else 6
        if current_die not in DICE_LADDER:
            current_die = 6
        return templates.TemplateResponse(
            "roll.html", {"request": request, "current_die": current_die}
        )

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request, db: Session = Depends(get_db)):
        """Render session history page."""
        sessions = (
            db.execute(select(SessionModel).order_by(SessionModel.started_at.desc()).limit(50))
            .scalars()
            .all()
        )

        session_responses = []
        for s in sessions:
            ladder_path = session.build_ladder_path(s, db)
            active_thread = session.get_active_thread(s, db)

            events = (
                db.execute(
                    select(Event)
                    .where(Event.session_id == s.id)
                    .order_by(Event.timestamp.desc())
                    .limit(5)
                )
                .scalars()
                .all()
            )

            formatted_events = []
            for event in events:
                thread_title = None
                if event.type == "roll":
                    thread_id = event.selected_thread_id
                else:
                    thread_id = event.thread_id

                if thread_id:
                    thread = db.get(Thread, thread_id)
                    if thread:
                        thread_title = thread.title

                event_data = {
                    "id": event.id,
                    "type": event.type,
                    "timestamp": event.timestamp,
                    "thread_title": thread_title,
                }

                if event.type == "roll":
                    event_data.update(
                        {
                            "die": event.die,
                            "result": event.result,
                        }
                    )
                elif event.type == "rate":
                    event_data.update(
                        {
                            "rating": event.rating,
                            "issues_read": event.issues_read,
                        }
                    )

                formatted_events.append(event_data)

            session_responses.append(
                {
                    "id": s.id,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "ladder_path": ladder_path,
                    "active_thread": active_thread,
                    "recent_events": formatted_events,
                }
            )

        return templates.TemplateResponse(
            "history.html", {"request": request, "sessions": session_responses}
        )

    @app.get("/rate", response_class=HTMLResponse)
    async def rate_page(request: Request):
        """Render rating page."""
        return templates.TemplateResponse("rate.html", {"request": request})

    @app.get("/queue", response_class=HTMLResponse)
    async def queue_page(request: Request):
        """Render queue page."""
        return templates.TemplateResponse("queue.html", {"request": request})

    @app.get("/roll", response_class=HTMLResponse)
    async def roll_page(request: Request, db: Session = Depends(get_db)):
        """Render roll page."""
        from datetime import datetime, timedelta

        from comic_pile.dice_ladder import DICE_LADDER
        from comic_pile.session import get_current_die, get_or_create

        current_session = get_or_create(db, user_id=1)
        current_die = get_current_die(current_session.id, db) if current_session else 6
        if current_die not in DICE_LADDER:
            current_die = 6

        pending_html = ""
        if current_session and current_session.pending_thread_id:
            cutoff_time = datetime.now() - timedelta(hours=6)
            if (
                current_session.pending_thread_updated_at
                and current_session.pending_thread_updated_at >= cutoff_time
            ):
                from app.models import Thread

                pending_thread = db.get(Thread, current_session.pending_thread_id)
                if pending_thread:
                    pending_html = f"""
                    <div id="pending-thread-alert" class="mb-4 bg-yellow-50 border-2 border-yellow-300 rounded-lg p-4">
                        <div class="flex items-start justify-between">
                            <div class="flex-1">
                                <p class="text-yellow-800 font-medium mb-1">You were about to read:</p>
                                <p class="text-lg font-bold text-gray-900">{pending_thread.title}</p>
                                <p class="text-sm text-gray-600">{pending_thread.format}</p>
                            </div>
                            <button
                                hx-post="/roll/dismiss-pending"
                                hx-target="#pending-thread-alert"
                                hx-swap="outerHTML"
                                class="text-yellow-700 hover:text-yellow-900 text-2xl ml-2"
                                aria-label="Dismiss pending thread"
                            >
                                &times;
                            </button>
                        </div>
                    </div>
                    """

        return templates.TemplateResponse(
            "roll.html",
            {"request": request, "current_die": current_die, "pending_html": pending_html},
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        """Render settings page."""
        return templates.TemplateResponse("settings.html", {"request": request})

    @app.get("/tasks/coordinator", response_class=HTMLResponse)
    async def coordinator_page(request: Request, db: Session = Depends(get_db)):
        """Render task coordinator dashboard."""
        coordinator_data = get_coordinator_data(db)
        return templates.TemplateResponse(
            "coordinator.html", {"request": request, **coordinator_data.model_dump()}
        )

    @app.get("/tasks/analytics", response_class=HTMLResponse)
    async def analytics_page(request: Request, db: Session = Depends(get_db)):
        """Render task analytics dashboard."""
        from app.api.tasks import get_metrics

        metrics = get_metrics(db)
        return templates.TemplateResponse("analytics.html", {"request": request, **metrics})

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
