"""Regression coverage for canonical Roll and rating v1 routes."""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.main import create_app


_ROLL_PATHS = (
    "/roll/",
    "/roll/dismiss-pending",
    "/roll/override",
)


def _iter_effective_api_routes(app: FastAPI) -> Iterator[tuple[str, APIRoute]]:
    """Yield every effective ``APIRoute`` with its mounted path.

    FastAPI 0.137+ keeps included routers as inclusion-tree nodes instead of
    flat ``APIRoute`` entries, so descend through each node's original router
    while accumulating its mount prefix.

    Args:
        app: FastAPI application under test.

    Returns:
        Iterator of ``(path, route)`` pairs for every effective API route.
    """
    stack: list[tuple[object, str]] = [(route, "") for route in app.routes]
    while stack:
        route, prefix = stack.pop(0)
        if isinstance(route, APIRoute):
            yield (f"{prefix}{route.path}", route)
            continue
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is None or include_context is None:
            continue
        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        stack[0:0] = [(nested, nested_prefix) for nested in nested_routes]


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
        for candidate_path, route in _iter_effective_api_routes(app)
        if candidate_path == path
    )


def test_roll_v1_aliases_and_retired_rate_routes() -> None:
    """Retained Roll aliases match; both retired Python rating paths are absent."""
    app = create_app(serve_frontend=False)

    for suffix in _ROLL_PATHS:
        legacy = _route_by_path(app, f"/api{suffix}")
        canonical = _route_by_path(app, f"/api/v1{suffix}")
        assert canonical.endpoint is legacy.endpoint
        assert canonical.methods == legacy.methods

    effective_paths = {path for path, _ in _iter_effective_api_routes(app)}
    assert "/api/rate/" not in effective_paths
    assert "/api/v1/rate/" not in effective_paths


def test_roll_v1_routes_have_unique_operation_ids_without_retired_rate() -> None:
    """OpenAPI must expose canonical routes without duplicate operation IDs."""
    app = create_app(serve_frontend=False)
    schema = app.openapi()

    expected_paths = {f"/api/v1{suffix}" for suffix in _ROLL_PATHS}
    assert "/api/v1/rate/" not in schema["paths"]
    assert expected_paths <= schema["paths"].keys()

    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))
