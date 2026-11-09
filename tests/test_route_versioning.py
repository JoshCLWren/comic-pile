"""Tests for retained legacy and canonical API route aliases.

The API exposes a legacy surface (/api/*) and a versioned surface (/api/v1/*).
/api/v1/sessions/current/ is an explicit backwards-compat alias of
/api/sessions/current/ so session consumers can use the versioned surface
without behavior changes. See docs/API.md (API Versioning) and the convention
comment in app/main.py.

This test file verifies three things:
1. The alias does not drift for the /sessions/current/ endpoint.
2. No new client-facing routes are added under bare /api/* (regression guard
   for the convention documented in app/main.py).
3. Retired operations stay retired: the Roll skip/unskip surface has no
   handler, and re-adding one fails this suite.
"""

import pytest

from fastapi import FastAPI
from fastapi.routing import APIRoute, Mount
from httpx import AsyncClient

from app.main import create_app


# Routes that are intentionally mounted under bare /api/* as non-production
# tooling, not client APIs. These are exempt from the "no new bare /api/*"
# convention. See the comment in app/main.py.
_BARE_API_EXCEPTIONS = frozenset(
    {
        "/api/metrics",
        "/api/test/sessions/expire",
        "/api/test/reading-orders",
        "/api/test/issue-identity",
        "/api/test/cbl-source",
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

    def record_methods(path: str, methods: set[str] | None) -> None:
        methods_by_path[path] = methods_by_path.get(path, frozenset()) | frozenset(methods or ())

    def collect_from_routes(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                record_methods(route.path, route.methods)
            elif hasattr(route, "original_router") and hasattr(route, "include_context"):
                # IncludedRouter - collect from the original router with prefix
                prefix = route.include_context.prefix
                for r in route.original_router.routes:
                    if isinstance(r, APIRoute):
                        full_path = prefix + r.path
                        record_methods(full_path, r.methods)
            elif isinstance(route, Mount):
                # Recursively collect from mounted apps
                collect_from_routes(getattr(route.app, "routes", []))

    collect_from_routes(app.routes)
    return methods_by_path


def test_collect_routes_unions_methods_on_the_same_path() -> None:
    """Both methods survive when FastAPI registers separate route objects."""
    app = FastAPI()
    app.add_api_route("/api/v1/threads/", lambda: None, methods=["GET"])
    app.add_api_route("/api/v1/threads/", lambda: None, methods=["POST"])

    assert _collect_routes(app)["/api/v1/threads/"] == frozenset({"GET", "POST"})


def test_v1_undo_aliases_match_legacy_route_methods() -> None:
    """Canonical aliases reuse the same undo handler contracts (v1 snooze retired, #4338)."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    alias_pairs = (
        (
            "/api/undo/{session_id}/undo/{snapshot_id}",
            "/api/v1/undo/{session_id}/undo/{snapshot_id}",
        ),
        ("/api/undo/{session_id}/snapshots", "/api/v1/undo/{session_id}/snapshots"),
    )
    for legacy_path, canonical_path in alias_pairs:
        assert canonical_path in methods_by_path
        assert methods_by_path[canonical_path] == methods_by_path[legacy_path]


def test_retired_queue_routes_are_absent() -> None:
    """Native v2 queue-entry resources replace position/back/shuffle on every alias.

    Regression guard for the retired queue action surface (#4458): no Python
    handler may be re-registered for the legacy position/back/shuffle paths
    under either prefix, and the FastAPI OpenAPI document must not publish
    those operations again. ``PATCH /api/v2/queue-entries/{thread_id}`` with a
    target ``position`` and ``POST /api/v2/queue-orders`` (in
    ``native/contracts/v2-runtime.openapi.json``) are the replacement.
    """
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    for prefix in ("/api/queue", "/api/v1/queue"):
        assert f"{prefix}/threads/{{thread_id}}/position/" not in methods_by_path, (
            f"{prefix}/threads/{{thread_id}}/position/ must stay retired; "
            "PATCH /api/v2/queue-entries/{thread_id} is the replacement"
        )
        assert f"{prefix}/threads/{{thread_id}}/back/" not in methods_by_path, (
            f"{prefix}/threads/{{thread_id}}/back/ must stay retired; "
            "PATCH /api/v2/queue-entries/{thread_id} with position is the replacement"
        )
        assert f"{prefix}/shuffle/" not in methods_by_path, (
            f"{prefix}/shuffle/ must stay retired; "
            "POST /api/v2/queue-orders is the replacement"
        )

    schema = create_app(serve_frontend=False).openapi()
    for prefix in ("/api/queue", "/api/v1/queue"):
        assert f"{prefix}/threads/{{thread_id}}/position/" not in schema["paths"]
        assert f"{prefix}/threads/{{thread_id}}/back/" not in schema["paths"]
        assert f"{prefix}/shuffle/" not in schema["paths"]


def test_retired_thread_html_routes_are_absent() -> None:
    """Rust-first cutover excludes unused HTML handlers but retains the JSON listing."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)
    for prefix in ("/api/threads", "/api/v1/threads"):
        assert f"{prefix}/active" not in methods_by_path
        assert f"{prefix}/completed" not in methods_by_path
        assert f"{prefix}/active" not in app.openapi()["paths"]
        assert f"{prefix}/completed" not in app.openapi()["paths"]
    assert "/api/v1/threads/completed/threads" in methods_by_path


def test_pruned_admin_routes_are_absent() -> None:
    """Pruned admin import/export/delete handlers stay removed (#4861).

    The zero-browser admin surface was deleted with its router mounts.
    Re-adding any admin handler must fail here so the prune cannot regress
    silently. Health/ping/metrics are untouched and covered elsewhere.
    """
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    pruned_paths = (
        "/api/admin/import/csv/",
        "/api/v1/admin/import/csv/",
        "/api/admin/export/csv/",
        "/api/v1/admin/export/csv/",
        "/api/admin/export/json/",
        "/api/v1/admin/export/json/",
        "/api/admin/export/summary/",
        "/api/v1/admin/export/summary/",
        "/api/admin/delete-test-data/",
        "/api/v1/admin/delete-test-data/",
    )
    for path in pruned_paths:
        assert path not in methods_by_path, f"{path} must stay pruned"

    schema = create_app(serve_frontend=False).openapi()
    for path in pruned_paths:
        assert path not in schema["paths"], f"{path} must stay out of OpenAPI"


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


def test_pruned_debug_routes_are_absent() -> None:
    """Pruned debug log handlers stay removed (#4861).

    The non-production debug router was deleted; re-adding it must fail here.
    Eager health/ping/metrics routes are kept and covered by other tests.
    """
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    for path in ("/api/debug/log", "/api/v1/debug/log"):
        assert path not in methods_by_path, f"{path} must stay pruned"

    schema = create_app(serve_frontend=False).openapi()
    for path in ("/api/debug/log", "/api/v1/debug/log"):
        assert path not in schema["paths"], f"{path} must stay out of OpenAPI"


def test_retired_zero_browser_delivery_routes_are_absent() -> None:
    """Delivery HTTP API was pruned: the browser never calls it (#4865)."""
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    for path in (
        "/api/v1/delivery",
        "/api/v1/delivery/target/{owner}/{repo}/branch/{branch_name:path}",
    ):
        assert path not in methods_by_path


def test_no_new_bare_api_client_routes() -> None:
    """Regression guard: no client-facing routes under bare /api/* (non-v1)."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    # Grandfathered legacy bare /api/* routes. Extensions of an already-
    # grandfathered resource stay here when changing the prefix would break
    # existing clients.
    grandfathered_bare_api = frozenset(
        {
            "/api/auth/csrf",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/me",
            "/api/auth/refresh",
            "/api/auth/register",
            "/api/auth/forgot-password",
            "/api/auth/reset-password",
            "/api/bug-reports/",
            "/api/health",
            "/api/health/dependencies",
            "/api/health/live",
            "/api/health/warmup",
            "/api/instance/warm",
            "/api/ping",
            "/api/roll/bootstrap",
            "/api/roll/dismiss-pending",
            "/api/roll/override",
            "/api/roll/events/{event_id}/recommendation-explanation",
            "/api/sessions/",
            "/api/sessions/current/",
            "/api/sessions/{session_id}",
            "/api/sessions/{session_id}/details",
            "/api/sessions/{session_id}/restore-session-start",
            "/api/sessions/{session_id}/snapshots",
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
        if path.startswith("/api/v2/"):
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


def test_threads_collection_is_only_the_native_v2_resource() -> None:
    """The retired v1/bare Python collection no longer has an HTTP handler."""
    app = create_app(serve_frontend=False)
    methods_by_path = _collect_routes(app)

    # Creation remains a POST on the same prefix; only the collection read was
    # retired to the native v2 resource.
    assert "GET" not in methods_by_path["/api/v1/threads/"]
    assert "GET" not in methods_by_path["/api/threads/"]
    assert "POST" in methods_by_path["/api/v1/threads/"]
    assert "POST" in methods_by_path["/api/threads/"]
    assert "/api/v1/threads/stale" in methods_by_path


def test_retired_move_to_front_routes_are_absent() -> None:
    """Native queue-entry PATCH replaces both legacy move-to-front aliases."""
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    for prefix in ("/api/queue", "/api/v1/queue"):
        assert f"{prefix}/threads/{{thread_id}}/front/" not in methods_by_path


def test_retired_roll_skip_routes_are_absent() -> None:
    """Reroll (POST /api/v2/roll/offer) replaced skip and unskip on every alias.

    Regression guard for the retired skip surface: no Python handler may be
    re-registered for either legacy prefix, and the generated OpenAPI contract
    must not publish the operation again. Reroll is the only move-past action.
    """
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    for prefix in ("/api/roll", "/api/v1/roll"):
        assert f"{prefix}/skip" not in methods_by_path, (
            f"{prefix}/skip must not be re-added; Reroll (/api/v2/roll/offer) "
            "is the replacement"
        )
        assert f"{prefix}/skip/{{thread_id}}/unskip" not in methods_by_path, (
            f"{prefix}/skip/{{thread_id}}/unskip must not be re-added"
        )

    schema = create_app(serve_frontend=False).openapi()
    for path in ("/api/v1/roll/skip", "/api/roll/skip"):
        assert path not in schema["paths"], f"{path} must stay out of the OpenAPI contract"
    assert "/api/v1/roll/skip/{thread_id}/unskip" not in schema["paths"]


def test_pruned_python_analytics_routes_are_absent() -> None:
    """Pruned Python analytics handlers stay removed; native v2 is kept (#4861).

    The Python ``/api/analytics/metrics`` and ``/api/v1/analytics/metrics``
    handlers were deleted because no browser caller remains — the frontend
    uses the native Rust ``GET /api/v2/analytics/metrics`` resource (#4348).
    Eager ``/api/metrics`` and ``/api/v1/metrics`` are a different,
    retained surface covered by :func:`test_v1_metrics_alias_matches_legacy_route_methods`.
    """
    methods_by_path = _collect_routes(create_app(serve_frontend=False))
    for path in ("/api/analytics/metrics", "/api/v1/analytics/metrics"):
        assert path not in methods_by_path, f"{path} must stay pruned"

    schema = create_app(serve_frontend=False).openapi()
    for path in ("/api/analytics/metrics", "/api/v1/analytics/metrics"):
        assert path not in schema["paths"], f"{path} must stay out of OpenAPI"
