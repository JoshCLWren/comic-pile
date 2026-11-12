"""Prove the SQL budget counter detects uncatalogued service-role queries."""

from __future__ import annotations

import os

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from route_harness import db_counters


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
