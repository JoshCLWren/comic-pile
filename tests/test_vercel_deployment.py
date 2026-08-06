"""Regression tests for the production Vercel routing boundary."""

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERCEL_CONFIG = REPOSITORY_ROOT / "vercel.json"
VERCEL_ENTRYPOINT = REPOSITORY_ROOT / "api" / "index.py"


def _load_vercel_config() -> dict[str, object]:
    """Load the checked-in Vercel configuration.

    Returns:
        Parsed Vercel configuration.
    """
    return json.loads(VERCEL_CONFIG.read_text(encoding="utf-8"))


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
    assert "create_app(serve_frontend=False)" in VERCEL_ENTRYPOINT.read_text(encoding="utf-8")


def test_vercel_routes_backend_before_spa_fallback() -> None:
    """Ensure API and documentation requests cannot be swallowed by the SPA."""
    config = _load_vercel_config()
    routes = config["routes"]

    assert routes[0] == {"src": "/api(?:/.*)?", "dest": "/api/index.py"}
    assert routes[1] == {
        "src": "/(?:openapi\\.json|docs|redoc|health)",
        "dest": "/api/index.py",
    }
    assert routes[2]["src"] == "/"
    assert routes[2]["dest"] == "/index.html"
    assert routes[3] == {"handle": "filesystem"}
    assert routes[-1]["src"] == "/(.*)"
    assert routes[-1]["dest"] == "/index.html"


def test_static_html_exposes_routing_evidence_and_security_headers() -> None:
    """Ensure static HTML remains identifiable and receives browser protections."""
    config = _load_vercel_config()
    routes = config["routes"]

    for route in (routes[2], routes[-1]):
        headers = route["headers"]
        assert headers["X-ComicPile-Frontend"] == "vercel-static"
        assert headers["Cache-Control"] == "public, max-age=0, must-revalidate"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
