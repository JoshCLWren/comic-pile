"""Operational-surface stability guards for the deliberately unversioned allowlist.

The v1 cutover contract (issue #1742) allowlists exactly four surfaces that must
remain reachable outside ``/api/v1``: health probes, ping, docs, and static
assets. These are consumed by uptime monitors, cold-start crons, browsers, and
the SPA bundle rather than versioned API clients, so relocating them is a
production incident even when every API consumer has migrated.

Regression provenance: an earlier cutover attempt moved the analytics mount
(which also carries the health router) from ``/api`` to ``/api/v1``, which
orphaned ``/api/health``, shifted the canonical bounded probes to
``/api/v1/v1/health/*``, and broke the frontend heartbeat fetch of
``/api/ping``. The guards below pin those surfaces so the final bare-mount
deletion step cannot silently relocate them.

These tests inspect routing tables only; they never open database connections.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from app.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

#: Bare paths that operational consumers depend on and that must never move
#: behind a version prefix. Ping warms serverless cold starts (issue #1389)
#: and is fetched directly by ``frontend/src/hooks/usePingHeartbeat.ts``;
#: ``/api/health`` is the dependency-free uptime liveness URL.
_BARE_OPERATIONAL_ROUTES: frozenset[str] = frozenset(
    {
        "GET /api/ping",
        "GET /api/health",
    }
)

#: Canonical bounded health probes served under the versioned prefix via the
#: analytics mount. Uptime tooling calls these instead of the legacy URL.
#: ``/api/v1/health/cache-quota`` (issue #1751) is the visible near-limit /
#: over-budget alert surface and must also stay pinned at ``/api/v1/health/*``.
_CANONICAL_HEALTH_ROUTES: frozenset[str] = frozenset(
    {
        "GET /api/v1/health/live",
        "GET /api/v1/health/dependencies",
        "GET /api/v1/health/warmup",
        "GET /api/v1/health/cache-quota",
        "GET /api/v1/health/cache-latency",
    }
)

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
    for route in app_routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            keys.add(f"{method} {path}")
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


def test_bare_ping_and_liveness_remain_unversioned(api_routes: set[str]) -> None:
    """The bare ping and legacy liveness URLs must stay mounted verbatim."""
    _assert_routes_present(api_routes, _BARE_OPERATIONAL_ROUTES)


def test_canonical_health_probes_stay_on_v1_prefix(api_routes: set[str]) -> None:
    """Bounded dependency probes must remain at /api/v1/health/*."""
    _assert_routes_present(api_routes, _CANONICAL_HEALTH_ROUTES)


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
