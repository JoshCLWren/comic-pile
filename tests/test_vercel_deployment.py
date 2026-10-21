"""Regression tests for the production Vercel routing boundary."""

import json
from pathlib import Path
from typing import cast


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERCEL_CONFIG = REPOSITORY_ROOT / "vercel.json"
VERCEL_ENTRYPOINT = REPOSITORY_ROOT / "api" / "index.py"

# The SPA fallback and the prerendered route pages are static documents, so
# every one of them carries the same browser protections. Only the landing
# page is a crawl target and therefore the only one without `X-Robots-Tag`.
STATIC_SECURITY_HEADERS = {
    "Cache-Control": "public, max-age=0, must-revalidate",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-ComicPile-Frontend": "vercel-static",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
}
NOINDEX_ROBOTS_TAG = "noindex, nofollow"
CATCH_ALL_SOURCE = "/(.*)"


def _load_vercel_config() -> dict[str, object]:
    """Load the checked-in Vercel configuration.

    Returns:
        Parsed Vercel configuration.
    """
    return json.loads(VERCEL_CONFIG.read_text(encoding="utf-8"))


def _routes(config: dict[str, object]) -> list[dict[str, object]]:
    """Return the typed route list from a parsed Vercel configuration.

    Args:
        config: Parsed Vercel configuration.

    Returns:
        Ordered Vercel route definitions.
    """
    return cast("list[dict[str, object]]", config["routes"])


def _headers(route: dict[str, object]) -> dict[str, str]:
    """Return the response headers declared by one route.

    Args:
        route: A single Vercel route definition.

    Returns:
        The route's response headers, or an empty mapping when it declares none.
    """
    return cast("dict[str, str]", route.get("headers", {}))


def _spa_page_routes(routes: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return the routes that serve a prerendered SPA page.

    The API routes, the asset cache route, and the catch-all fallback are not
    prerendered pages and are excluded.

    Args:
        routes: Ordered Vercel route definitions.

    Returns:
        The routes that rewrite to a prerendered ``.html`` document.
    """
    pages = []
    for route in routes:
        source = route.get("src")
        destination = route.get("dest")
        if not isinstance(source, str) or not isinstance(destination, str):
            continue
        if source == CATCH_ALL_SOURCE:
            continue
        if source.startswith("/api") or source.startswith("/(?:openapi"):
            continue
        if not destination.endswith(".html"):
            continue
        pages.append(route)
    return pages


def test_vercel_builds_static_frontend_and_api_function_separately() -> None:
    """Ensure production builds independent static and Python outputs."""
    config = _load_vercel_config()
    builds = config["builds"]

    assert builds == [
        {"src": "api/index.py", "use": "@vercel/python"},
        {
            "src": "package.json",
            "use": "@vercel/static-build",
            "config": {"distDir": "static/react"},
        },
    ]
    entrypoint = VERCEL_ENTRYPOINT.read_text(encoding="utf-8")
    # The Vercel function must never serve the frontend (vercel.json builds the
    # SPA separately) and must keep the core/heavy router imports out of the
    # cold start, registering them on the first non-ping request instead.
    assert "serve_frontend=False" in entrypoint
    assert "defer_router_imports=True" in entrypoint


def test_vercel_routes_backend_before_spa_fallback() -> None:
    """Ensure API and documentation requests cannot be swallowed by the SPA."""
    routes = _routes(_load_vercel_config())

    assert routes[0]["src"] == "/api(?:/.*)?"
    assert routes[0]["dest"] == "/api/index.py"
    assert routes[1]["src"] == "/(?:openapi\\.json|docs|redoc|health)"
    assert routes[1]["dest"] == "/api/index.py"
    assert routes[2]["src"] == "/"
    assert routes[2]["dest"] == "/index.html"
    # The catch-all SPA fallback stays last, behind the filesystem handler.
    assert routes[-1]["src"] == CATCH_ALL_SOURCE
    assert routes[-1]["dest"] == "/index.html"
    assert {"handle": "filesystem"} in routes
    assert routes.index({"handle": "filesystem"}) < len(routes) - 1
    # The /assets/.+ cache headers route (added for edge caching) continues
    # instead of rewriting, so the filesystem handler still serves the asset.
    assets = next(route for route in routes if route.get("src") == "/assets/.+")
    assert assets["continue"] is True
    assert assets["headers"] == {
        "Cache-Control": "public, max-age=31536000, immutable"
    }
    assert routes.index(assets) < routes.index({"handle": "filesystem"})


def test_vercel_spa_pages_are_blocked_from_indexing() -> None:
    """Only the landing page may be crawled; every other page is noindex."""
    routes = _routes(_load_vercel_config())
    pages = _spa_page_routes(routes)

    landing = next(route for route in pages if route.get("src") == "/")
    assert "X-Robots-Tag" not in _headers(landing)

    for route in pages:
        if route.get("src") == "/":
            continue
        headers = _headers(route)
        assert headers.get("X-Robots-Tag") == NOINDEX_ROBOTS_TAG, route.get("src")
        for name, value in STATIC_SECURITY_HEADERS.items():
            assert headers.get(name) == value, f"{route.get('src')}: {name}"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_vercel_spa_pages_serve_their_own_prerendered_document() -> None:
    """Each prerendered page must be served from its own generated file."""
    pages = _spa_page_routes(_routes(_load_vercel_config()))

    for route in pages:
        source = cast("str", route["src"])
        destination = cast("str", route["dest"])
        expected = "/index.html" if source == "/" else f"{source}.html"
        assert destination == expected, source


def test_vercel_catch_all_fallback_blocks_indexing() -> None:
    """The SPA fallback must not turn unknown paths into crawlable pages."""
    routes = _routes(_load_vercel_config())
    catch_all = routes[-1]

    assert catch_all["src"] == CATCH_ALL_SOURCE
    assert catch_all["dest"] == "/index.html"
    assert _headers(catch_all).get("X-Robots-Tag") == NOINDEX_ROBOTS_TAG


def test_static_html_exposes_routing_evidence_and_security_headers() -> None:
    """Ensure static HTML remains identifiable and receives browser protections."""
    routes = _routes(_load_vercel_config())
    pages = _spa_page_routes(routes)

    for route in [*pages, routes[-1]]:
        headers = _headers(route)
        assert headers["X-ComicPile-Frontend"] == "vercel-static"
        assert headers["Cache-Control"] == "public, max-age=0, must-revalidate"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
