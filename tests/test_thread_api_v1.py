"""Contract tests for canonical and compatibility thread API routes."""

from collections.abc import Callable, Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.main import create_app


def _thread_routes(prefix: str) -> dict[tuple[str, tuple[str, ...]], Callable[..., object]]:
    """Return thread route suffix/method pairs mapped to their shared handlers."""
    app = create_app(serve_frontend=False)
    routes: dict[tuple[str, tuple[str, ...]], Callable[..., object]] = {}
    for path, route in _iter_effective_api_routes(app):
        if not path.startswith(prefix):
            continue
        suffix = path.removeprefix(prefix)
        methods = tuple(sorted(route.methods or set()))
        routes[(suffix, methods)] = route.endpoint
    return routes


def _iter_effective_api_routes(app: FastAPI) -> Iterator[tuple[str, APIRoute]]:
    """Yield ``(path, route)`` pairs, descending into router-inclusion nodes.

    FastAPI 0.137+ keeps included routers as inclusion-tree nodes instead of
    flat ``APIRoute`` entries, so recurse through each node's original router
    while accumulating its mount prefix.

    Args:
        app: FastAPI application under test.

    Returns:
        Iterator of ``(path, route)`` pairs for every effective API route.
    """
    routes = getattr(app, "routes", [])
    stack: list[tuple[object, str]] = [(route, "") for route in routes]
    while stack:
        route, route_prefix = stack.pop(0)
        if isinstance(route, APIRoute):
            yield (f"{route_prefix}{route.path}", route)
            continue
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is None or include_context is None:
            continue
        nested_prefix = f"{route_prefix}{getattr(include_context, 'prefix', '')}"
        stack[0:0] = [(nested, nested_prefix) for nested in nested_routes]


def test_v1_thread_routes_share_legacy_implementations() -> None:
    """Canonical retained thread routes must delegate to the compatibility handlers."""
    legacy = _thread_routes("/api/threads")
    canonical = _thread_routes("/api/v1/threads")

    assert legacy
    assert legacy.keys() <= canonical.keys()
    for route_key, legacy_endpoint in legacy.items():
        assert canonical[route_key] is legacy_endpoint


def test_v1_thread_openapi_operation_ids_are_unique() -> None:
    """Thread route additions must preserve document-wide OpenAPI operation ID uniqueness."""
    schema = create_app(serve_frontend=False).openapi()
    operation_ids: list[str] = []

    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation_ids.append(operation["operationId"])

    assert operation_ids
    assert len(operation_ids) == len(set(operation_ids))
