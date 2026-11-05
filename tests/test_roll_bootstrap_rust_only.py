"""Keep the retired Python Roll bootstrap surface from silently returning.

The public v2 bootstrap belongs to the native Rust Vercel handler, not FastAPI.
These assertions deliberately do not require an authenticated Rust fixture.
"""

import json
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app
from app.repositories import roll_repository
from app.schemas import roll as roll_schemas
from app.services.roll_service import RollService


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


def test_python_bootstrap_projection_stays_deleted() -> None:
    """Do not resurrect the retired Python bootstrap read model (#4350).

    The Python v1 projection had no live caller once both clients moved to the
    Rust v2 resource. Deleting it is only durable if reintroduction fails here
    rather than silently re-adding query code no route serves.
    """
    assert not hasattr(roll_schemas, "RollBootstrapResponse")
    assert not hasattr(roll_schemas, "RollBootstrapThread")
    assert not hasattr(RollService, "load_bootstrap_thread_data")
    assert [
        name for name in dir(roll_repository) if name.startswith("fetch_bootstrap_")
    ] == []


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


def test_frontend_bootstrap_and_recovery_call_only_v2_rust_route() -> None:
    """The Roll screen and the protected mutation refresh cannot resurrect v1."""
    root = Path(__file__).resolve().parents[1]
    for path in (
        "frontend/src/services/rollBootstrapApi.ts",
        "frontend/src/services/protectedRollMutationApi.ts",
    ):
        source = (root / path).read_text()
        assert "'/v2/roll/bootstrap'" in source, path
        assert "'/v1/roll/bootstrap'" not in source, path
        assert "'/roll/bootstrap'" not in source, path
    acceptance = (root / "frontend/src/test/reading-mode-acceptance.spec.ts").read_text()
    assert "fetch('/api/v2/roll/bootstrap'" in acceptance
    assert "page.request.get('/api/roll/bootstrap'" not in acceptance
    assert "page.request.get('/api/v1/roll/bootstrap'" not in acceptance
    native = (root / "native/roll-service/src/lib.rs").read_text()
    assert '.route("/api/v2/roll/bootstrap", get(bootstrap::bootstrap_v2))' in native
