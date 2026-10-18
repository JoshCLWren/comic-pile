"""Regression tests for the production Vercel SEO routing contract (issue #3905).

Issue #3905 found that per-route HTML metadata files were built and deployed but
never served: the Vercel catch-all sent every non-file path to ``/index.html``,
so authenticated routes returned the indexable landing page head and no
``noindex`` header even though FastAPI handled them correctly.

These tests run against the *actual* ``vercel.json`` routing config rather than
FastAPI, so a future edit that revives the catch-all-to-``index.html`` bug fails
CI instead of silently shipping. They cross-check ``vercel.json`` against the
canonical route indexability table in ``frontend/src/seo/routeSeo.ts`` and the
shared noindex fallback shell produced by
``frontend/scripts/generate-route-html.mjs``.
"""

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERCEL_CONFIG = REPOSITORY_ROOT / "vercel.json"
ROUTE_SEO_SOURCE = REPOSITORY_ROOT / "frontend" / "src" / "seo" / "routeSeo.ts"
ROUTE_HTML_SCRIPT = REPOSITORY_ROOT / "frontend" / "scripts" / "generate-route-html.mjs"
MAIN_SOURCE = REPOSITORY_ROOT / "app" / "main.py"

NOINDEX = "noindex, nofollow"


def _routes() -> list[dict[str, object]]:
    """Return the ordered route list from ``vercel.json``.

    Returns:
        Parsed route definitions.
    """
    config = json.loads(VERCEL_CONFIG.read_text(encoding="utf-8"))
    routes = config["routes"]
    assert isinstance(routes, list)
    return routes


def _non_parameterized_route_patterns() -> list[str]:
    """Return every literal (non-parameterized) route pattern in the SEO table.

    Returns:
        Route patterns without ``:param`` segments and without the fallback ``*``.
    """
    source = ROUTE_SEO_SOURCE.read_text(encoding="utf-8")
    patterns = re.findall(r"pattern:\s*'([^']+)'", source)
    return [p for p in patterns if p != "*" and ":" not in p]


def _route_html_rewrite() -> dict[str, object]:
    """Return the ``<route>.html`` rewrite route from ``vercel.json``.

    Returns:
        The single route whose destination template is ``/$1.html``.

    Raises:
        AssertionError: If the route is absent or not unique.
    """
    matches = [route for route in _routes() if route.get("dest") == "/$1.html"]
    assert len(matches) == 1, f"expected exactly one /$1.html route, found {len(matches)}"
    return matches[0]


def _header_value(route: dict[str, object], name: str) -> str | None:
    """Return a header value from a route definition.

    Args:
        route: A parsed Vercel route.
        name: Header name.

    Returns:
        The header value, or ``None`` when absent.
    """
    headers = route.get("headers")
    assert isinstance(headers, dict)
    value = headers.get(name)
    return value if isinstance(value, str) else None


def test_route_html_rewrite_covers_every_non_parameterized_route() -> None:
    """Every literal route must be rewritten to its generated ``.html`` file."""
    route = _route_html_rewrite()
    source_regex = route["src"]
    assert isinstance(source_regex, str)

    missing: list[str] = []
    for pattern in _non_parameterized_route_patterns():
        if pattern == "/":
            # The landing page has its own route entry pointing at /index.html.
            assert any(r.get("src") == "/" and r.get("dest") == "/index.html" for r in _routes())
            continue
        match = re.fullmatch(source_regex, pattern)
        if match is None:
            missing.append(pattern)
            continue
        # The destination template must resolve to the file generate-route-html
        # writes: `<pattern without leading slash>.html`.
        assert f"/{match.group(1)}.html" == f"{pattern}.html", pattern

    assert missing == [], f"routes not served a route-specific HTML file: {missing}"


def test_parameterized_and_unknown_paths_fall_through_to_the_noindex_shell() -> None:
    """Parameterized and unknown paths must not match the route-file rewrite regex."""
    route = _route_html_rewrite()
    source_regex = route["src"]
    assert isinstance(source_regex, str)

    for path in (
        "/thread/17938",
        "/threads/17938",
        "/sessions/abc",
        "/creators/some-creator",
        "/crossovers/age-of-apocalypse",
        "/continuity-plans/7",
        "/continuity-plans/7/edit",
        "/not-a-declared-route",
    ):
        assert re.fullmatch(source_regex, path) is None, path


def test_non_parameterized_route_files_send_noindex() -> None:
    """Served route-specific HTML must opt out of indexing at the HTTP layer."""
    route = _route_html_rewrite()
    assert _header_value(route, "X-Robots-Tag") == NOINDEX


def test_catch_all_serves_the_noindex_fallback_shell_not_the_landing_page() -> None:
    """The catch-all must serve the noindex shell, never indexable ``index.html``."""
    routes = _routes()
    catch_all = routes[-1]
    assert catch_all["src"] == "/(.*)"
    assert catch_all["dest"] == "/spa.html"
    assert _header_value(catch_all, "X-Robots-Tag") == NOINDEX


def test_landing_page_remains_the_only_indexable_static_html() -> None:
    """Only `/` may be served the indexable landing page without a noindex header."""
    routes = _routes()
    landing = routes[2]
    assert landing["src"] == "/"
    assert landing["dest"] == "/index.html"
    assert _header_value(landing, "X-Robots-Tag") is None


def test_route_file_rewrite_precedes_the_filesystem_boundary() -> None:
    """Route rewrites must run before filesystem/catch-all routing."""
    routes = _routes()
    route_file_index = next(i for i, r in enumerate(routes) if r.get("dest") == "/$1.html")
    filesystem_index = next(i for i, r in enumerate(routes) if r.get("handle") == "filesystem")
    assert route_file_index < filesystem_index
    assert filesystem_index < len(routes) - 1


def test_fallback_shell_filename_is_consistent_across_layers() -> None:
    """The build script, FastAPI, and Vercel must agree on the shell file name."""
    main_source = MAIN_SOURCE.read_text(encoding="utf-8")
    script_source = ROUTE_HTML_SCRIPT.read_text(encoding="utf-8")

    assert '_SPA_FALLBACK_SHELL_FILENAME = "spa.html"' in main_source
    assert "SPA_FALLBACK_FILENAME = 'spa.html'" in script_source
    assert _routes()[-1]["dest"] == "/spa.html"
