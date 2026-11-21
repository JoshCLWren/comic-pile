"""Shared per-route measurement harness for native Roll parity tests (#4737).

Each measurement runs one Rust example binary (one authenticated HTTP request
against the canonical Alembic schema) and reports, in one canonical line:

- HTTP response bytes,
- Rust process wall time and child CPU time,
- Postgres transactions/blocks deltas from ``pg_stat_database`` (blocks are
  converted to bytes using the 8 KiB PostgreSQL block size),
- Top-level and nested statement executions from ``pg_stat_statements`` under
  the isolated service role. Measured parity tests fail if the extension is
  unavailable; static call-site pins alone do not satisfy the runtime budget.

The canonical line is printed in test output (``pytest -s``) and is the record
of measured per-route numbers alongside the production ``vercel-log``
``elapsed_ms`` line. Fixture data must come from the canonical Alembic schema
(see ``conftest.py`` in this directory); this harness never creates tables.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

#: PostgreSQL block size; converts ``pg_stat_database`` block deltas to bytes.
BLOCK_BYTES = 8192
SQL_BUDGET_SOURCES = Path(__file__).resolve().parents[3] / "docs/api/sql-budget-sources.json"


def _budget_entry(method: str, path: str) -> dict[str, object]:
    """Return the unique editable SQL budget source for one operation."""
    document = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))
    matching = [
        entry
        for entry in document["operations"]
        if entry["method"] == method and entry["path"] == path
    ]
    assert len(matching) == 1, f"missing or duplicate SQL budget: {method} {path}"
    return matching[0]


def assert_declared_budget(method: str, path: str, *measurements: int | None) -> None:
    """Fail when a measured native route exceeds its declared source budget.

    Args:
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.
        *measurements: Counts that must be present and within the maximum.

    Returns:
        None; invalid measurements raise AssertionError.
    """
    maximum = _budget_entry(method, path)["sql_budget"]["max_statements"]
    assert isinstance(maximum, int) and maximum >= 0
    for measured in measurements:
        assert measured is not None, "pg_stat_statements must measure every covered route"
        assert measured <= maximum, (
            f"{method} {path} issued {measured} statements; declared maximum is {maximum}"
        )


@dataclass(frozen=True)
class StatementBreakdown:
    """PostgreSQL statements split by application, control, runtime, and nesting."""

    application: int
    transaction_control: int
    runtime_overhead: int
    nested: int

    @property
    def top_level(self) -> int:
        """Return the total top-level statement count."""
        return self.application + self.transaction_control + self.runtime_overhead


def assert_statement_budget(
    method: str,
    path: str,
    *measurements: StatementBreakdown | None,
    require_maximum: bool = False,
) -> None:
    """Enforce each declared component of a measured route's SQL budget.

    Args:
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.
        *measurements: Statement splits that must be present and within budget.
        require_maximum: Whether each measurement must equal the worst-case maximum.

    Returns:
        None; an invalid or over-budget measurement raises AssertionError.
    """
    budget = _budget_entry(method, path)["sql_budget"]
    application_maximum = budget["application_statements"]
    control_maximum = budget["transaction_control_statements"]
    overhead_maximum = budget.get("runtime_overhead_statements", 0)
    nested_maximum = budget.get("max_nested_statements", 0)
    maximum = budget["max_statements"]
    for measured in measurements:
        assert measured is not None, "pg_stat_statements must measure every covered route"
        assert measured.application <= application_maximum, (
            f"{method} {path} application statement count changed: "
            f"{measured.application} > {application_maximum}"
        )
        assert measured.transaction_control <= control_maximum, (
            f"{method} {path} transaction-control statement count changed: "
            f"{measured.transaction_control} > {control_maximum}"
        )
        assert measured.runtime_overhead <= overhead_maximum, (
            f"{method} {path} runtime-overhead statement count changed: "
            f"{measured.runtime_overhead} > {overhead_maximum}"
        )
        assert measured.nested <= nested_maximum, (
            f"{method} {path} nested statement count changed: "
            f"{measured.nested} > {nested_maximum}"
        )
        assert_declared_budget(method, path, measured.top_level)
        if require_maximum:
            assert measured.top_level == maximum, (
                f"{method} {path} declares a slack budget: {measured.top_level} measured "
                f"against a {maximum} maximum, so one extra query would still fit"
            )


def assert_no_statement_growth(
    method: str,
    path: str,
    small: StatementBreakdown,
    large: StatementBreakdown,
) -> None:
    """Fail when any fixed-budget statement component grows with data size."""
    budget = _budget_entry(method, path)["sql_budget"]
    assert budget["grows_with_data"] is False, f"{method} {path} must have a fixed SQL budget"
    for component in ("application", "transaction_control", "runtime_overhead", "nested"):
        small_count = getattr(small, component)
        large_count = getattr(large, component)
        assert large_count <= small_count, (
            f"{method} {path} {component} statement count grew with data size: "
            f"{small_count} -> {large_count}"
        )


@dataclass(frozen=True)
class RouteMeasurement:
    """Measured cost of one authenticated route invocation."""

    route: str
    fixture: str
    status: int
    http_bytes: int
    wall_ms: float
    child_cpu_ms: float
    db_xacts: int
    db_blocks: int
    db_bytes: int
    db_statements: int | None
    db_nested_statements: int | None
    body: dict[str, object]


async def _role_statement_count(connection: AsyncConnection, *, toplevel: bool) -> int | None:
    """Read one isolated service-role statement count from PostgreSQL stats."""
    try:
        if not toplevel:
            setting = await connection.execute(text("SHOW pg_stat_statements.track"))
            if setting.scalar_one() != "all":
                return None
        row = await connection.execute(
            text(
                "SELECT COALESCE(SUM(s.calls), 0) FROM pg_stat_statements s "
                "JOIN pg_roles r ON r.oid = s.userid "
                "WHERE r.rolname = 'roll_test_dml' AND s.toplevel = :toplevel "
                "AND s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())"
            ),
            {"toplevel": toplevel},
        )
        return int(row.scalar_one())
    except DBAPIError:
        return None


async def db_counters(engine: AsyncEngine) -> tuple[int, int, int | None]:
    """Return cumulative (xacts, blocks, statements) Postgres counters.

    Statements are filtered to the isolated ``roll_test_dml`` role and read
    through the administrative connection, so snapshot queries and unrelated
    test roles cannot inflate the route count. Transactions and blocks remain
    database-wide context, not exact route accounting.
    """
    admin_url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if admin_url is None:
        stats_engine = engine
    else:
        stats_engine = create_async_engine(
            admin_url.replace("postgresql://", "postgresql+asyncpg://")
        )
    try:
        async with stats_engine.connect() as admin:
            row = await admin.execute(
                text(
                    "SELECT xact_commit + xact_rollback, blks_read + blks_hit "
                    "FROM pg_stat_database WHERE datname = current_database()"
                )
            )
            xacts, blocks = (int(value) for value in row.one())
            if admin_url is None:
                return xacts, blocks, None
            statements = await _role_statement_count(admin, toplevel=True)
    finally:
        if stats_engine is not engine:
            await stats_engine.dispose()
    return xacts, blocks, statements


async def db_nested_statements(engine: AsyncEngine) -> int | None:
    """Return nested trigger/function statements for the isolated service role.

    Args:
        engine: Route database engine (administrative URL is read from the environment).

    Returns:
        Nested count, or None when the administrative URL is unset or tracking
        does not include nested statements.
    """
    admin_url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if admin_url is None:
        return None
    admin_engine = create_async_engine(admin_url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with admin_engine.connect() as admin:
            return await _role_statement_count(admin, toplevel=False)
    finally:
        await admin_engine.dispose()


async def run_rust_example(
    binary: str,
    env: dict[str, str],
    timeout: float = 25.0,
) -> tuple[dict[str, object], bytes, float, float]:
    """Run a Rust example binary; return parsed body, raw bytes, wall, child CPU."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        binary,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout)
    wall = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    assert proc.returncode == 0, err.decode()
    return json.loads(out), out, wall, cpu


def format_measurement(measurement: RouteMeasurement) -> str:
    """Return the canonical one-line record of a measurement."""
    statements = (
        str(measurement.db_statements) if measurement.db_statements is not None else "n/a"
    )
    nested = (
        str(measurement.db_nested_statements)
        if measurement.db_nested_statements is not None
        else "n/a"
    )
    return (
        "route-harness "
        f"route={measurement.route} fixture={measurement.fixture} "
        f"status={measurement.status} http_bytes={measurement.http_bytes} "
        f"wall_ms={measurement.wall_ms:.2f} "
        f"child_cpu_ms={measurement.child_cpu_ms:.2f} "
        f"db_xacts={measurement.db_xacts} db_blocks={measurement.db_blocks} "
        f"db_bytes={measurement.db_bytes} db_statements={statements} "
        f"db_nested_statements={nested}"
    )


async def measure_route(
    binary: str,
    env: dict[str, str],
    engine: AsyncEngine,
    route: str,
    fixture: str,
) -> RouteMeasurement:
    """Measure one invocation: snapshot counters, run, snapshot, print, return."""
    xacts_before, blocks_before, statements_before = await db_counters(engine)
    nested_before = await db_nested_statements(engine)
    result, raw, wall, cpu = await run_rust_example(binary, env)
    xacts_after, blocks_after, statements_after = await db_counters(engine)
    nested_after = await db_nested_statements(engine)
    body = result.get("body")
    assert isinstance(body, dict)
    measurement = RouteMeasurement(
        route=route,
        fixture=fixture,
        status=int(result["status"]),
        http_bytes=len(raw),
        wall_ms=wall * 1000,
        child_cpu_ms=cpu * 1000,
        db_xacts=xacts_after - xacts_before,
        db_blocks=blocks_after - blocks_before,
        db_bytes=(blocks_after - blocks_before) * BLOCK_BYTES,
        db_statements=(
            statements_after - statements_before
            if statements_after is not None and statements_before is not None
            else None
        ),
        db_nested_statements=(
            nested_after - nested_before
            if nested_after is not None and nested_before is not None
            else None
        ),
        body=body,
    )
    print(format_measurement(measurement), flush=True)
    return measurement


def cargo_example_path(name: str) -> Path:
    """Resolve an example using Cargo's build-directory-relative target setting.

    Args:
        name: Cargo example executable name.

    Returns:
        Absolute path to the debug example executable.
    """
    build_directory = Path(__file__).resolve().parents[1]
    target = Path(os.environ.get("CARGO_TARGET_DIR", "target"))
    if not target.is_absolute():
        target = build_directory / target
    return target / "debug" / "examples" / name
