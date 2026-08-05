"""Regression coverage for dependency-group route precedence."""

from starlette.routing import Match

from app.api.dependency_group import router


def test_thread_group_lookup_is_not_shadowed_by_group_id_route() -> None:
    """Route the Roll lookup to its static endpoint before dynamic group IDs."""
    scope = {
        "type": "http",
        "path": "/reading-order-groups/threads/42/groups",
        "method": "GET",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "http_version": "1.1",
    }

    full_matches = [
        route
        for route in router.routes
        if route.matches(scope)[0] is Match.FULL
    ]

    assert full_matches
    assert full_matches[0].name == "list_thread_groups"
