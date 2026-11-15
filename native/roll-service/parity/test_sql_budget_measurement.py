"""Prove the SQL budget counter detects uncatalogued service-role queries."""

from __future__ import annotations

import json
import os

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from route_harness import (
    SQL_BUDGET_SOURCES,
    assert_declared_budget,
    db_counters,
    db_nested_statements,
)


def _declared_maximum(method: str, path: str) -> int:
    """Return the declared ``max_statements`` for one measured native route."""
    operations = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))["operations"]
    matching = [
        entry for entry in operations if entry["method"] == method and entry["path"] == path
    ]
    assert len(matching) == 1, f"missing or duplicate SQL budget: {method} {path}"
    maximum = matching[0]["sql_budget"]["max_statements"]
    assert isinstance(maximum, int)
    return maximum


def test_declared_budget_rejects_one_extra_statement() -> None:
    """A deliberate extra query must fail the corresponding route budget test.

    The measured route tests call :func:`assert_declared_budget` with their
    observed statement deltas. One uncatalogued query raises the measured count
    by one, so the declared maximum must reject it; this pins that sensitivity
    for a route added by #5148. The N+1 counterpart is the per-route
    ``large_delta <= small_delta + 2`` assertion, which a per-row query fails.
    """
    maximum = _declared_maximum("POST", "/api/v2/dependencies/")
    assert_declared_budget("POST", "/api/v2/dependencies/", maximum)
    with pytest.raises(AssertionError, match="declared maximum"):
        assert_declared_budget("POST", "/api/v2/dependencies/", maximum + 1)


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
