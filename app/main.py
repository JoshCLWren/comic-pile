"""FastAPI application factory and configuration."""

import asyncio
import logging
import os
import secrets
from pathlib import Path
from typing import cast

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
from starlette.responses import Response as StarletteResponse
from starlette.types import Scope
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cache import cache
from app.config import get_app_settings, get_database_settings, get_redis_settings
from app.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    is_csrf_protected_request,
    log_csrf_rejection,
)
from app.database import get_db
from app.exception_handlers import register_exception_handlers
from app.lifecycle import init_database
from app.middleware import limiter, SecurityHeadersMiddleware
from app.middleware.performance import PerformanceMiddleware, compute_startup_duration
from app.middleware.request_logging import add_request_logging_middleware
from app.safe_logging import safe_connection_metadata

logger = logging.getLogger(__name__)


def _default_log_level(environment: str) -> int:
    """Resolve the default root log level for an environment.

    Production defaults to WARNING so structured slow-request and client-error
    warnings reach deployment logs. Set ``LOG_LEVEL`` to raise or lower it.

    Args:
        environment: Current application environment.

    Returns:
        The default root logging level for the environment.
    """
    env_level_map: dict[str, int] = {
        "production": logging.WARNING,
        "staging": logging.WARNING,
        "development": logging.DEBUG,
        "test": logging.WARNING,
    }
    return env_level_map.get(environment, logging.WARNING)


def _resolve_log_level(environment: str) -> int:
    """Resolve the effective root log level, honoring a ``LOG_LEVEL`` override.

    Args:
        environment: Current application environment.

    Returns:
        The root logging level to configure.
    """
    requested_level = os.getenv("LOG_LEVEL")
    if requested_level:
        return logging.getLevelNamesMapping().get(
            requested_level.upper(),
            _default_log_level(environment),
        )
    return _default_log_level(environment)


def _configure_logging(environment: str) -> None:
    """Configure root logging unless a handler is already installed.

    Uvicorn leaves the root logger without handlers, so this path runs in
    production. ``basicConfig`` is a no-op when handlers already exist.

    Args:
        environment: Current application environment.
    """
    if logging.getLogger().hasHandlers():
        return
    logging.basicConfig(level=_resolve_log_level(environment))


_db_settings = get_database_settings()
logger.info(
    "Application database configured",
    extra={"database": safe_connection_metadata(_db_settings.database_url)},
)


def _register_lightweight_routers(app: FastAPI) -> None:
    """Register lightweight routers that are always needed.

    These routers have zero or negligible import overhead and are needed for
    basic functionality and cold-start mitigation.
    """
    # Lightweight ping endpoint for cold-start mitigation (issue #1389).
    # Zero database/ORM overhead; keeps Vercel serverless functions warm.
    from app.api import ping

    app.include_router(ping.router, prefix="/api", tags=["ping"])

    # Expose the metrics router in every environment so production performance
    # tracking (issue #834) and future regression checks can read startup
    # telemetry. It returns only process startup epoch and duration.
    from app.api import metrics

    app.include_router(metrics.router, prefix="/api", tags=["metrics"])
    app.include_router(metrics.router, prefix="/api/v1", tags=["metrics"])


def _register_heavy_routers(app: FastAPI) -> None:
    """Register routers that may pull in heavier optional dependencies.

    These are moved behind lazy imports so a cold start that only serves /api/ping
    does not pay the cost of image-processing or performance-telemetry stacks.
    """
    # Performance metrics collection and query (issue #834).
    # Records and exposes production startup and page-load timing data
    # so regressions can be tied to deployments. Versioned-surface only:
    # new client resources must not introduce bare /api/* routes.
    from app.api import performance_metric

    app.include_router(
        performance_metric.router,
        prefix="/api/v1/performance-metrics",
        tags=["performance-metrics"],
    )

    # Edge-cacheable remote cover image optimizer. Unauthenticated by design
    # (<img> tags cannot send auth); strictly allowlisted upstreams only.
    from app.api import images

    app.include_router(images.router, tags=["images"])


def _register_core_routers(app: FastAPI) -> None:
    """Register core API routers that are always needed.

    These imports are deferred to function scope so they are not executed at
    module load time, reducing the cold-start import graph.
    """
    # API route prefix convention:

    # - Every domain resource is reachable under the versioned /api/v1/* surface.
    # - Legacy resources remain available under /api/* as compatibility aliases.
    # - Retained auth, session, snooze, undo, roll, and rating resources have
    #   explicit v1 aliases while legacy paths remain compatibility surfaces.
    # - Admin (internal ops), bug reports, metrics, and non-production debug
    #   tooling expose canonical /api/v1 twins of their legacy mounts.
    # - Ping is operational telemetry exempt from versioning; test helpers stay
    #   test-only tooling under bare /api/test/* in test environments.
    # Add new client resources under /api/v1/*; do not introduce new bare
    # /api/* routes.
    from app.api import admin
    from app.api import analytics
    from app.api import auth
    from app.api import bug_report
    from app.api import catalog
    from app.api import cbl_plan_adoption
    from app.api import comicvine_resolution
    from app.api import creators
    from app.api import dependency
    from app.api import health
    from app.api import identity_inbox
    from app.api import issue
    from app.api import issue_identity
    from app.api import preferences
    from app.api import queue
    from app.api import rate
    from app.api import reading_mode
    from app.api import reading_orders
    from app.api import recommendation_diagnostics
    from app.api import roll
    from app.api import session
    from app.api import snooze
    from app.api import taste
    from app.api import taste_signal
    from app.api import thread
    from app.api import traffic_metrics
    from app.api import undo

    app.include_router(roll.router, prefix="/api/roll", tags=["roll"])
    app.include_router(roll.router, prefix="/api/v1/roll", tags=["roll"])
    # Roll v2: versioned-only, no unversioned alias per #2716
    app.include_router(roll.v2_router, prefix="/api/v2/roll", tags=["roll"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
    app.include_router(analytics.router, prefix="/api", tags=["analytics"])
    app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(bug_report.router, prefix="/api/bug-reports", tags=["bug-reports"])
    app.include_router(bug_report.router, prefix="/api/v1/bug-reports", tags=["bug-reports"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(thread.router, prefix="/api/threads", tags=["threads"])
    app.include_router(thread.router, prefix="/api/v1/threads", tags=["threads"])
    # New client resources (e.g. paginated completed threads for issue #2567)
    # are versioned-only: no bare /api/* twin.
    app.include_router(thread.v1_router, prefix="/api/v1/threads", tags=["threads"])
    app.include_router(issue.router, tags=["issues"])
    app.include_router(comicvine_resolution.router, tags=["comicvine-resolution"])
    app.include_router(creators.router, tags=["creators"])
    app.include_router(taste.router, prefix="/api/v1", tags=["taste"])
    app.include_router(rate.router, prefix="/api/rate", tags=["rate"])
    app.include_router(rate.router, prefix="/api/v1/rate", tags=["rate"])
    app.include_router(queue.router, prefix="/api/queue", tags=["queue"])
    app.include_router(queue.router, prefix="/api/v1/queue", tags=["queue"])
    app.include_router(reading_orders.router, tags=["reading-orders"])
    app.include_router(
        recommendation_diagnostics.router, prefix="/api", tags=["recommendations"]
    )
    app.include_router(session.router, prefix="/api/sessions", tags=["session"])
    app.include_router(session.router, prefix="/api/v1/sessions", tags=["session"])
    app.include_router(reading_mode.router, tags=["reading-mode"])
    app.include_router(snooze.router, prefix="/api/snooze", tags=["snooze"])
    app.include_router(snooze.router, prefix="/api/v1/snooze", tags=["snooze"])
    app.include_router(undo.router, prefix="/api/undo", tags=["undo"])
    app.include_router(undo.router, prefix="/api/v1/undo", tags=["undo"])
    app.include_router(preferences.router, prefix="/api/v1", tags=["users"])
    app.include_router(taste_signal.router, prefix="/api/v1", tags=["taste-signals"])
    app.include_router(traffic_metrics.router, prefix="/api", tags=["traffic"])
    app.include_router(dependency.router, prefix="/api/v1", tags=["dependencies"])
    app.include_router(catalog.router, tags=["catalog"])
    app.include_router(identity_inbox.router, tags=["identity-inbox"])
    app.include_router(issue_identity.router, tags=["issue-identity"])
    app.include_router(cbl_plan_adoption.router, tags=["cbl-adoption-commit"])


def _register_debug_routers(app: FastAPI, environment: str) -> None:
    """Register debug routers in non-production environments.

    Args:
        app: The FastAPI application instance.
        environment: Current application environment string.
    """
    if environment != "production":
        from app.api import debug

        app.include_router(debug.router, prefix="/api", tags=["debug"])
        app.include_router(debug.router, prefix="/api/v1", tags=["debug"])


def _register_test_routers(app: FastAPI) -> None:
    """Register test-helper routers when running in the test environment."""
    if os.getenv("TEST_ENVIRONMENT") == "true":
        from app.api.test_helpers import router as test_helpers_router

        app.include_router(test_helpers_router, prefix="/api", tags=["test"])


def register_all_routers(app: FastAPI, environment: str) -> None:
    """Register all routers in optimized order.

    Router modules are imported lazily inside each sub-function so that a cold
    ping invocation does not load the full import graph. Registration order:
    lightweight (ping, metrics) -> core API routers -> heavy/optional routers
    -> environment-specific debug and test routers.

    Args:
        app: The FastAPI application instance.
        environment: Current application environment string.
    """
    _register_lightweight_routers(app)
    _register_core_routers(app)
    _register_heavy_routers(app)
    _register_debug_routers(app, environment)
    _register_test_routers(app)


def create_app(*, serve_frontend: bool = True) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        serve_frontend: Whether to mount frontend static assets and SPA routes.

    Returns:
        Configured FastAPI application instance.
    """
    app_settings = get_app_settings()
    _configure_logging(app_settings.environment)
    startup_state: dict[str, str] = {}

    _heavy_lock: asyncio.Lock = asyncio.Lock()
    _heavy_state: dict[str, bool] = {"initialized": False, "in_progress": False}

    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )

    # Register rate limiter and handler for both normal and test-mode rate limiting.
    app.state.limiter = limiter

    def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
        """Adapt slowapi handler to FastAPI's exception handler type.

        Args:
            request: FastAPI request object.
            exc: Raised exception.

        Returns:
            Response generated by slowapi's exception handler.
        """
        return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))

    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app_settings.validate_production_cors()
    cors_origins = app_settings.cors_origins_list

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(PerformanceMiddleware)

    @app.middleware("http")
    async def csrf_middleware(request: Request, call_next):
        """Require a matching CSRF header and cookie on mutating API requests."""
        if os.getenv("TEST_ENVIRONMENT") == "true":
            return await call_next(request)
        if not is_csrf_protected_request(request.method, request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        if not auth_header:
            return await call_next(request)

        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        if (
            not csrf_cookie
            or not csrf_header
            or not secrets.compare_digest(csrf_cookie, csrf_header)
        ):
            log_csrf_rejection(request)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)

    # Register all routers with deferred imports to reduce cold-start cost.
    register_all_routers(app, app_settings.environment)

    # Error-only request logging (body redaction + environment-aware sanitization).
    add_request_logging_middleware(app, app_settings.environment)

    # Global, HTTP, and validation exception handlers (environment-aware logging).
    register_exception_handlers(app, app_settings)

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
        include_in_schema=False,
    )
    async def api_not_found(path: str) -> JSONResponse:
        """Return a JSON 404 for unknown API routes.

        Args:
            path: API path that was not found.

        Returns:
            JSON response with 404 status code.
        """
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not Found"})

    class CacheControlledStaticFiles(StarletteStaticFiles):
        """StaticFiles with explicit cache-control headers for hashed assets."""

        async def get_response(self, path: str, scope: Scope) -> StarletteResponse:
            """Get static file response with cache-control headers.

            Args:
                path: The path to the static file.
                scope: ASGI scope containing request information.

            Returns:
                A Starlette response with cache-control headers for hashed assets.
            """
            response = await super().get_response(path, scope)
            if hasattr(response, "headers"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    if serve_frontend:
        if app_settings.environment == "production":
            _assert_production_frontend_assets()
            app.mount("/static", StaticFiles(directory="static"), name="static")
            app.mount(
                "/assets",
                CacheControlledStaticFiles(directory="static/react/assets"),
                name="assets",
            )
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
            fallback_html = "<!doctype html><html><body><div id='root'></div></body></html>"
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

    if serve_frontend:

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

    async def _init_provided_cache(
        provider_name: str,
        startup_state: dict[str, str],
        config: dict[str, str],
    ) -> None:
        """Initialize the configured cache provider with demotion support.

        The process-wide ``cache`` router is reconfigured in place so that every
        importer keeps using the same singleton. On persistent failure the
        provider is demoted to fail-open for the process lifetime; optional
        caching never becomes a request dependency.

        Args:
            provider_name: ``"postgres"`` or ``"redis"``.
            startup_state: Shared dict between startup and shutdown events.
            config: Provider-specific keyword arguments for ``cache.configure``.
        """
        try:
            await cache.configure(provider_name, **config)
            startup_state["cache_provider_type"] = provider_name
            logger.info(
                "Cache provider '%s' initialized successfully", provider_name
            )
        except Exception as exc:
            logger.error(
                "Cache provider '%s' startup failed: %s - "
                "Demoting to fail-open for process lifetime",
                provider_name,
                exc,
            )
            await cache.demote()
            startup_state["cache_provider_type"] = "demoted-off"

    async def _ensure_heavy_init() -> None:
        """Lazily initialize database, cache accounting, and cache provider once.

        The lightweight ``/api/ping`` wake-up deliberately skips this path so a
        cold ping does not open a PostgreSQL connection or reserve cache blocks.
        Every other operational route triggers heavy init on first use, guarded
        by an async lock so concurrent cold requests only run the sequence once.
        """
        if _heavy_state["initialized"]:
            return
        async with _heavy_lock:
            if _heavy_state["initialized"]:
                return
            if _heavy_state["in_progress"]:
                return
            _heavy_state["in_progress"] = True
            try:
                await init_database(app_settings.environment)

                from app.cache_accounting import cache_accounting
                from app.database import async_engine

                try:
                    await cache_accounting.initialize(async_engine)
                except Exception:
                    logger.warning(
                        "Durable cache accounting init failed; quota telemetry degraded"
                    )

                redis_settings = get_redis_settings()
                from app.cache_quota import set_quota_throttle_enabled

                set_quota_throttle_enabled(redis_settings.cache_quota_throttle_enabled)
                provider = redis_settings.effective_provider

                if provider == "off":
                    logger.info("CACHE_PROVIDER=off - caching disabled")
                elif provider == "postgres":
                    await _init_provided_cache(
                        "postgres",
                        startup_state,
                        {"database_url": get_database_settings().async_url},
                    )
                elif provider == "redis":
                    if (
                        redis_settings.resolved_upstash_rest_url
                        and redis_settings.resolved_upstash_rest_token
                    ):
                        await _init_provided_cache(
                            "redis",
                            startup_state,
                            {
                                "url": redis_settings.resolved_upstash_rest_url,
                                "token": redis_settings.resolved_upstash_rest_token,
                                "throttle_enabled": redis_settings.cache_quota_throttle_enabled,
                            },
                        )
                    elif redis_settings.redis_url:
                        if not redis_settings.cache_local_redis_dev:
                            logger.warning(
                                "Local Redis URL present but CACHE_LOCAL_REDIS_DEV is not set; "
                                "refusing the local Redis client path. Use Upstash credentials "
                                "or enable the dev flag to use local Redis."
                            )
                        else:
                            await _init_provided_cache(
                                "redis",
                                startup_state,
                                {
                                    "local_url": redis_settings.redis_url,
                                    "allow_local": True,
                                    "throttle_enabled": redis_settings.cache_quota_throttle_enabled,
                                },
                            )
                    else:
                        logger.warning(
                            "Redis credentials absent for CACHE_PROVIDER=redis; caching disabled"
                        )

                from app.startup_diagnostics import mark_heavy_init_complete

                heavy_ms = mark_heavy_init_complete()
                logger.warning(
                    "Heavy application initialization completed in %.2f ms provider=%s",
                    heavy_ms,
                    startup_state.get("cache_provider_type", "unconfigured"),
                    extra={
                        "event": "heavy_application_startup",
                        "heavy_initialized": True,
                        "heavy_init_duration_ms": round(heavy_ms, 2),
                        "cache_provider_type": startup_state.get(
                            "cache_provider_type", "unconfigured"
                        ),
                    },
                )
                _heavy_state["initialized"] = True
            finally:
                _heavy_state["in_progress"] = False

    # Expose for tests and get_db fallback
    app.state.ensure_heavy_init = _ensure_heavy_init  # type: ignore[attr-defined]
    app.state.heavy_init_state = _heavy_state  # type: ignore[attr-defined]

    @app.on_event("startup")
    async def startup_event():
        """Lightweight startup; heavy DB/cache init is deferred to first non-ping request."""
        await compute_startup_duration()
        from app.startup_diagnostics import is_heavy_initialized, startup_event_snapshot

        snapshot = startup_event_snapshot()
        logger.warning(
            "Lightweight application startup completed (ping-ready) in %.2f ms heavy_initialized=%s",
            snapshot.startup_duration_ms or 0.0,
            is_heavy_initialized(),
            extra={
                "event": "lightweight_application_startup",
                "heavy_initialized": is_heavy_initialized(),
                "startup_duration_ms": round(snapshot.startup_duration_ms or 0.0, 2),
                "deployment_id": snapshot.deployment_id,
            },
        )

        # Start Neon egress monitor when credentials are configured.
        if os.getenv("NEON_TOKEN") and os.getenv("NEON_PROJECT_ID"):
            try:
                from app.services.neon_monitor import startup_event as neon_startup

                await neon_startup()
            except Exception:
                logger.warning("Neon monitor startup skipped", exc_info=True)

    @app.middleware("http")
    async def heavy_init_middleware(request: Request, call_next):
        """Ensure heavy dependencies are ready for all routes except the ping probe."""
        defer_heavy_init = os.getenv("TEST_ENVIRONMENT") == "true" and os.getenv(
            "ENABLE_LAZY_HEAVY_INIT_IN_TESTS"
        ) != "true"
        # Exempt the keep-warm probe including its trailing-slash form, which
        # Starlette would otherwise slash-redirect only after heavy init ran.
        request_path = request.url.path
        is_ping_probe = request_path == "/api/ping" or request_path.startswith("/api/ping/")
        if not is_ping_probe and not defer_heavy_init:
            await _ensure_heavy_init()
        response = await call_next(request)
        from app.startup_diagnostics import is_heavy_initialized as _is_heavy

        response.headers["X-Heavy-Init"] = "1" if _is_heavy() else "0"
        return response

    @app.on_event("shutdown")
    async def shutdown_event():
        """Close cache connection and accounting on application shutdown."""
        from app.cache_accounting import cache_accounting

        logger.info(
            "Shutting down cache (provider=%s)",
            startup_state.get("cache_provider_type", "unconfigured"),
        )
        await cache_accounting.close()
        await cache.close()

        # Shut down Neon egress monitor if it was started.
        if os.getenv("NEON_TOKEN") and os.getenv("NEON_PROJECT_ID"):
            try:
                from app.services.neon_monitor import shutdown_event as neon_shutdown

                await neon_shutdown()
            except Exception:
                logger.warning("Neon monitor shutdown skipped", exc_info=True)

    return app


app = create_app()
