"""Regression tests for route-specific SPA HTML file selection (issue #3485).

The FastAPI SPA fallback serves a generated ``static/react/<route>.html`` when
one exists so crawlers receive route-specific title, description, canonical,
and robots metadata. These tests pin the path-to-file mapping itself, including
the rejection of request paths that could escape the build directory.
"""

from pathlib import Path

import pytest

from app.main import _spa_route_file_path, _spa_serve_path


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


def _write_build(tmp_path: Path) -> None:
    """Create a minimal ``static/react`` build directory in ``tmp_path``."""
    build = tmp_path / "static" / "react"
    build.mkdir(parents=True)
    (build / "index.html").write_text("<html>landing</html>")
    (build / "spa.html").write_text("<html>shell</html>")
    (build / "queue.html").write_text("<html>queue</html>")


def test_serve_path_prefers_route_specific_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated route file wins over the shared fallback shell."""
    _write_build(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert _spa_serve_path("/queue") == Path("static/react/queue.html")
    assert _spa_serve_path("queue") == Path("static/react/queue.html")


def test_serve_path_uses_noindex_shell_for_param_and_unknown_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parameterized and unknown paths are served the noindex shell, not index.html."""
    _write_build(tmp_path)
    monkeypatch.chdir(tmp_path)

    for request_path in ("/thread/42", "/threads/42", "/not-a-declared-route", "/cbl-sources-typo"):
        assert _spa_serve_path(request_path) == Path("static/react/spa.html"), request_path


def test_serve_path_keeps_landing_page_on_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The indexable landing page must never resolve to the noindex shell."""
    _write_build(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert _spa_serve_path("/") == Path("static/react/index.html")
    assert _spa_serve_path("") == Path("static/react/index.html")


def test_serve_path_falls_back_to_index_without_a_generated_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Builds without the fallback shell still answer every SPA path."""
    build = tmp_path / "static" / "react"
    build.mkdir(parents=True)
    (build / "index.html").write_text("<html>landing</html>")
    monkeypatch.chdir(tmp_path)

    assert _spa_serve_path("/thread/42") == Path("static/react/index.html")
    assert _spa_serve_path("/") == Path("static/react/index.html")
