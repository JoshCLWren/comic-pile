"""Operational-surface stability guards for the deliberately unversioned allowlist.

The v1 cutover contract (issue #1742) allowlists surfaces that must remain
reachable outside ``/api/v1``: FastAPI docs and static assets. These are
consumed by browsers and the SPA bundle rather than versioned API clients, so
relocating them is a production incident even when every API consumer has
migrated. The retired Python health probes are no longer part of this surface.

These tests inspect routing tables only; they never open database connections.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from app.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

#: FastAPI's default documentation surface, part of the unversioned allowlist.
_DOCS_ROUTES: frozenset[str] = frozenset(
    {
        "GET /docs",
        "GET /redoc",
        "GET /openapi.json",
    }
)


def _route_keys(app_routes: Sequence[object]) -> set[str]:
    """Collect ``METHOD path`` keys for every registered route.

    FastAPI registers domain endpoints as ``APIRoute`` objects but its docs
    surface (``/docs``, ``/redoc``, ``/openapi.json``) as plain Starlette
    ``Route`` objects, so matching is duck-typed on ``path``/``methods``.

    Args:
        app_routes: Route list from a FastAPI application instance.

    Returns:
        Set of ``"<METHOD> <path>"`` strings for all routable entries.
    """
    keys: set[str] = set()
    
    def _collect_routes(routes, prefix=""):
        for route in routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            # Handle included routers (FastAPI stores them as _IncludedRouter objects)
            if hasattr(route, 'original_router') and hasattr(route.original_router, 'routes'):
                # Get the prefix from the include context and recurse
                include_prefix = getattr(getattr(route, 'include_context', None), 'prefix', "") or ""
                new_prefix = prefix + include_prefix
                _collect_routes(route.original_router.routes, new_prefix)
            elif path and methods:
                full_path = prefix + path
                for method in methods:
                    keys.add(f"{method} {full_path}")
    
    _collect_routes(app_routes)
    return keys


@pytest.fixture(scope="module")
def api_routes() -> set[str]:
    """Build the application once and expose its flattened route table.

    Returns:
        Set of ``"<METHOD> <path>"`` strings for the default application.
    """
    return _route_keys(create_app(serve_frontend=True).routes)


def _assert_routes_present(routes: set[str], expected: frozenset[str]) -> None:
    """Assert every expected route key is registered.

    Args:
        routes: All registered ``"<METHOD> <path>"`` keys.
        expected: Route keys that must be present.

    Raises:
        AssertionError: If any expected route key is missing.
    """
    missing = sorted(expected - routes)
    assert not missing, (
        "Operational routes disappeared from the unversioned surface; uptime "
        f"probes, warmup crons, or the SPA heartbeat will break: {missing}"
    )


def test_temporary_cache_latency_probe_is_gone(api_routes: set[str]) -> None:
    """Issue #2216 one-shot probe must not ship on main."""
    assert "GET /api/v1/health/cache-latency" not in api_routes
    assert "GET /api/health/cache-latency" not in api_routes


def test_docs_surface_remains_unversioned(api_routes: set[str]) -> None:
    """Swagger, ReDoc, and the OpenAPI schema stay on their bare URLs."""
    _assert_routes_present(api_routes, _DOCS_ROUTES)


def test_no_double_versioned_route_paths(api_routes: set[str]) -> None:
    """No route may nest /v1 inside the versioned mount (prefix-shift bug).

    Moving a mount from ``/api`` to ``/api/v1`` without adjusting nested
    ``/v1/...`` route definitions produces paths such as
    ``/api/v1/v1/health/live``. This assertion fails loudly on that shape.
    """
    doubled = sorted(key for key in api_routes if "/v1/v1/" in key)
    assert not doubled, f"Double-versioned route paths detected: {doubled}"


_HAS_STATIC_DIR = (REPOSITORY_ROOT / "static").is_dir()


@pytest.mark.skipif(
    not _HAS_STATIC_DIR,
    reason="No static directory present; nothing to pin.",
)
def test_static_mounts_registered_when_assets_exist() -> None:
    """Static asset mounts stay unversioned whenever the bundles are present.

    Skipped when the repository has no built frontend assets, because
    ``create_app`` only mounts the static directories when they exist.
    """
    mount_paths = {
        getattr(route, "path", "") for route in create_app().routes
    }
    pinned = {"/static", "/assets"} & mount_paths
    assert pinned, (
        "Expected at least one unversioned static mount (/static or /assets) "
        "when frontend assets exist."
    )
