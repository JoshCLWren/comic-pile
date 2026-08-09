"""Contract tests for canonical and compatibility thread API routes."""

from collections.abc import Callable

from fastapi.routing import APIRoute

from app.main import create_app


def _thread_routes(prefix: str) -> dict[tuple[str, tuple[str, ...]], Callable[..., object]]:
    """Return thread route suffix/method pairs mapped to their shared handlers."""
    app = create_app(serve_frontend=False)
    routes: dict[tuple[str, tuple[str, ...]], Callable[..., object]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(prefix):
            continue
        suffix = route.path.removeprefix(prefix)
        methods = tuple(sorted(route.methods or set()))
        routes[(suffix, methods)] = route.endpoint
    return routes


def test_v1_thread_routes_share_legacy_implementations() -> None:
    """Canonical retained thread routes must delegate to the compatibility handlers."""
    legacy = _thread_routes("/api/threads")
    canonical = _thread_routes("/api/v1/threads")

    assert legacy
    assert legacy.keys() <= canonical.keys()
    for route_key, legacy_endpoint in legacy.items():
        assert canonical[route_key] is legacy_endpoint


def test_v1_thread_openapi_operation_ids_are_unique() -> None:
    """Canonical thread operations must not introduce duplicate OpenAPI operation IDs."""
    schema = create_app(serve_frontend=False).openapi()
    operation_ids: list[str] = []

    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/threads"):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation_ids.append(operation["operationId"])

    assert operation_ids
    assert len(operation_ids) == len(set(operation_ids))
