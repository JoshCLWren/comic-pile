"""Prove the SQL budget counter detects uncatalogued service-role queries."""

from __future__ import annotations

import os

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from route_harness import db_counters, db_nested_statements


@pytest.mark.asyncio
async def test_extra_service_query_increments_measured_budget() -> None:
    """A new query under the isolated route role must change the measured count."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        _, _, before = await db_counters(engine)
        assert before is not None, "pg_stat_statements must be enabled for SQL budgets"
        connection = await asyncpg.connect(url)
        try:
            await connection.execute("SELECT 1")
        finally:
            await connection.close()
        _, _, after = await db_counters(engine)
        assert after is not None
        assert after - before == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_nested_service_query_is_measured() -> None:
    """A function invocation records its nested query under track=all."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    admin_url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    admin = await asyncpg.connect(admin_url)
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        assert await admin.fetchval("SHOW pg_stat_statements.track") == "all"
        await admin.execute(
            "CREATE OR REPLACE FUNCTION public.sql_budget_nested_probe() RETURNS integer "
            "LANGUAGE plpgsql AS $$ BEGIN PERFORM 8675309; RETURN 1; END $$"
        )
        before = await db_nested_statements(engine)
        assert before is not None
        connection = await asyncpg.connect(url)
        try:
            await connection.fetchval("SELECT public.sql_budget_nested_probe()")
        finally:
            await connection.close()
        after = await db_nested_statements(engine)
        assert after is not None and after > before

        from route_harness import _role_statement_count
        from sqlalchemy import text
        admin_engine = create_async_engine(admin_url.replace("postgresql://", "postgresql+asyncpg://"))
        async with admin_engine.connect() as route_connection:
            await route_connection.execute(text("SET pg_stat_statements.track = 'top'"))
            assert await _role_statement_count(route_connection, toplevel=False) is None
        await admin_engine.dispose()
    finally:
        await admin.execute("DROP FUNCTION IF EXISTS public.sql_budget_nested_probe()")
        await admin.close()
        await engine.dispose()


@pytest.mark.parametrize("target", ["target", "custom-target", "/tmp/absolute-target"])
def test_cargo_example_target_resolution(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Relative Cargo targets are resolved from the crate build directory."""
    from pathlib import Path
    from route_harness import cargo_example_path

    monkeypatch.setenv("CARGO_TARGET_DIR", target)
    crate = Path(__file__).resolve().parents[1]
    assert cargo_example_path("http_auth_login") == crate / target / "debug/examples/http_auth_login"
