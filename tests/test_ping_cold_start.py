"""Regression coverage for lazy ping cold-start mitigation (issue #2561)."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache_accounting import cache_accounting
from app.startup_diagnostics import (
    is_heavy_initialized,
    reset_startup_diagnostics_for_test,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _find_startup_handler(app):
    """Return the lifespan startup handler named ``startup_event``."""
    for handler in app.router.on_startup:
        if getattr(handler, "__name__", None) == "startup_event":
            return handler
    raise AssertionError("startup_event handler not found")


@pytest.mark.asyncio
async def test_cold_ping_does_not_initialize_database_or_cache() -> None:
    """Cold GET /api/ping completes without opening PG or initializing cache accounting."""
    reset_startup_diagnostics_for_test()
    cache_accounting.reset()
    # ensure any prior heavy state is cleared
    from app import main

    with (
        patch("app.main.init_database", new_callable=AsyncMock) as mock_init,
        patch.object(cache_accounting, "initialize", new_callable=AsyncMock) as mock_acct,
        patch.object(main.cache, "configure", new_callable=AsyncMock),
    ):
        app = main.create_app(serve_frontend=False)
        startup = _find_startup_handler(app)
        await startup()

        # lightweight startup must not have touched heavy deps
        mock_init.assert_not_awaited()
        mock_acct.assert_not_awaited()
        assert is_heavy_initialized() is False

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/ping")

            assert resp.status_code == 200
            assert resp.json() == {"status": "alive"}
            # observability: lightweight wake-up distinguishable from heavy cold start
            assert resp.headers.get("X-Heavy-Init") == "0"
            assert is_heavy_initialized() is False

            # trailing-slash probes must stay light too (slash redirect happens
            # inside routing, after this middleware would otherwise heavy-init)
            slash_resp = await client.get("/api/ping/")
            assert slash_resp.headers.get("X-Heavy-Init") == "0"
            assert is_heavy_initialized() is False

        mock_init.assert_not_awaited()
        mock_acct.assert_not_awaited()



@pytest.mark.asyncio
async def test_first_non_ping_request_initializes_heavy_dependencies() -> None:
    """First non-ping request lazily initializes DB and cache infrastructure."""
    reset_startup_diagnostics_for_test()
    cache_accounting.reset()
    from app import main

    with (
        patch("app.main.init_database", new_callable=AsyncMock) as mock_init,
        patch.object(cache_accounting, "initialize", new_callable=AsyncMock) as mock_acct,
        patch.object(main.cache, "configure", new_callable=AsyncMock),
    ):
        app = main.create_app(serve_frontend=False)
        startup = _find_startup_handler(app)
        await startup()

        mock_init.assert_not_awaited()
        assert is_heavy_initialized() is False

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # any non-ping path must trigger heavy init, even an unknown API route
            resp = await client.get("/api/unknown-route-for-cold-start-test")

        # heavy init should have run once
        mock_init.assert_awaited()
        mock_acct.assert_awaited()
        # provider specifics may or may not configure cache; init_database+accounting prove heavy ran
        assert is_heavy_initialized() is True
        assert resp.headers.get("X-Heavy-Init") == "1"


@pytest.mark.asyncio
async def test_ping_then_non_ping_sequence() -> None:
    """Ping keeps process light; subsequent app route triggers heavy init exactly once."""
    reset_startup_diagnostics_for_test()
    cache_accounting.reset()
    from app import main

    with (
        patch("app.main.init_database", new_callable=AsyncMock) as mock_init,
        patch.object(cache_accounting, "initialize", new_callable=AsyncMock) as mock_acct,
        patch.object(main.cache, "configure", new_callable=AsyncMock),
    ):
        app = main.create_app(serve_frontend=False)
        startup = _find_startup_handler(app)
        await startup()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ping_resp = await client.get("/api/ping")
            assert ping_resp.headers.get("X-Heavy-Init") == "0"
            mock_init.assert_not_awaited()
            mock_acct.assert_not_awaited()

            second = await client.get("/api/another-non-ping")
            assert second.headers.get("X-Heavy-Init") == "1"
            mock_init.assert_awaited_once()
            mock_acct.assert_awaited_once()

            # third request must not re-run heavy init
            third = await client.get("/api/yet-another")
            assert third.headers.get("X-Heavy-Init") == "1"
            mock_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_init_does_not_eagerly_import_full_router_surface() -> None:
    """Importing app.api.ping defers full router surface; cold start stays cheap (issue #2978)."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from app.api import ping\n"
        "eager = [m for m in sys.modules if m.startswith('app.api.') and m != 'app.api.ping']\n"
        "if eager:\n"
        "    print(eager)\n"
        "    sys.exit(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, (
        "app.api package eagerly loaded the full router surface: "
        f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
    )


def test_app_main_defers_app_construction_to_lazy_attribute() -> None:
    """Guard against eager app construction in app.main (issue #2978)."""
    tree = ast.parse((REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8"))

    eager_constructions = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "create_app"
    ]
    assert eager_constructions == [], (
        "app.main must not call create_app() at module scope; the shared instance is "
        "built lazily by the module __getattr__ so api/index.py does not pay twice"
    )
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "__getattr__" for node in tree.body
    ), "app.main must expose a module-level __getattr__ that builds the shared app lazily"


def test_vercel_entry_path_constructs_exactly_one_app() -> None:
    """Verify the Vercel entry path builds exactly one application (issue #2978)."""
    tree = ast.parse((REPO_ROOT / "api" / "index.py").read_text(encoding="utf-8"))

    create_app_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_app"
    ]
    assert len(create_app_calls) == 1

    imported_from_app_main = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.main"
        for alias in node.names
    }
    assert imported_from_app_main == {"create_app"}, (
        "api/index.py must build its own instance instead of importing the shared app, "
        "which would construct a second application on every cold start"
    )


@pytest.mark.asyncio
async def test_heavy_init_is_idempotent_under_concurrent_pings() -> None:
    """Concurrent non-ping requests initialize heavy deps only once."""
    reset_startup_diagnostics_for_test()
    cache_accounting.reset()
    from app import main
    import asyncio

    with (
        patch("app.main.init_database", new_callable=AsyncMock) as mock_init,
        patch.object(cache_accounting, "initialize", new_callable=AsyncMock) as mock_acct,
        patch.object(main.cache, "configure", new_callable=AsyncMock),
    ):
        app = main.create_app(serve_frontend=False)
        startup = _find_startup_handler(app)
        await startup()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            results = await asyncio.gather(
                client.get("/api/a"),
                client.get("/api/b"),
                client.get("/api/c"),
            )
        # at most one heavy init despite concurrent triggers
        assert mock_init.await_count == 1
        assert mock_acct.await_count == 1
        for resp in results:
            assert resp.headers.get("X-Heavy-Init") == "1"
