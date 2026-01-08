"""Test for bug fix: duplicate route handlers causing DB locks."""

import pytest


def test_no_duplicate_route_handlers():
    """Verify that no duplicate route handlers exist for the same endpoint.

    This test ensures that the bug causing DB locks from history interactions
    is fixed. Duplicate route handlers with the same path and method can cause
    FastAPI to behave unpredictably, leading to DB locks and app freezes.

    Bug: Task 127 - Prevent DB lock or app freeze from history interactions
    """
    from app.api.session import router
    from collections import defaultdict

    paths = defaultdict(list)
    for route in router.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            key = (route.path, frozenset(route.methods))  # type: ignore[arg-type]
            paths[key].append(route)

    duplicates = [
        (path, methods) for (path, methods), handlers in paths.items() if len(handlers) > 1
    ]

    assert len(duplicates) == 0, f"Found duplicate route handlers: {duplicates}"


def test_snapshots_route_returns_html():
    """Verify that the /sessions/{session_id}/snapshots route returns HTML.

    The history page expects HTML responses from this endpoint via HTMX.
    This test ensures the HTML handler is being used correctly.
    """
    from app.api.session import router
    from fastapi.responses import HTMLResponse

    for route in router.routes:
        if hasattr(route, "path") and "/{session_id}/snapshots" in route.path:  # type: ignore[attr-defined]
            assert route.response_class == HTMLResponse, (  # type: ignore[attr-defined]
                f"Expected HTMLResponse for {route.path}, got {route.response_class}"  # type: ignore[attr-defined]
            )
            return

    pytest.fail("Route /sessions/{session_id}/snapshots not found")
