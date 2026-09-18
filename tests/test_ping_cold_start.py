"""Regression coverage for lazy ping cold-start mitigation (issue #2561)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app.cache_accounting import cache_accounting
from app.startup_diagnostics import (
    is_heavy_initialized,
    reset_startup_diagnostics_for_test,
)


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
