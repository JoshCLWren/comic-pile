"""Regression coverage for application startup and authentication routes."""

from collections.abc import Iterable

from fastapi.routing import APIRoute

from app.main import create_app


AUTH_SUFFIXES = frozenset(
    {
        "/csrf",
        "/login",
        "/logout",
        "/me",
        "/refresh",
        "/register",
    }
)

STARTUP_SENTINEL_ROUTES = {
    "/api/v1/auth/me": frozenset({"GET"}),
    "/api/v1/crossover-templates/preview": frozenset({"POST"}),
    "/api/v1/crossover-templates/adopt": frozenset({"POST"}),
    "/api/v1/continuity-plans/{plan_id}/readiness": frozenset({"GET"}),
}


def _collect_route_methods(
    routes: Iterable[object], *, prefix: str = ""
) -> dict[str, set[str]]:
    """Collect API route methods across flattened and lazily included routers."""
    methods_by_path: dict[str, set[str]] = {}

    for route in routes:
        if isinstance(route, APIRoute):
            methods_by_path.setdefault(f"{prefix}{route.path}", set()).update(
                route.methods or set()
            )
            continue

        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is None or include_context is None:
            continue

        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        for path, methods in _collect_route_methods(
            nested_routes, prefix=nested_prefix
        ).items():
            methods_by_path.setdefault(path, set()).update(methods)

    return methods_by_path


def _route_methods_by_path() -> dict[str, frozenset[str]]:
    """Return HTTP methods for each application route path.

    FastAPI 0.137+ can retain included routers lazily instead of flattening every
    child into ``app.routes``. Walk either representation so this startup guard
    does not silently depend on the currently pinned FastAPI implementation.

    Returns:
        Mapping from route path to its supported HTTP methods.
    """
    app = create_app(serve_frontend=False)
    return {
        path: frozenset(methods)
        for path, methods in _collect_route_methods(app.routes).items()
    }


def test_application_startup_loads_cross_feature_routers() -> None:
    """Require startup to load auth, crossover-template, and readiness routers."""
    methods_by_path = _route_methods_by_path()

    for path, methods in STARTUP_SENTINEL_ROUTES.items():
        assert path in methods_by_path
        assert methods_by_path[path] == methods


def test_auth_v1_routes_are_canonical_compatibility_twins() -> None:
    """Require every maintained auth operation on both v1 and legacy paths."""
    methods_by_path = _route_methods_by_path()

    for suffix in AUTH_SUFFIXES:
        canonical = f"/api/v1/auth{suffix}"
        legacy = f"/api/auth{suffix}"
        assert canonical in methods_by_path
        assert legacy in methods_by_path
        assert methods_by_path[canonical] == methods_by_path[legacy]


def test_openapi_exposes_canonical_auth_paths() -> None:
    """Keep canonical auth operations visible to generated frontend clients."""
    schema = create_app(serve_frontend=False).openapi()
    paths = schema["paths"]

    for suffix in AUTH_SUFFIXES:
        assert f"/api/v1/auth{suffix}" in paths
