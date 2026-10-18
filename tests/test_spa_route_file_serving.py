"""Regression tests for route-specific SPA HTML file selection (issue #3485).

The FastAPI SPA fallback serves a generated ``static/react/<route>.html`` when
one exists so crawlers receive route-specific title, description, canonical,
and robots metadata. These tests pin the path-to-file mapping itself, including
the rejection of request paths that could escape the build directory.
"""

from pathlib import Path

from app.main import _spa_route_file_path


def test_root_maps_to_landing_index() -> None:
    """The landing path resolves to the SPA index, not a generated file."""
    assert _spa_route_file_path("/") == Path("static/react/index.html")
    assert _spa_route_file_path("") == Path("static/react/index.html")


def test_route_path_maps_to_generated_route_file() -> None:
    """A normal route resolves to its generated file, with or without slash."""
    assert _spa_route_file_path("/queue") == Path("static/react/queue.html")
    assert _spa_route_file_path("queue") == Path("static/react/queue.html")
    assert _spa_route_file_path("/queue/") == Path("static/react/queue.html")


def test_legit_route_file_stays_inside_build_dir() -> None:
    """The generated-file candidate never leaves ``static/react``."""
    candidate = _spa_route_file_path("/queue")
    build_dir = Path("static/react")
    assert candidate.resolve().is_relative_to(build_dir.resolve())


def test_traversal_request_paths_fall_back_to_spa_index() -> None:
    """Dot segments cannot escape the build directory and serve other files.

    A crafted request such as ``/../../frontend/dice-playground`` would
    otherwise resolve to ``frontend/dice-playground.html`` outside
    ``static/react``. Every unsafe shape falls back to the SPA index, matching
    the behavior for any route without a generated file.
    """
    unsafe_paths = (
        "/../frontend/dice-playground",
        "../../frontend/dice-playground",
        "/queue/../../secret",
        "/queue/./asset",
        "/queue\\..\\escape",
        "/a//b",
    )
    for request_path in unsafe_paths:
        assert _spa_route_file_path(request_path) == Path("static/react/index.html"), request_path
