"""Keep the retired Python Roll bootstrap GETs from silently returning.

The public v2 bootstrap belongs to the native Rust Vercel handler, not FastAPI.
These assertions deliberately do not require an authenticated Rust fixture.
"""

import json
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app


BOOTSTRAP_PATHS = (
    "/api/roll/bootstrap",
    "/api/v1/roll/bootstrap",
    "/api/v2/roll/bootstrap",
)


def test_python_exposes_no_roll_bootstrap_get_handlers() -> None:
    """Do not reinstate a Python fallback through any versioned alias."""
    matches = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path in BOOTSTRAP_PATHS
        and "GET" in (route.methods or set())
    ]
    assert matches == []
    paths = app.openapi()["paths"]
    for path in BOOTSTRAP_PATHS:
        assert "get" not in paths.get(path, {})


def test_public_v2_bootstrap_routes_to_native_rust() -> None:
    """The only supported bootstrap ingress targets the Rust function."""
    config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
    matching = [
        route
        for route in config["routes"]
        if route.get("src") == "/api/v2/roll/bootstrap"
    ]
    assert matching == [
        {
            "src": "/api/v2/roll/bootstrap",
            "methods": ["GET"],
            "dest": "/api/native_roll.rs",
        }
    ]
