"""Regression coverage for application database startup behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.lifecycle import init_database


@pytest.mark.asyncio
async def test_production_startup_does_not_acquire_database_connection() -> None:
    """Production startup must leave Neon untouched until a route needs it."""
    session_factory = AsyncMock(side_effect=AssertionError("database session opened"))

    with patch("app.lifecycle.AsyncSessionLocal", session_factory):
        await init_database("production")

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_production_startup_does_not_run_schema_setup() -> None:
    """Deployment migrations, not a cold request, own production schema setup."""
    engine = MagicMock()
    engine.begin = AsyncMock(side_effect=AssertionError("engine connection opened"))

    with patch("app.lifecycle.async_engine", engine):
        await init_database("production")

    engine.begin.assert_not_called()
