"""Regression tests for the production Vercel routing boundary."""

import json
import re
from pathlib import Path
from typing import cast


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERCEL_CONFIG = REPOSITORY_ROOT / "vercel.json"
VERCEL_ENTRYPOINT = REPOSITORY_ROOT / "api" / "index.py"
ROUTE_SEO_TABLE_MODULE = REPOSITORY_ROOT / "frontend" / "src" / "seo" / "routeSeo.ts"

# Every served HTML response route must carry the browser-protection header set
# that the landing and SPA fallback routes already apply, on top of caching.
HTML_SECURITY_HEADERS = {
    "Cache-Control": "public, max-age=0, must-revalidate",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https:; font-src 'self' "
        "https://fonts.gstatic.com; connect-src 'self' "
        "https://fonts.googleapis.com; frame-ancestors 'none'; form-action "
        "'self'; base-uri 'self'; frame-src 'none';"
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-ComicPile-Frontend": "vercel-static",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
}
NOINDEX_ROBOTS_HEADERS = {"X-Robots-Tag": "noindex, nofollow"}
ROUTE_SEO_PATTERN_RE = re.compile(r"pattern: '(/[^']*)'")

# Paths that match parameterized RouteSeoTable entries (see routeSeo.ts).
# The build's HTML generator skips them, so they must fall through the
# filesystem handler into the SPA fallback route instead of serving a
# generated static file that never exists.
DYNAMIC_ROUTE_PROBES = (
    "/thread/17938",
    "/threads/17938",
    "/creators/ultimate-spider-man",
    "/crossovers/civil-war-reading-order",
    "/continuity-plans/7",
    "/continuity-plans/7/edit",
    "/sessions/12345",
)


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
    """Return the route's header map.

    Args:
        route: A Vercel route definition.

    Returns:
        The route's headers dictionary.
    """
    return cast("dict[str, str]", route["headers"])


def _generated_route_html_pages() -> frozenset[str]:
    """Page slugs whose ``<route>.html`` file the build generates.

    The Vite build's ``closeBundle`` hook generates one HTML file per
    non-parameterized route from ``frontend/src/seo/routeSeo.ts``. The landing
    ``/`` entry becomes ``index.html``, which the existing ``/`` route already
    serves, so it is excluded here.

    Returns:
        Slugs such as ``"login"`` or ``"creators/compare"``.
    """
    source = ROUTE_SEO_TABLE_MODULE.read_text(encoding="utf-8")
    pages: set[str] = set()
    for match in ROUTE_SEO_PATTERN_RE.finditer(source):
        pattern = match.group(1)
        if pattern != "/" and ":" not in pattern:
            pages.add(pattern.lstrip("/"))
    return frozenset(pages)


def _route_html_src_pattern() -> str:
    """Build the exact route-HTML ``src`` regex the Vercel config must carry.

    The configuration spells out one static alternative per generated page so
    the routing layer mirrors the HTML generator. Sorted order keeps the
    generated expectation deterministic.

    Returns:
        The anchored, un-escaped regex source string.
    """
    pages = "|".join(sorted(_generated_route_html_pages()))
    return f"/({pages})(\\.html)?"


def _route_html_rule() -> dict[str, object]:
    """Return the exact Vercel route definition that serves generated pages.

    Returns:
        The complete route-HTML routing rule.
    """
    return {
        "src": _route_html_src_pattern(),
        "dest": "/$1.html",
        "headers": {**HTML_SECURITY_HEADERS, **NOINDEX_ROBOTS_HEADERS},
    }


def test_vercel_builds_static_frontend_and_api_function_separately() -> None:
    """Ensure production builds independent static, Rust, Node, and Python outputs."""
    config = _load_vercel_config()
    builds = config["builds"]

    assert builds == [
        {
            "src": "api/index.py",
            "use": "@vercel/python",
            "config": {"excludeFiles": "{target/**,native/**/target/**}"},
        },
        {"src": "api/native_roll.rs", "use": "@vercel/rust"},
        {"src": "api/auth/me.ts", "use": "@vercel/node"},
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

    assert routes[0] == {
        "src": "/api/v1/auth/me",
        "methods": ["GET"],
        "dest": "/api/auth/me.ts",
    }
    assert routes[1] == {
        "src": "/api/_native_roll/health",
        "methods": ["GET"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[2] == {
        "src": "/api/v2/roll/bootstrap",
        "methods": ["GET"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[3] == {
        "src": "/api/v2/roll/dice-command",
        "methods": ["POST"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[4] == {
        "src": "/api/v2/roll/offer",
        "methods": ["POST"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[5] == {
        "src": "/api/v2/roll/reset",
        "methods": ["POST"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[6] == {
        "src": "/api/v1/roll/dismiss-pending",
        "methods": ["POST"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[7] == {
        "src": "/api/roll/dismiss-pending",
        "methods": ["POST"],
        "dest": "/api/native_roll.rs",
    }
    assert routes[8] == {"src": "/api(?:/.*)?", "dest": "/api/index.py"}
    assert routes[9] == {
        "src": "/(?:openapi\\.json|docs|redoc|health)",
        "dest": "/api/index.py",
    }
    assert routes[10]["src"] == "/"
    assert routes[10]["dest"] == "/index.html"
    # Route 10 is the /assets/.+ cache headers route (added for edge caching)
    assert routes[11] == {
        "src": "/assets/.+",
        "continue": True,
        "headers": {"Cache-Control": "public, max-age=31536000, immutable"},
    }
    # Route 11 serves the build's generated route HTML pages (see
    # test_vercel_route_html_rule_serves_every_generated_page).
    assert routes[12] == _route_html_rule()
    assert routes[13] == {"handle": "filesystem"}
    assert routes[-1]["src"] == "/(.*)"
    assert routes[-1]["dest"] == "/index.html"


def test_static_html_exposes_routing_evidence_and_security_headers() -> None:
    """Ensure static HTML remains identifiable and receives browser protections."""
    routes = _routes(_load_vercel_config())

    for route in (routes[10], routes[12], routes[-1]):
        headers = _headers(route)
        assert headers["X-ComicPile-Frontend"] == "vercel-static"
        assert headers["Cache-Control"] == "public, max-age=0, must-revalidate"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert headers["Strict-Transport-Security"] == (
            "max-age=63072000; includeSubDomains; preload"
        )
        assert headers["X-XSS-Protection"] == "1; mode=block"

    # Only the landing route is indexable; every other HTML response the
    # routing layer serves must state its non-indexability.
    landing_headers = _headers(routes[10])
    assert "X-Robots-Tag" not in landing_headers
    for route in (routes[12], routes[-1]):
        assert _headers(route)["X-Robots-Tag"] == "noindex, nofollow"


def test_vercel_route_html_rule_serves_every_generated_page() -> None:
    """Every generated route page is served at its published location.

    The build publishes ``static/react`` at the site root, so ``/login`` maps
    to ``/login.html`` (not ``/static/react/login.html``), and nested pages
    such as ``/creators/compare`` map to ``/creators/compare.html``.
    """
    routes = _routes(_load_vercel_config())
    html_rule = routes[12]

    assert html_rule == _route_html_rule()

    src_pattern = str(html_rule["src"])
    pages = _generated_route_html_pages()
    assert pages, "route SEO table must contain static route pages"
    for page in sorted(pages):
        for path in (f"/{page}", f"/{page}.html"):
            matched = re.fullmatch(src_pattern, path)
            assert matched is not None, f"{path} must serve the generated {page}.html"
            assert matched.group(1) == page, path


def test_vercel_route_html_rule_lists_exactly_the_generated_alternatives() -> None:
    """No stale or missing static alternatives are configured.

    The rule is anchored without wildcards, so a listed static page that the
    HTML generator no longer produces would 404 instead of falling back to the
    SPA. This assertion fails the configuration change in both directions.
    """
    routes = _routes(_load_vercel_config())
    src_pattern = str(routes[12]["src"])
    suffix = ")(\\.html)?"

    assert src_pattern.startswith("/(")
    assert src_pattern.endswith(suffix)
    configured_alternatives = set(src_pattern[2:-len(suffix)].split("|"))
    generated_pages = _generated_route_html_pages()

    assert configured_alternatives == generated_pages


def test_vercel_dynamic_route_pages_fall_through_to_the_spa_fallback() -> None:
    """Parameterized pages keep the app fallback and SPA noindex robots header."""
    routes = _routes(_load_vercel_config())
    src_pattern = str(routes[12]["src"])

    for path in DYNAMIC_ROUTE_PROBES:
        matched = re.fullmatch(src_pattern, path)
        assert matched is None, f"{path} must fall through to the SPA, not a static file"

    assert routes[13] == {"handle": "filesystem"}
    fallback = routes[-1]
    assert fallback["src"] == "/(.*)"
    assert fallback["dest"] == "/index.html"
    assert _headers(fallback)["X-Robots-Tag"] == "noindex, nofollow"


_RELATIVE_MODULE_SPECIFIER_RE = re.compile(
    r"""(?:from|import)\s+['"](\.[^'"]+)['"]""",
)


def test_vercel_node_typescript_relative_imports_use_js_extensions() -> None:
    """Node ESM on Vercel cannot load extensionless relative imports.

    ``@vercel/node`` compiles ``api/auth/me.ts`` to ``me.js`` and leaves import
    specifiers intact. With ``"type": "module"``, ``from '../src/auth'`` becomes
    ``ERR_MODULE_NOT_FOUND`` for ``/var/task/api/src/auth`` (issue #4295).
    """
    offenders: list[str] = []
    api_root = REPOSITORY_ROOT / "api"
    for source in sorted(api_root.rglob("*.ts")):
        if "node_modules" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        for match in _RELATIVE_MODULE_SPECIFIER_RE.finditer(text):
            specifier = match.group(1)
            if not specifier.endswith(".js"):
                relative = source.relative_to(REPOSITORY_ROOT)
                offenders.append(f"{relative}: {specifier}")
    assert offenders == [], (
        "Vercel Node ESM requires relative imports to use .js extensions; "
        + "; ".join(offenders)
    )


def test_node_auth_route_is_isolated_from_python_and_static_routes() -> None:
    """Keep auth GET in Node, native probe GET in Rust, and other APIs in Python."""
    routes = _routes(_load_vercel_config())
    probes = (
        ("GET", "/api/v1/auth/me", "/api/auth/me.ts"),
        ("POST", "/api/v1/auth/me", "/api/index.py"),
        ("POST", "/api/v1/auth/refresh", "/api/index.py"),
        ("GET", "/api/v1/roll/bootstrap", "/api/index.py"),
        ("GET", "/api/_native_roll/bootstrap", "/api/index.py"),
        ("GET", "/api/v2/roll/bootstrap", "/api/native_roll.rs"),
        ("POST", "/api/v2/roll/bootstrap", "/api/index.py"),
        ("POST", "/api/v2/roll/dice-command", "/api/native_roll.rs"),
        ("POST", "/api/v2/roll/offer", "/api/native_roll.rs"),
        ("POST", "/api/v2/roll/reset", "/api/native_roll.rs"),
        ("GET", "/api/_native_roll/health", "/api/native_roll.rs"),
        ("POST", "/api/_native_roll/health", "/api/index.py"),
        ("GET", "/api/v2/reading-boundaries", "/api/index.py"),
        ("GET", "/health", "/api/index.py"),
        ("GET", "/", "/index.html"),
    )
    for method, path, expected in probes:
        for route in routes:
            if "src" not in route:
                continue
            methods = cast("list[str]", route.get("methods", [method]))
            if method not in methods:
                continue
            if re.fullmatch(str(route["src"]), path):
                assert route.get("dest") == expected, (method, path)
                break
        else:
            raise AssertionError(f"No route for {method} {path}")
