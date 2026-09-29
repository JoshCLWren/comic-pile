"""Guard the FastAPI route-introspection contract this codebase relies on.

FastAPI 0.137.0 refactored ``include_router`` so that ``router.routes`` becomes
a tree of router-inclusion nodes instead of a flat list of ``APIRoute``
objects, and it stopped reporting the effective mounted path through
``scope["route"].path``. Both are load-bearing here: every API surface in
``app/main.py`` is mounted with ``include_router``, ``app/traffic_metrics.py``
derives per-route request counters from ``scope["route"].path``, and the
route-surface guards under ``tests/`` flatten ``app.routes``.

On 0.137+ both surfaces silently degrade instead of raising: included routes
vanish from ``app.routes``, and ``scope["route"].path`` reverts to the
unprefixed sub-router path, so distinct endpoints collapse onto the same
traffic-metrics bucket. ``pyproject.toml`` therefore caps FastAPI below 0.137
until the route-introspection layer is migrated off internals that upstream
documented as no longer public API. These tests fail loudly if that cap is
lifted before the migration happens.
"""

import fastapi
from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient


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


def _flat_route_paths(app: FastAPI) -> set[str]:
    """Collect the paths of every ``APIRoute`` reachable from ``app.routes``.

    Args:
        app: FastAPI application to inspect.

    Returns:
        Paths of the routes that a flat ``app.routes`` scan can observe.
    """
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_included_router_routes_remain_flat_and_prefixed() -> None:
    """``app.routes`` must expose included routes as flat, prefixed paths."""
    captured: dict[str, object] = {}
    app = _build_included_router_app(captured)

    assert f"{_MOUNT_PREFIX}/widgets/{{widget_id}}" in _flat_route_paths(app)


async def test_matched_scope_route_reports_the_effective_mounted_path() -> None:
    """``scope["route"].path`` must stay the effective mounted path template."""
    captured: dict[str, object] = {}
    app = _build_included_router_app(captured)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://probe") as client:
        response = await client.get(f"{_MOUNT_PREFIX}/widgets/7")

    assert response.status_code == 200
    scope = captured["scope"]
    route = scope.get("route") if isinstance(scope, dict) else None
    assert getattr(route, "path", None) == f"{_MOUNT_PREFIX}/widgets/{{widget_id}}"


def test_pinned_fastapi_still_provides_the_flat_route_contract() -> None:
    """The installed FastAPI must predate the router-tree refactor in 0.137.0."""
    version = tuple(int(part) for part in fastapi.__version__.split(".")[:2])
    assert version < (0, 137), (
        f"FastAPI {fastapi.__version__} replaced app.routes with a router "
        "inclusion tree and stopped reporting effective mounted paths. Migrate "
        "app/traffic_metrics.py and the tests/* route-surface guards off "
        "router.routes before lifting the <0.137.0 ceiling in pyproject.toml."
    )
