"""Guard the FastAPI route-introspection contract this codebase relies on.

FastAPI 0.137.0 refactored ``include_router`` so that ``router.routes`` holds
a tree of router-inclusion nodes instead of a flat list of ``APIRoute``
objects. Included routes are reached by recursing through each node's
``original_router.routes`` while accumulating its ``include_context.prefix``,
and the effective mounted template for a request lives on the per-request
effective route context (``scope["fastapi"]["effective_route_context"]``)
because ``scope["route"]`` is now the original, unprefixed route.

Every API surface in ``app/main.py`` is mounted with ``include_router``,
``app/traffic_metrics.py`` resolves per-route request counters through
:func:`app.traffic_metrics.resolve_route_template`, and the route-surface
guards under ``tests/`` flatten ``app.routes`` with the same recursion. These
tests fail loudly if a future FastAPI release changes either surface again.
"""

from collections.abc import Sequence

from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.traffic_metrics import resolve_route_template

_MOUNT_PREFIX = "/api/v1/probes"


def _build_included_router_app(captured: dict[str, object]) -> FastAPI:
    """Build an app whose only route arrives through ``include_router``.

    Args:
        captured: Mutable sink that receives the live request scope.

    Returns:
        A FastAPI app with one prefixed, included route.
    """
    router = APIRouter()

    @router.get("/widgets/{widget_id}")
    async def read_widget(widget_id: int, request: Request) -> dict[str, int]:
        captured["scope"] = request.scope
        return {"widget_id": widget_id}

    app = FastAPI()
    app.include_router(router, prefix=_MOUNT_PREFIX)
    return app


def _flat_route_paths(routes: Sequence[object], prefix: str = "") -> set[str]:
    """Collect effective paths, descending into router-inclusion nodes.

    Args:
        routes: Route list from an application or an included router.
        prefix: Accumulated mount prefix from outer inclusion nodes.

    Returns:
        Effective paths of every reachable route.
    """
    paths: set[str] = set()
    for route in routes:
        if isinstance(route, APIRoute):
            paths.add(f"{prefix}{route.path}")
            continue
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is None or include_context is None:
            continue
        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        paths.update(_flat_route_paths(nested_routes, prefix=nested_prefix))
    return paths


def test_included_router_routes_remain_flat_and_prefixed() -> None:
    """Included routes must flatten to their effective prefixed paths."""
    captured: dict[str, object] = {}
    app = _build_included_router_app(captured)

    assert f"{_MOUNT_PREFIX}/widgets/{{widget_id}}" in _flat_route_paths(app.routes)


async def test_effective_route_template_reports_the_mounted_path() -> None:
    """The resolved template must stay the effective mounted path template."""
    captured: dict[str, object] = {}
    app = _build_included_router_app(captured)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://probe") as client:
        response = await client.get(f"{_MOUNT_PREFIX}/widgets/7")

    assert response.status_code == 200
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert (
        resolve_route_template(scope) == f"{_MOUNT_PREFIX}/widgets/{{widget_id}}"
    )


async def test_direct_routes_still_resolve_without_inclusion_nodes() -> None:
    """Directly registered routes resolve through the matched route fallback."""
    captured: dict[str, object] = {}
    app = FastAPI()

    @app.get("/direct/{name}")
    async def read_direct(name: str, request: Request) -> dict[str, str]:
        captured["scope"] = request.scope
        return {"name": name}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://probe") as client:
        response = await client.get("/direct/bob")

    assert response.status_code == 200
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert resolve_route_template(scope) == "/direct/{name}"
