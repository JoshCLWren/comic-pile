"""Regression coverage for the cold-import budget on the API entry path (#2978).

The Vercel Fluid function pays for every module it imports before it can answer
``/api/ping``. These tests pin the contracts that keep that cheap:

* ``app.api`` composes nothing at import time (no eager router imports);
* a cold entry-path start registers only the lightweight routers, and the first
  non-ping request completes the route table without letting the ``/api/*`` 404
  fallback shadow the deferred routers; and
* ``app.main`` does not construct an application merely by being imported, so
  ``api/index.py`` no longer builds a second, frontend-serving app.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import dependency
from app.main import create_app, get_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_PACKAGE_INIT = REPOSITORY_ROOT / "app" / "api" / "__init__.py"
ENTRY_PATH = REPOSITORY_ROOT / "api" / "index.py"

#: Modules that must stay unimported until a non-ping request needs them.
DEFERRED_ROUTER_MODULES = (
    "app.api.roll",
    "app.api.thread",
    "app.api.session",
    "app.api.continuity_plan",
    "app.api.continuity_rule",
    "app.api.releases",
    "app.api.roll_recovery_switch",
)

#: Dependency sub-router route reachable only once the sub-routers are composed.
#: Regression guard for the 404s an out-of-order ``include_router`` produced:
#: ``FastAPI.include_router`` snapshots routes when it is called, so composition
#: has to happen before the router is copied into the application.
DEPENDENCY_SUBROUTER_PATH = "/api/v1/reading-order-groups/"
RELEASES_SUBROUTER_PATH = "/api/v1/releases/"
API_FALLBACK_PATH = "/api/{path:path}"


def _loaded_modules(bootstrap: str) -> set[str]:
    """Import a module in a fresh interpreter and report ``sys.modules``.

    Args:
        bootstrap: Python source that performs the import.

    Returns:
        Module names loaded after the import.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; {bootstrap}; print('\\n'.join(sorted(sys.modules)))",
        ],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        check=True,
    )

    return set(result.stdout.split())


def _imported_api_modules() -> set[str]:
    """Return the modules loaded by importing ``app.api`` alone."""
    return _loaded_modules("import app.api")


def _imported_entry_path_modules() -> set[str]:
    """Return the modules loaded by importing the Vercel entry path."""
    return _loaded_modules("import sys; sys.path.insert(0, 'api'); import index")


def _deferred_leaks(loaded: set[str]) -> set[str]:
    """Return the deferred router modules that are already imported."""
    return set(DEFERRED_ROUTER_MODULES) & loaded


def _route_paths(app) -> list[str]:
    """Return the application's route paths in match order.

    Args:
        app: FastAPI application instance.

    Returns:
        Ordered route paths.
    """
    return [route.path for route in app.routes]


def test_api_package_declares_no_eager_imports() -> None:
    """``app.api`` cannot drag in the API surface through a package-level import."""
    tree = ast.parse(API_PACKAGE_INIT.read_text(encoding="utf-8"))

    eager_imports = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"))
        or (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("app") for alias in node.names)
        )
    ]

    assert eager_imports == []


def test_importing_api_package_does_not_import_router_modules() -> None:
    """Importing ``app.api`` alone leaves every router submodule unloaded."""
    assert _deferred_leaks(_imported_api_modules()) == set()


def test_cold_entry_path_does_not_import_core_router_modules() -> None:
    """The Vercel entry path imports no core router before the first ping."""
    assert _deferred_leaks(_imported_entry_path_modules()) == set()


def test_entry_point_defers_router_registration() -> None:
    """The Vercel entry point opts into deferred router registration."""
    assert "defer_router_imports=True" in ENTRY_PATH.read_text(encoding="utf-8")


def test_importing_app_main_does_not_build_an_application() -> None:
    """Importing ``app.main`` costs no application construction (issue #2978 AC4)."""
    loaded = _loaded_modules(
        "import app.main; assert 'app' not in vars(app.main), vars(app.main).keys()"
    )

    assert "fastapi.applications" in loaded


def test_dependency_subrouters_are_mounted_exactly_once() -> None:
    """Repeated application builds do not duplicate dependency sub-routes."""
    before = len(dependency.router.routes)
    create_app(serve_frontend=False)
    create_app(serve_frontend=False)

    assert len(dependency.router.routes) == before


@pytest.mark.asyncio
async def test_cold_ping_defers_core_routers_and_next_request_completes_them() -> None:
    """Ping answers before the core routers load; the next request completes them."""
    eager_paths = _route_paths(create_app(serve_frontend=False))
    app = create_app(serve_frontend=False, defer_router_imports=True)
    cold_paths = _route_paths(app)

    assert "/api/ping" in cold_paths
    assert DEPENDENCY_SUBROUTER_PATH not in cold_paths
    assert RELEASES_SUBROUTER_PATH not in cold_paths

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ping = await client.get("/api/ping")

        assert ping.status_code == 200
        assert ping.json() == {"status": "alive"}
        assert _route_paths(app) == cold_paths

        # Unauthenticated: a 401 proves the real route answered instead of the
        # ``/api/{path:path}`` fallback shadowing the deferred routers.
        response = await client.get(DEPENDENCY_SUBROUTER_PATH)

    assert response.status_code == 401

    completed_paths = _route_paths(app)
    assert completed_paths == eager_paths
    assert completed_paths.index(DEPENDENCY_SUBROUTER_PATH) < completed_paths.index(
        API_FALLBACK_PATH
    )


@pytest.mark.asyncio
async def test_unknown_api_path_still_returns_json_404_after_deferred_registration() -> None:
    """The JSON API fallback keeps answering unknown paths once registration completes."""
    app = create_app(serve_frontend=False, defer_router_imports=True)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/this-route-does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_default_application_is_cached() -> None:
    """``app.main.app`` resolves to one cached instance for ASGI and test importers."""
    assert get_app() is get_app()