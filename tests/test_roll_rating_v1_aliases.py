"""Regression coverage for canonical Roll and rating v1 routes."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.main import create_app


_ROLL_PATHS = (
    "/roll/",
    "/roll/bootstrap",
    "/roll/clear-manual-die",
    "/roll/dismiss-pending",
    "/roll/override",
    "/roll/set-die",
)


def _route_by_path(app: FastAPI, path: str) -> APIRoute:
    """Return the API route registered for a path.

    Args:
        app: FastAPI application under test.
        path: Exact route path to locate.

    Returns:
        The matching FastAPI route.
    """
    return next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path
    )


def test_roll_and_rating_v1_aliases_reuse_legacy_handlers() -> None:
    """Canonical v1 aliases must share handlers with compatibility routes."""
    app = create_app(serve_frontend=False)

    for suffix in _ROLL_PATHS:
        legacy = _route_by_path(app, f"/api{suffix}")
        canonical = _route_by_path(app, f"/api/v1{suffix}")
        assert canonical.endpoint is legacy.endpoint
        assert canonical.methods == legacy.methods

    legacy_rate = _route_by_path(app, "/api/rate/")
    canonical_rate = _route_by_path(app, "/api/v1/rate/")
    assert canonical_rate.endpoint is legacy_rate.endpoint
    assert canonical_rate.methods == legacy_rate.methods


def test_roll_and_rating_v1_routes_are_exposed_once_in_openapi() -> None:
    """OpenAPI must expose canonical routes without duplicate operation IDs."""
    app = create_app(serve_frontend=False)
    schema = app.openapi()

    expected_paths = {f"/api/v1{suffix}" for suffix in _ROLL_PATHS} | {"/api/v1/rate/"}
    assert expected_paths <= schema["paths"].keys()

    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))
