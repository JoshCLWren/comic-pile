"""Route-coverage guards for per-resource deferred router loading (#3479).

``app.router_mounts`` declares which resource segments each deferred mount
serves. A missing declaration lets a real API route fall through to the JSON
404 fallback on a cold serverless start, which an eager-application test cannot
see. These guards exercise the deferred registry instead:

* every eager ``/api/*`` route is reachable after selecting mounts for its own
  path (the route-coverage guard promised by ``app.router_mounts``);
* a snooze request registers only the snooze mount, not catalog/images/delivery;
* ``POST /api/v1/roll/switch-prerequisite`` (composed into the dependency mount)
  answers on the first request instead of falling through to the fallback; and
* ``import api.index`` stays inside the cold-start import budget.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.router_mounts import EAGER_SEGMENTS, request_segment

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_FALLBACK_PATH = "/api/{path:path}"
PREREQUISITE_SWITCH_PATH = "/api/v1/roll/switch-prerequisite"
SNOOZE_PATH = "/api/v1/snooze/"
IMPORT_BUDGET_MS = 600


def _iter_effective_routes(routes, prefix: str = ""):
    """Yield ``(path, methods)`` pairs in match order.

    FastAPI 0.137+ keeps included routers as inclusion-tree nodes instead of
    flat route entries, so descend through each node's original router while
    accumulating its mount prefix.

    Args:
        routes: Route list from an application or an included router.
        prefix: Accumulated mount prefix from outer inclusion nodes.

    Yields:
        Effective route paths with their HTTP methods.
    """
    for route in routes:
        route_path = getattr(route, "path", None)
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if (
            isinstance(route_path, str)
            and not hasattr(route, "original_router")
            or nested_routes is None
            or include_context is None
        ):
            if isinstance(route_path, str):
                yield f"{prefix}{route_path}", getattr(route, "methods", None)
            continue
        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        yield from _iter_effective_routes(nested_routes, prefix=nested_prefix)


def _route_paths(app) -> list[str]:
    """Return the application's effective route paths in match order.

    Args:
        app: FastAPI application instance.

    Returns:
        Ordered effective route paths.
    """
    return [path for path, _methods in _iter_effective_routes(app.routes)]


def _route_signatures(app) -> set[tuple[str, frozenset[str]]]:
    """Return ``(path, methods)`` signatures for the application's routes.

    Args:
        app: FastAPI application instance.

    Returns:
        Effective route signatures; method-less routes use an empty set.
    """
    return {
        (path, frozenset(methods or ()))
        for path, methods in _iter_effective_routes(app.routes)
    }


def _api_route_signatures(app) -> set[tuple[str, frozenset[str]]]:
    """Return only the eager API route signatures that mounts must cover.

    Args:
        app: FastAPI application instance.

    Returns:
        Route signatures under ``/api/`` excluding the JSON 404 fallback.
    """
    return {
        signature
        for signature in _route_signatures(app)
        if signature[0].startswith("/api/") and API_FALLBACK_PATH not in signature[0]
    }


def test_every_eager_api_route_is_reachable_from_its_selected_mounts() -> None:
    """A request for any eager API route must load a mount that serves it."""
    eager_signatures = _api_route_signatures(create_app(serve_frontend=False))
    assert eager_signatures

    signatures_by_segment: dict[str, set[tuple[str, frozenset[str]]]] = {}
    for signature in eager_signatures:
        signatures_by_segment.setdefault(request_segment(signature[0]), set()).add(signature)

    for segment, expected in signatures_by_segment.items():
        if segment in EAGER_SEGMENTS:
            continue
        # One fresh deferred application per resource segment proves the mounts
        # selected for that segment register every route the eager app exposes.
        app = create_app(serve_frontend=False, defer_router_imports=True)
        sample_path = next(iter(expected))[0]
        app.state.register_routers_for_path(sample_path)
        registered = _route_signatures(app)
        missing = sorted(expected - registered)
        assert not missing, f"segment {segment!r} is not covered; missing {missing}"


@pytest.mark.asyncio
async def test_first_snooze_request_registers_only_the_snooze_mount() -> None:
    """A cold snooze request must not import catalog, images or delivery."""
    eager_paths = set(_route_paths(create_app(serve_frontend=False)))
    snooze_paths = {path for path in eager_paths if request_segment(path) == "snooze"}

    app = create_app(serve_frontend=False, defer_router_imports=True)
    cold_paths = set(_route_paths(app))
    assert SNOOZE_PATH not in cold_paths

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(SNOOZE_PATH)

    # Unauthenticated: a 401 proves the snooze route answered, not the fallback.
    assert response.status_code == 401

    loaded_paths = set(_route_paths(app)) - cold_paths - {API_FALLBACK_PATH}
    assert loaded_paths
    assert loaded_paths <= snooze_paths
    for heavy_path in ("/api/v1/catalog/series", "/api/v1/images/optimize", "/api/v1/delivery"):
        assert heavy_path not in cold_paths | loaded_paths


@pytest.mark.asyncio
async def test_prerequisite_switch_is_reachable_on_the_first_request() -> None:
    """The dependency-composed roll switch route must not fall through to 404."""
    app = create_app(serve_frontend=False, defer_router_imports=True)
    assert PREREQUISITE_SWITCH_PATH not in _route_paths(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            PREREQUISITE_SWITCH_PATH,
            json={"node_type": "issue", "node_id": 1},
        )

    assert response.status_code == 401
    assert PREREQUISITE_SWITCH_PATH in _route_paths(app)


def test_api_index_import_stays_within_the_cold_start_budget() -> None:
    """``import api.index`` must stay under the 0.6 s cold-start import budget."""
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import api.index"],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        check=True,
        timeout=120,
    )

    import_us = None
    for line in result.stderr.splitlines():
        if line.rstrip().endswith("| api.index"):
            import_us = int(line.rsplit("|", 2)[1].strip())
    assert import_us is not None, "importtime did not report api.index"
    assert import_us < IMPORT_BUDGET_MS * 1000, (
        f"import api.index took {import_us / 1000:.0f} ms; budget is {IMPORT_BUDGET_MS} ms"
    )
