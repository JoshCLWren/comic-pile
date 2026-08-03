"""Tests for the API route prefix convention and the sessions alias (issue #376).

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

from httpx import AsyncClient

from app.main import create_app


# Routes that are intentionally mounted under bare /api/* as non-production
# tooling, not client APIs. These are exempt from the "no new bare /api/*"
# convention. See the comment in app/main.py.
_BARE_API_EXCEPTIONS = frozenset(
    {
        "/api/debug/log",
        "/api/test/sessions/expire",
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


def test_no_new_bare_api_client_routes() -> None:
    """Regression guard: no client-facing routes under bare /api/* (non-v1)."""
    app = create_app(serve_frontend=False)

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
            "/api/admin/import/reviews/",
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
            "/api/roll/set-die",
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
            "/api/threads/{thread_id}/reviews",
            "/api/threads/{thread_id}/set-pending",
            "/api/threads/{thread_id}/test-backdate",
            "/api/threads/{thread_id}:migrateToIssues",
            "/api/threads/{thread_id}:migrateToIssuesSimple",
            "/api/tasks/",
            "/api/tasks/ready",
            "/api/tasks/metrics",
            "/api/undo/{session_id}/snapshots",
            "/api/undo/{session_id}/undo/{snapshot_id}",
            "/api/{path:path}",
        }
    )

    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
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
