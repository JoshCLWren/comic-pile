"""Guard: the retired session-lifecycle v1 routes stay retired (#4343).

Owner directive (2026-11-18): ``GET /api/v1/sessions/current/`` and
``POST /api/v1/sessions/{session_id}/restore-session-start`` are retired, not
ported. Sessionless Roll replaces the current-session concept with
event-derived state, and restoring a session-start snapshot conflicts with the
event-based activity, rating-correction and Reset Dice model. Historical event
and session data is untouched.
"""

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FRAGMENT = REPO_ROOT / "docs" / "api" / "route-fragments" / "sessions.json"

RETIRED_OPERATIONS = (
    ("GET", "/api/v1/sessions/current/"),
    ("GET", "/api/sessions/current/"),
    ("POST", "/api/v1/sessions/{session_id}/restore-session-start"),
    ("POST", "/api/sessions/{session_id}/restore-session-start"),
)
RETIRED_SEGMENTS = ("/current", "/restore-session-start")


def _operations(routes: list[object], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield method/path pairs through FastAPI's included-router tree."""
    for route in routes:
        if isinstance(route, APIRoute):
            for method in route.methods or ():
                yield method, prefix + route.path
            continue
        original_router = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original_router is not None and context is not None:
            yield from _operations(original_router.routes, prefix + context.prefix)


def test_python_app_does_not_register_retired_session_lifecycle_routes() -> None:
    """Python serves neither retired route, with or without a trailing slash."""
    operations = set(_operations(list(create_app(serve_frontend=False).routes)))
    assert operations.isdisjoint(RETIRED_OPERATIONS), sorted(operations & set(RETIRED_OPERATIONS))
    offenders = sorted(
        (method, path)
        for method, path in operations
        if "/sessions" in path and path.rstrip("/").endswith(RETIRED_SEGMENTS)
    )
    assert offenders == []


def test_openapi_schema_does_not_publish_retired_session_lifecycle_routes() -> None:
    """The generated contract never advertises the retired operations."""
    schema = create_app(serve_frontend=False).openapi()
    published = {path.rstrip("/") for path in schema["paths"]}
    assert not any(path.endswith(RETIRED_SEGMENTS) and "/sessions" in path for path in published)


def test_sessions_route_fragment_has_no_retired_lifecycle_entries() -> None:
    """The routing source fragment carries no exception for the retired routes."""
    operations = json.loads(SESSIONS_FRAGMENT.read_text(encoding="utf-8"))["operations"]
    retired = {(method, path) for method, path in RETIRED_OPERATIONS}
    declared = {(operation["method"], operation["path"]) for operation in operations}
    assert declared.isdisjoint(retired), sorted(declared & retired)
    for operation in operations:
        assert "restore-session-start" not in operation["src"], operation
        assert "sessions/current" not in operation["src"], operation
