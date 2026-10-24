"""FastAPI application factory and configuration."""

import asyncio
import logging
import os
import secrets
from pathlib import Path
from typing import cast
from xml.sax.saxutils import escape as escape_xml

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

from app.config import get_app_settings, get_database_settings
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
from app.performance_budgets import (
    PerformanceWarning,
    StartupBudgetError,
    enforce_startup_budget,
    get_performance_budget_manager,
    run_bounded,
)
from app.router_mounts import (
    RouterMount,
    build_router_mounts,
    select_mounts_for_path,
)
from app.safe_logging import safe_connection_metadata

logger = logging.getLogger(__name__)

# Per-operation startup budgets (issue #3243). Every readiness-critical await on
# the ping-ready path is bounded well below the 2500 ms total startup budget, so
# the offending operation is named and cancelled long before the process could
# reach a pathological cold start.
_NEON_STARTUP_WARNING_MS = 150
_NEON_STARTUP_TIMEOUT_MS = 500
# Heavy database initialization runs on the first non-ping request, not on the
# ping-ready path, so it carries its own separately budgeted deadline. Its retry
# backoff can legitimately exceed the ping-readiness budget.
_HEAVY_INIT_WARNING_MS = 3000
_HEAVY_INIT_TIMEOUT_MS = 5000


# SEO indexability policy (issue #3065). Only the public landing page is a
# crawl target. Every other SPA path — auth/utility pages, redirects, and all
# authenticated routes — is served with `X-Robots-Tag: noindex, nofollow` so it
# cannot appear in search results even for crawlers that skip JavaScript. The
# frontend canonical table in `frontend/src/seo/routeSeo.ts` mirrors this
# policy for client-side head management (`Seo` component).
_SPA_INDEXABLE_PATHS = frozenset({"/"})

# Canonical production origin for absolute SEO URLs (`/sitemap.xml` and the
# `Sitemap:` line in `robots.txt`). Mirrors `DEFAULT_PRODUCTION_ORIGIN` in
# `frontend/scripts/generate-sitemap.mjs`; a build may override its own copy
# through `VITE_PRODUCTION_ORIGIN`.
PRODUCTION_ORIGIN = "https://comic-pile.vercel.app"


def _robots_tag_for_spa_path(request_path: str) -> str | None:
    """Return the robots header value for an SPA path, if it must not be indexed.

    Args:
        request_path: Request path with or without a leading slash.

    Returns:
        ``"noindex, nofollow"`` for every path except the indexable landing
        page, ``None`` when the path is an intentional crawl target.
    """
    normalized = "/" + request_path.strip().strip("/")
    if normalized in _SPA_INDEXABLE_PATHS:
        return None
    return "noindex, nofollow"


def _spa_route_file_path(request_path: str) -> Path:
    """Return the route-specific HTML file for a request path, if one exists.

    The Vite build's ``closeBundle`` hook generates a static ``<route>.html`` for
    every non-parameterized route (see ``frontend/scripts/generate-route-html.mjs``).
    Serving that file lets crawlers and clients see route-specific title,
    description, canonical, and robots metadata instead of the landing page
    shell.

    The request path is never trusted for filesystem layout: empty, ``.`` and
    ``..`` segments, and backslashes are rejected so a crafted request such as
    ``/../../frontend/dice-playground`` cannot escape ``static/react`` and serve
    an unrelated ``.html`` file. An unsafe path falls back to the SPA index,
    exactly like any other route without a generated file, and the resolved
    candidate must stay inside the build directory even if it contains a
    symlinked segment.

    Args:
        request_path: Request path with or without a leading slash.

    Returns:
        Path to the generated route HTML file, or the SPA index when the path
        is unsafe or no route-specific file was generated.
    """
    build_dir = Path("static/react")
    stripped = request_path.strip().strip("/")
    if not stripped:
        return build_dir / "index.html"
    segments = stripped.replace("\\", "/").split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return build_dir / "index.html"
    candidate = build_dir / f"{stripped}.html"
    if not candidate.resolve().is_relative_to(build_dir.resolve()):
        return build_dir / "index.html"
    return candidate


def _render_sitemap_xml() -> str:
    """Render the sitemap for the canonical indexable path set.

    Served when a build has not published ``static/react/sitemap.xml`` (local
    development and test checkouts), so ``/sitemap.xml`` always answers with
    valid XML instead of the SPA shell.

    Returns:
        Sitemap XML listing every path in ``_SPA_INDEXABLE_PATHS`` with an
        absolute canonical URL on the production origin.
    """
    locations = [escape_xml(PRODUCTION_ORIGIN + path) for path in sorted(_SPA_INDEXABLE_PATHS)]
    entries = "".join(f"  <url><loc>{loc}</loc></url>\n" for loc in locations)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}"
        "</urlset>\n"
    )


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


#: Route prefixes whose routers are registered before deferred loading starts.
#: A request for one of these answers from the already-registered table and must
#: not pay to register anything else (issue #3479).
_EAGER_ROUTE_PREFIXES: tuple[str, ...] = (
    "/api/ping",
    "/api/metrics",
    "/api/v1/metrics",
    "/api/v1/keepalive",
    "/health",
)


def _is_eager_path(path: str) -> bool:
    """Return whether ``path`` is served by an eagerly registered route.

    Args:
        path: Concrete request path.

    Returns:
        True when the path answers from the lightweight cold-start route table.
    """
    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in _EAGER_ROUTE_PREFIXES
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

    # Lightweight keep-alive endpoint for Neon warm-pool maintenance (issue #3480).
    # Runs a minimal SELECT 1 on the pooled connection to prevent Neon
    # from suspending during active use. Browser-consumed operational
    # tooling: mounted under /api/v1 and kept out of the generated client
    # schema (include_in_schema=False), like the bounded health probes.
    from app.api import keepalive

    app.include_router(keepalive.router, prefix="/api/v1", tags=["keepalive"])

    # Expose the metrics router in every environment so production performance
    # tracking (issue #834) and future regression checks can read startup
    # telemetry. It returns only process startup epoch and duration.
    from app.api import metrics

    app.include_router(metrics.router, prefix="/api", tags=["metrics"])
    app.include_router(metrics.router, prefix="/api/v1", tags=["metrics"])


def register_all_routers(app: FastAPI, environment: str) -> None:
    """Register every router in the historical order.

    Router modules are imported lazily inside each mount so that a cold ping
    invocation does not load the full import graph. Registration order is the
    historical ``include_router`` order: lightweight (ping, metrics, keepalive)
    then every deferred mount from :mod:`app.router_mounts`.

    Args:
        app: The FastAPI application instance.
        environment: Current application environment string.
    """
    _register_lightweight_routers(app)
    register_deferred_routers(app, environment)


def register_deferred_routers(app: FastAPI, environment: str) -> None:
    """Register every router that the lightweight cold start leaves out.

    Split out of :func:`register_all_routers` so a cold serverless start can
    register one resource mount on demand instead of importing the whole API
    surface. See :mod:`app.router_mounts` for the mount registry.

    Args:
        app: The FastAPI application instance.
        environment: Current application environment string.
    """
    for mount in build_router_mounts(environment):
        mount.register(app)


def _register_api_not_found_route(app: FastAPI) -> None:
    """Register the JSON 404 fallback for unknown ``/api/*`` paths.

    This must be registered after every real API route: Starlette matches
    routes in order, so the ``/api/{path:path}`` catch-all would otherwise
    shadow the deferred routers.

    Args:
        app: The FastAPI application instance.
    """

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


def create_app(*, serve_frontend: bool = True, defer_router_imports: bool = False) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        serve_frontend: Whether to mount frontend static assets and SPA routes.
        defer_router_imports: Whether to defer core, heavy, debug, and test
            router registration until the first non-ping request. The Vercel
            entry path enables this so a cold ``/api/ping`` start never imports
            the API surface; every other caller keeps eager registration so the
            complete route table is inspectable after construction.

    Returns:
        Configured FastAPI application instance.
    """
    app_settings = get_app_settings()
    _configure_logging(app_settings.environment)

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

    # Register routers with deferred, per-resource module imports to reduce
    # cold-start cost. In deferred mode only the lightweight ping/metrics/
    # keepalive routers are registered now. Each real request registers just the
    # mounts its resource segment needs (issue #3479) and splices them in after
    # the lightweight routes so the JSON 404 fallback and SPA routes keep
    # matching last.
    deferred_route_index: list[int | None] = [None]
    deferred_inserted = [0]
    deferred_mounts: list[RouterMount] = []
    registered_mount_keys: set[str] = set()
    fallback_registered = [False]

    def _register_deferred_mount(mount: RouterMount) -> None:
        """Register one deferred mount at its historical position, once."""
        if mount.key in registered_mount_keys:
            return
        registered_mount_keys.add(mount.key)
        existing_count = len(app.router.routes)
        mount.register(app)
        new_routes = app.router.routes[existing_count:]
        if not new_routes:
            return
        del app.router.routes[existing_count:]
        index = deferred_route_index[0]
        assert index is not None
        insert_at = index + deferred_inserted[0]
        app.router.routes[insert_at:insert_at] = new_routes
        deferred_inserted[0] += len(new_routes)
        # A route registered after the schema was generated must appear in it.
        app.openapi_schema = None

    def _register_api_fallback() -> None:
        """Place the JSON 404 fallback after every registered API route."""
        if fallback_registered[0]:
            return
        fallback_registered[0] = True
        existing_count = len(app.router.routes)
        _register_api_not_found_route(app)
        fallback_routes = app.router.routes[existing_count:]
        del app.router.routes[existing_count:]
        index = deferred_route_index[0]
        assert index is not None
        # Later mounts insert at the same index, so the fallback always stays
        # after the routes registered before it.
        insert_at = index + deferred_inserted[0]
        app.router.routes[insert_at:insert_at] = fallback_routes

    def register_routers_for_path(path: str) -> None:
        """Register the deferred mounts a request path needs.

        Unknown ``/api/*`` segments register nothing and answer from the routes
        that are already registered. Every non-API path (docs, OpenAPI schema,
        SPA) completes the whole route table so introspection stays complete.

        Args:
            path: Concrete request path.
        """
        if deferred_route_index[0] is None:
            return
        if _is_eager_path(path):
            return
        mounts = (
            select_mounts_for_path(path, deferred_mounts)
            if path.startswith("/api/")
            else tuple(deferred_mounts)
        )
        for mount in mounts:
            _register_deferred_mount(mount)
        _register_api_fallback()

    if defer_router_imports:
        _register_lightweight_routers(app)
        deferred_route_index[0] = len(app.router.routes)
        deferred_mounts.extend(build_router_mounts(app_settings.environment))
    else:
        register_all_routers(app, app_settings.environment)
        _register_api_not_found_route(app)

    # Exposed for the cold-start route-surface guards and for tests that drive
    # lazy registration without issuing HTTP requests.
    app.state.register_routers_for_path = register_routers_for_path

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
        robots_txt = Path("static/react/robots.txt")
        has_js = any(assets_dir.glob("*.js")) if assets_dir.exists() else False
        has_css = any(assets_dir.glob("*.css")) if assets_dir.exists() else False

        if (
            not spa_index.exists()
            or not assets_dir.exists()
            or not has_js
            or not has_css
            or not robots_txt.exists()
        ):
            raise RuntimeError(
                "Missing built frontend artifacts in production. "
                "Expected static/react/index.html, static/react/robots.txt, "
                "and static/react/assets with JS/CSS files."
            )

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

        def _serve_spa_index_response(request_path: str = "/") -> Response:
            """Serve SPA index file when available, else return fallback HTML.

            Args:
                request_path: Request path being served, used to decide the
                    robots header. Only the indexable landing page omits it.

            Returns:
                FileResponse for the built SPA index, or fallback HTMLResponse in test environments.
            """
            from fastapi.responses import FileResponse, HTMLResponse

            spa_index = Path("static/react/index.html")
            route_file = _spa_route_file_path(request_path)
            serve_path = route_file if route_file.exists() else spa_index
            cache_headers = {"Cache-Control": "no-store, no-cache, must-revalidate"}
            robots_tag = _robots_tag_for_spa_path(request_path)
            if robots_tag is not None:
                cache_headers["X-Robots-Tag"] = robots_tag
            if serve_path.exists():
                return FileResponse(str(serve_path), headers=cache_headers)
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
            return _serve_spa_index_response("/")

        @app.get("/robots.txt")
        async def serve_robots_txt():
            """Serve the crawler indexability policy.

            Prefers the built ``static/react/robots.txt`` (derived from
            ``frontend/public/robots.txt`` at build time), falling back to the
            source file in development and test checkouts.

            Returns:
                Plain-text robots.txt response with a short public cache.
            """
            from fastapi.responses import FileResponse

            robots_headers = {"Cache-Control": "public, max-age=3600"}
            built_robots = Path("static/react/robots.txt")
            if built_robots.exists():
                return FileResponse(
                    str(built_robots), media_type="text/plain", headers=robots_headers
                )
            source_robots = Path("frontend/public/robots.txt")
            if source_robots.exists():
                return FileResponse(
                    str(source_robots), media_type="text/plain", headers=robots_headers
                )
            raise StarletteHTTPException(status_code=503, detail="Crawler policy unavailable")

        @app.get("/sitemap.xml")
        async def serve_sitemap_xml():
            """Serve the sitemap of public indexable URLs.

            Prefers the build-generated ``static/react/sitemap.xml`` so a
            deployment that overrides ``VITE_PRODUCTION_ORIGIN`` serves its own
            absolute URLs, then falls back to rendering the canonical indexable
            path set so ``/sitemap.xml`` never returns the SPA shell.

            Returns:
                XML sitemap response with a short public cache.
            """
            from fastapi.responses import FileResponse

            sitemap_headers = {"Cache-Control": "public, max-age=3600"}
            built_sitemap = Path("static/react/sitemap.xml")
            if built_sitemap.exists():
                return FileResponse(
                    str(built_sitemap), media_type="application/xml", headers=sitemap_headers
                )
            return Response(
                content=_render_sitemap_xml(),
                media_type="application/xml",
                headers=sitemap_headers,
            )

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
    async def health_check() -> dict[str, str]:
        """Public liveness check without opening a billable Neon connection."""
        return {"status": "alive"}

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
            blocked_exact = {
                "health",
                "openapi.json",
                "docs",
                "redoc",
                "vite.svg",
                "robots.txt",
                "sitemap.xml",
            }

            if (
                full_path in blocked_exact
                or full_path in blocked_prefixes
                or any(full_path.startswith(prefix + "/") for prefix in blocked_prefixes)
            ):
                raise StarletteHTTPException(status_code=404, detail="Not Found")

            return _serve_spa_index_response(f"/{full_path}")

    async def _ensure_heavy_init() -> None:
        """Lazily initialize database once.

        The lightweight ``/api/ping`` wake-up deliberately skips this path so a
        cold ping does not open a PostgreSQL connection.
        Every other operational route triggers heavy init on first use, guarded
        by an async lock so concurrent cold requests only run the sequence once.
        
        This operation is protected by performance budgets to prevent slow
        initialization from blocking the application.
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
                # Initialize database under its own separately budgeted deadline.
                await run_bounded(
                    operation="startup.database_initialization",
                    coroutine=init_database(app_settings.environment),
                    warning_ms=_HEAVY_INIT_WARNING_MS,
                    timeout_ms=_HEAVY_INIT_TIMEOUT_MS,
                    context={
                        "environment": app_settings.environment,
                        "deployment_id": getattr(app_settings, "deployment_id", "unknown"),
                    },
                )

                from app.startup_diagnostics import mark_heavy_init_complete

                # mark_heavy_init_complete is synchronous (records a timestamp
                # and returns elapsed ms); it is not an awaitable and must not
                # be wrapped in run_bounded.
                heavy_ms = mark_heavy_init_complete()

                logger.warning(
                    "Heavy application initialization completed in %.2f ms",
                    heavy_ms,
                    extra={
                        "event": "heavy_application_startup",
                        "heavy_initialized": True,
                        "heavy_init_duration_ms": round(heavy_ms, 2),
                    },
                )
                _heavy_state["initialized"] = True

            except StartupBudgetError as e:
                logger.error(f"Heavy initialization budget exceeded: {e}")
                # In production, fail the request rather than continue with
                # incomplete initialization.
                if app_settings.environment == "production":
                    raise
                # In non-production, degrade explicitly: record the violation and
                # leave the operation uninitialized so the next request retries.
                violation = PerformanceWarning(
                    operation="heavy_init.database",
                    elapsed_ms=e.elapsed_ms,
                    budget_type="startup",
                    context={
                        "environment": app_settings.environment,
                        "deployment_id": getattr(app_settings, "deployment_id", "unknown"),
                        "deadline_ms": e.timeout_ms,
                    },
                    severity="violation",
                )
                get_performance_budget_manager().record_violation(violation)
                logger.error(
                    "Heavy initialization degraded: %s",
                    e,
                    extra={"performance_violation": violation.to_dict(), "level": "ERROR"},
                )
            finally:
                _heavy_state["in_progress"] = False

    # Expose for tests and get_db fallback
    for _attr_name, _attr_value in (
        ("ensure_heavy_init", _ensure_heavy_init),
        ("heavy_init_state", _heavy_state),
    ):
        setattr(app.state, _attr_name, _attr_value)

    @app.on_event("startup")
    async def startup_event():
        """Lightweight startup; heavy DB init is deferred to first non-ping request.

        The total ping-ready budget is evaluated after every readiness-critical
        await so no awaited startup work can hide from the 2.0 s warning and
        2.5 s hard budget.
        """
        try:
            await compute_startup_duration()
            from app.startup_diagnostics import is_heavy_initialized, startup_event_snapshot

            snapshot = startup_event_snapshot()
            startup_duration = snapshot.startup_duration_ms or 0.0

            # Start Neon egress monitor when credentials are configured. The
            # monitor is optional monitoring infrastructure, so a budget breach
            # degrades explicitly instead of extending ping readiness.
            if os.getenv("NEON_TOKEN") and os.getenv("NEON_PROJECT_ID"):
                try:
                    from app.services.neon_monitor import startup_event as neon_startup

                    await run_bounded(
                        operation="startup.neon_monitor",
                        coroutine=neon_startup(),
                        warning_ms=_NEON_STARTUP_WARNING_MS,
                        timeout_ms=_NEON_STARTUP_TIMEOUT_MS,
                        context={"deployment_id": snapshot.deployment_id},
                    )
                except Exception:
                    logger.warning("Neon monitor startup skipped", exc_info=True)

            ready_snapshot = startup_event_snapshot()
            readiness_ms = max(startup_duration, ready_snapshot.process_age_ms)
            try:
                enforce_startup_budget(
                    readiness_ms,
                    environment=app_settings.environment,
                    operation="startup.readiness",
                    context={
                        "deployment_id": ready_snapshot.deployment_id,
                        "heavy_initialized": is_heavy_initialized(),
                        "invocation": ready_snapshot.invocation,
                    },
                )
            finally:
                # Startup readiness samples are evaluated for telemetry but do
                # not file issues (issue #3552). Cold-start work is tracked
                # separately.
                try:
                    from app.services import performance_issue_service as perf_issues

                    perf_issues.handle_startup_telemetry(
                        duration_ms=readiness_ms,
                        operation="startup.readiness",
                        deployment_id=ready_snapshot.deployment_id,
                    )
                except Exception as exc:
                    logger.debug("Startup performance issue evaluation skipped: %s", exc)
            logger.warning(
                "Lightweight application startup completed (ping-ready) in %.2f ms heavy_initialized=%s",
                readiness_ms,
                is_heavy_initialized(),
                extra={
                    "event": "lightweight_application_startup",
                    "heavy_initialized": is_heavy_initialized(),
                    "startup_duration_ms": round(readiness_ms, 2),
                    "deployment_id": ready_snapshot.deployment_id,
                },
            )
        except StartupBudgetError:
            logger.error("Startup hard budget exceeded; failing initialization")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during startup: {e}")
            raise

    @app.middleware("http")
    async def heavy_init_middleware(request: Request, call_next):
        """Ensure heavy dependencies are ready for all routes except the ping probe."""
        defer_heavy_init = os.getenv("TEST_ENVIRONMENT") == "true" and os.getenv(
            "ENABLE_LAZY_HEAVY_INIT_IN_TESTS"
        ) != "true"
        # Exempt the keep-warm ping probe including its trailing-slash form, which
        # Starlette would otherwise slash-redirect only after heavy init ran.
        # The /api/v1/keepalive endpoint is NOT exempt - it needs the database pool.
        request_path = request.url.path
        is_ping_probe = request_path == "/api/ping" or request_path.startswith("/api/ping/")
        if not is_ping_probe:
            # Registration is synchronous, so concurrent cold requests cannot
            # interleave it; this runs before routing so the mounts the request
            # needs are part of the table the router matches against.
            register_routers_for_path(request_path)
        if not is_ping_probe and not defer_heavy_init:
            try:
                await _ensure_heavy_init()
            except StartupBudgetError as e:
                # In production, fail the request if heavy initialization times out
                if app_settings.environment == "production":
                    from fastapi import responses
                    return responses.JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={
                            "detail": "Service temporarily unavailable due to initialization timeout",
                            "operation": e.operation,
                            "elapsed_ms": e.elapsed_ms,
                            "timeout_ms": e.timeout_ms
                        }
                    )
                # In non-production, continue but log the violation
                logger.warning(f"Heavy initialization performance warning: {e}")
        
        response = await call_next(request)
        from app.startup_diagnostics import is_heavy_initialized as _is_heavy

        response.headers["X-Heavy-Init"] = "1" if _is_heavy() else "0"
        return response

    @app.on_event("shutdown")
    async def shutdown_event():
        """Shutdown application services."""
        # Shut down Neon egress monitor if it was started.
        if os.getenv("NEON_TOKEN") and os.getenv("NEON_PROJECT_ID"):
            try:
                from app.services.neon_monitor import shutdown_event as neon_shutdown

                await neon_shutdown()
            except Exception:
                logger.warning("Neon monitor shutdown skipped", exc_info=True)

        # Release the process-wide ComicVine keep-alive pool.
        try:
            from comic_pile.comicvine_provider import close_shared_http_client

            await close_shared_http_client()
        except Exception:
            logger.warning("ComicVine shared HTTP client shutdown skipped", exc_info=True)

    return app


_default_app: FastAPI | None = None


def get_app() -> FastAPI:
    """Return the process-wide default application, building it on first use.

    ``app.main:app`` stays a valid ASGI target for uvicorn and every
    ``from app.main import app`` importer, but importing this module no longer
    constructs an application. That removes the duplicate construction the
    Vercel entry path paid for, where importing :mod:`app.main` built a full
    frontend-serving app before ``api/index.py`` built its own.

    Returns:
        The cached default application instance.
    """
    global _default_app
    if _default_app is None:
        _default_app = create_app()
    return _default_app


def __getattr__(name: str) -> FastAPI:
    """Resolve the module-level ``app`` attribute on first access (PEP 562).

    Args:
        name: Attribute name requested on this module.

    Returns:
        The default application instance.

    Raises:
        AttributeError: If the module has no such attribute.
    """
    if name == "app":
        return get_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
