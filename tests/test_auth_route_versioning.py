"""Regression coverage for application startup and authentication routes."""

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


def _route_methods_by_path() -> dict[str, frozenset[str]]:
    """Return HTTP methods for each application route path.

    Returns:
        Mapping from route path to its supported HTTP methods.
    """
    app = create_app(serve_frontend=False)
    return {
        route.path: frozenset(route.methods or set())
        for route in app.routes
        if isinstance(route, APIRoute)
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
