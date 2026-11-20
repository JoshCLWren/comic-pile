"""Shared canonical-schema fixture for native Roll parity tests."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest_asyncio

# Parity tests import ``app.models`` from the repository root. CI sets
# PYTHONPATH=. explicitly; add that root here too so a direct pytest invocation
# of a single parity test file (for example the factory pre-push check) resolves
# the application package regardless of the caller's environment.
_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[3])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

_PARITY_DATABASE_LOCK = 4_535_000_002


@pytest_asyncio.fixture(autouse=True)
async def reset_canonical_schema() -> AsyncIterator[None]:
    """Serialize parity tests and reset the Alembic schema using the DML role."""
    url = os.environ.get("RUST_ROLL_PARITY_DATABASE_URL")
    if url is None:
        # Parity tests need a provisioned roll_test_dml database. Runner
        # environments without that service have no URL configured; attempt a
        # real connection to an unused loopback port so the outcome is the
        # database connection error it actually is. CI always supplies the
        # provisioned URL and never reaches this branch.
        url = "postgresql://roll_test_dml@127.0.0.1:1/native_auth_test"

    connection = await asyncpg.connect(url)
    try:
        role = await connection.fetchval("SELECT current_user")
        if role != "roll_test_dml":
            raise RuntimeError(
                "Rust parity tests must use the roll_test_dml database role"
            )

        await connection.execute("SELECT pg_advisory_lock($1)", _PARITY_DATABASE_LOCK)
        has_schema = await connection.fetchval(
            "SELECT to_regclass('public.threads') IS NOT NULL"
        )
        if not has_schema:
            raise RuntimeError(
                "Canonical public schema is missing; run Alembic migrations "
                "before the Rust parity suite"
            )

        tables = await connection.fetch(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version' "
            "ORDER BY tablename"
        )
        table_names = ", ".join(
            f'public."{row["tablename"]}"' for row in tables
        )
        if table_names:
            await connection.execute(f"TRUNCATE TABLE {table_names} CASCADE")
        await connection.execute(
            "SELECT setval(c.oid::regclass, 1, false) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'S' AND n.nspname = 'public'"
        )

        yield
    finally:
        if not connection.is_closed():
            await connection.execute(
                "SELECT pg_advisory_unlock($1)", _PARITY_DATABASE_LOCK
            )
            await connection.close()
