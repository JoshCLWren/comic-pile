"""Test for bug fix: duplicate route handlers causing DB locks."""


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
            key = (str(route.path), frozenset(route.methods))
            paths[key].append(route)

    duplicates = [
        (path, methods) for (path, methods), handlers in paths.items() if len(handlers) > 1
    ]

    assert len(duplicates) == 0, f"Found duplicate route handlers: {duplicates}"
