"""Tests for retained legacy and canonical API route aliases.

The API exposes a legacy surface (/api/*) and a versioned surface (/api/v1/*).
/api/v1/sessions/current/ is an explicit backwards-compat alias of
/api/sessions/current/ so session consumers can use the versioned surface
without behavior changes. See docs/API.md (API Versioning) and the convention
comment in app/main.py.

This test file verifies two things:
1. The alias does not drift for the /sessions/current/ endpoint.
2. No new client-facing routes are added under bare /api/* (regression guard
   for the convention documented in app/main.py).
"""

import pytest

from fastapi.routing import APIRoute, Mount
from httpx import AsyncClient

from app.main import create_app


# Routes that are intentionally mounted under bare /api/* as non-production
# tooling, not client APIs. These are exempt from the "no new bare /api/*"
# convention. See the comment in app/main.py.
_BARE_API_EXCEPTIONS = frozenset(
    {
        "/api/debug/log",
        "/api/metrics",
        "/api/test/sessions/expire",
        "/api/test/reading-orders",
        "/api/test/issue-identity",
    }
)


@pytest.mark.asyncio
async def test_api_v1_alias_session_endpoint_matches_legacy(auth_client: AsyncClient) -> None:
    """Verify /api/v1/sessions/current/ mirrors /api/sessions/current/.

    This ensures that aliasing does not change behavior and both routes
    return identical responses when authenticated.
    """
    resp_v1 = await auth_client.get("/api/v1/sessions/current/")
    resp_legacy = await auth_client.get("/api/sessions/current/")

    assert resp_v1.status_code == resp_legacy.status_code

    if resp_legacy.status_code == 200:
        assert resp_v1.json() == resp_legacy.json()
    else:
        assert resp_v1.text == resp_legacy.text


def _collect_routes(app) -> dict[str, frozenset[str]]:
    """Collect all APIRoute paths and methods, including those in IncludedRouters."""
    methods_by_path: dict[str, frozenset[str]] = {}

    def collect_from_routes(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                methods_by_path[route.path] = frozenset(route.methods or set())
            elif hasattr(route, "original_router") and hasattr(route, "include_context"):
                # IncludedRouter - collect from the original router with prefix
                prefix = route.include_context.prefix
                for r in route.original_router.routes:
                    if isinstance(r, APIRoute):
                        full_path = prefix + r.path
                        methods_by_path[full_path] = frozenset(r.methods or set())
            elif isinstance(route, Mount):
                # Recursively collect from mounted apps
                collect_from_routes(getattr(route.app, "routes", []))

    collect_from_routes(app.routes)
    return methods_by_path


def test_v1_snooze_and_undo_aliases_match_legacy_route_methods() -> None:
    """Canonical aliases reuse the same snooze and undo handler contracts."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    alias_pairs = (
        ("/api/snooze/", "/api/v1/snooze/"),
        ("/api/snooze/{thread_id}/unsnooze", "/api/v1/snooze/{thread_id}/unsnooze"),
        (
            "/api/undo/{session_id}/undo/{snapshot_id}",
            "/api/v1/undo/{session_id}/undo/{snapshot_id}",
        ),
        ("/api/undo/{session_id}/snapshots", "/api/v1/undo/{session_id}/snapshots"),
    )
    for legacy_path, canonical_path in alias_pairs:
        assert canonical_path in methods_by_path
        assert methods_by_path[canonical_path] == methods_by_path[legacy_path]


def test_v1_queue_aliases_match_legacy_route_methods() -> None:
    """Canonical /api/v1/queue aliases reuse the same queue handler contracts."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    alias_pairs = (
        ("/api/queue/shuffle/", "/api/v1/queue/shuffle/"),
        ("/api/queue/threads/{thread_id}/back/", "/api/v1/queue/threads/{thread_id}/back/"),
        ("/api/queue/threads/{thread_id}/front/", "/api/v1/queue/threads/{thread_id}/front/"),
        ("/api/queue/threads/{thread_id}/position/", "/api/v1/queue/threads/{thread_id}/position/"),
    )
    for legacy_path, canonical_path in alias_pairs:
        assert canonical_path in methods_by_path
        assert methods_by_path[canonical_path] == methods_by_path[legacy_path]


def test_v1_admin_aliases_match_legacy_route_methods() -> None:
    """Canonical /api/v1/admin aliases reuse the same admin handler contracts."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    alias_pairs = (
        ("/api/admin/import/csv/", "/api/v1/admin/import/csv/"),
        ("/api/admin/export/csv/", "/api/v1/admin/export/csv/"),
        ("/api/admin/export/json/", "/api/v1/admin/export/json/"),
        ("/api/admin/export/summary/", "/api/v1/admin/export/summary/"),
        ("/api/admin/delete-test-data/", "/api/v1/admin/delete-test-data/"),
    )
    for legacy_path, canonical_path in alias_pairs:
        assert canonical_path in methods_by_path
        assert methods_by_path[canonical_path] == methods_by_path[legacy_path]


def test_v1_bug_reports_alias_matches_legacy_route_methods() -> None:
    """Canonical /api/v1/bug-reports alias reuses the same handler contract."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    assert "/api/v1/bug-reports/" in methods_by_path
    assert methods_by_path["/api/v1/bug-reports/"] == methods_by_path["/api/bug-reports/"]


def test_v1_metrics_alias_matches_legacy_route_methods() -> None:
    """Canonical /api/v1/metrics alias reuses the same handler contract."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    assert "/api/v1/metrics" in methods_by_path
    assert methods_by_path["/api/v1/metrics"] == methods_by_path["/api/metrics"]


def test_v1_debug_alias_matches_legacy_route_methods_outside_production() -> None:
    """Canonical /api/v1/debug alias reuses the same handler contract (non-prod)."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    assert "/api/v1/debug/log" in methods_by_path
    assert methods_by_path["/api/v1/debug/log"] == methods_by_path["/api/debug/log"]


def test_no_new_bare_api_client_routes() -> None:
    """Regression guard: no client-facing routes under bare /api/* (non-v1)."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    # Grandfathered legacy bare /api/* routes. Extensions of an already-
    # grandfathered resource stay here when changing the prefix would break
    # existing clients.
    grandfathered_bare_api = frozenset(
        {
            "/api/admin/delete-test-data/",
            "/api/admin/export/csv/",
            "/api/admin/export/json/",
            "/api/admin/export/summary/",
            "/api/admin/import/csv/",
            "/api/analytics/metrics",
            "/api/analytics/summary",
            "/api/analytics/reading-history",
            "/api/auth/csrf",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/me",
            "/api/auth/refresh",
            "/api/auth/register",
            "/api/bug-reports/",
            "/api/health",
            "/api/ping",
            "/api/queue/shuffle/",
            "/api/queue/threads/{thread_id}/back/",
            "/api/queue/threads/{thread_id}/front/",
            "/api/queue/threads/{thread_id}/position/",
            "/api/rate/",
            "/api/roll/",
            "/api/roll/bootstrap",
            "/api/roll/clear-manual-die",
            "/api/roll/dismiss-pending",
            "/api/roll/override",
            "/api/roll/session-mode",
            "/api/roll/set-die",
            "/api/roll/events/{event_id}/recommendation-explanation",
            "/api/sessions/",
            "/api/sessions/current/",
            "/api/sessions/{session_id}",
            "/api/sessions/{session_id}/details",
            "/api/sessions/{session_id}/restore-session-start",
            "/api/sessions/{session_id}/snapshots",
            "/api/snooze/",
            "/api/snooze/{thread_id}/unsnooze",
            "/api/threads/",
            "/api/threads/active",
            "/api/threads/completed",
            "/api/threads/reactivate",
            "/api/threads/stale",
            "/api/threads/{thread_id}",
            "/api/threads/{thread_id}/position",
            "/api/threads/{thread_id}/set-pending",
            "/api/threads/{thread_id}/test-backdate",
            "/api/threads/{thread_id}:migrateToIssues",
            "/api/threads/{thread_id}:migrateToIssuesSimple",
            "/api/threads/{thread_id}:setCurrentIssue",
            "/api/tasks/",
            "/api/tasks/ready",
            "/api/tasks/metrics",
            "/api/undo/{session_id}/snapshots",
            "/api/undo/{session_id}/undo/{snapshot_id}",
            "/api/{path:path}",
        }
    )

    for path in methods_by_path:
        if not path.startswith("/api/"):
            continue
        if path.startswith("/api/v1/"):
            continue
        if path in _BARE_API_EXCEPTIONS:
            continue
        assert path in grandfathered_bare_api, (
            f"New bare /api/* route detected: {path}. "
            f"The API versioning convention (docs/API.md) requires new client "
            f"resources under /api/v1/*. Either move this route to /api/v1/* "
            f"or add it to the grandfathered set in test_route_versioning.py "
            f"if it is a legacy route."
        )
