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
    """Return the unique source budget for one native operation.

    Args:
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.

    Returns:
        The matching source entry.

    Raises:
        AssertionError: If the operation has no unique budget entry.
    """
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


def assert_no_statement_growth(
    method: str,
    path: str,
    small_count: int,
    large_count: int,
    *,
    tolerance: int = 0,
) -> None:
    """Fail when a fixed-size route's statement count grows with its data size.

    Args:
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.
        small_count: Statement count measured with the small fixture.
        large_count: Statement count measured with the large fixture.
        tolerance: Allowed increase in statement count for runtime variance.

    Returns:
        None; an invalid growth measurement raises AssertionError.
    """
    budget = _budget_entry(method, path)["sql_budget"]
    assert isinstance(budget, dict)
    assert budget.get("grows_with_data") is False, (
        f"{method} {path} must declare a fixed statement count"
    )
    assert large_count <= small_count + tolerance, (
        f"{method} {path} statement count grew with data size: "
        f"{small_count} -> {large_count}"
    )


@dataclass(frozen=True)
class StatementBreakdown:
    """Measured PostgreSQL statements split by execution responsibility."""

    application: int
    transaction_control: int
    runtime_overhead: int
    nested: int

    @property
    def top_level(self) -> int:
        """Return the total top-level statement count."""
        return self.application + self.transaction_control + self.runtime_overhead

    @property
    def total(self) -> int:
        """Return the top-level plus nested statement count."""
        return self.top_level + self.nested


def assert_measured_statement_breakdown(
    method: str,
    path: str,
    measured: StatementBreakdown,
) -> None:
    """Assert that a measured statement split matches its source budget.

    The measured split must match the declared application, transaction-control
    and runtime-overhead counts exactly, the nested count must stay within its
    declared maximum, and the declared maximum must leave no slack. Without
    that last property a deliberately added extra query could still fit inside
    the absolute budget, so one extra statement has to exceed it.

    Args:
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.
        measured: Statement counts measured for one request.

    Returns:
        None; a mismatched measurement raises AssertionError.
    """
    budget = _budget_entry(method, path)["sql_budget"]
    assert isinstance(budget, dict)
    assert measured.application == budget.get("application_statements"), (
        f"{method} {path} application statement count changed"
    )
    assert measured.transaction_control == budget.get("transaction_control_statements"), (
        f"{method} {path} transaction-control statement count changed"
    )
    assert measured.runtime_overhead == budget.get("runtime_overhead_statements"), (
        f"{method} {path} runtime-overhead statement count changed"
    )
    nested_maximum = budget.get("max_nested_statements")
    assert isinstance(nested_maximum, int)
    assert measured.nested <= nested_maximum, (
        f"{method} {path} issued {measured.nested} nested trigger statements; "
        f"declared maximum is {nested_maximum}"
    )
    maximum = budget.get("max_statements")
    assert isinstance(maximum, int)
    assert measured.top_level == maximum, (
        f"{method} {path} declares a slack budget: {measured.top_level} measured "
        f"statements against a {maximum} maximum, so one deliberately added "
        "extra query would still fit inside it"
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
    db_application_statements: int | None
    db_transaction_control_statements: int | None
    db_runtime_overhead_statements: int | None
    db_nested_statements: int | None
    body: dict[str, object]


async def _role_statement_count(connection: AsyncConnection, *, toplevel: bool) -> int | None:
    """Read one isolated service-role statement count from PostgreSQL stats."""
    try:
        if not toplevel:
            setting = await connection.execute(text("SHOW pg_stat_statements.track"))
            if setting.scalar_one() != "all":
                return None
        elif not toplevel:
            # This branch is unreachable, but kept for structural consistency if needed
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


async def reset_statement_stats() -> None:
    """Reset PostgreSQL statement statistics before one isolated route request.

    ``pg_stat_statements`` groups statements by PostgreSQL query id and keeps
    one representative text for the group. A checkout probe can therefore share
    a group with an application statement unless the group is first observed
    while the probe is the only statement in flight. Resetting immediately
    before the mounted request guarantees that the probe establishes the
    representative text; route statements then accumulate in separate groups.

    Args:
        None.

    Returns:
        None; a reset failure raises the database error.
    """
    admin_url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if admin_url is None:
        return
    admin_engine = create_async_engine(admin_url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with admin_engine.connect() as admin:
            await admin.execute(text("SELECT pg_stat_statements_reset()"))
    finally:
        await admin_engine.dispose()


async def db_statement_breakdown(engine: AsyncEngine) -> StatementBreakdown | None:
    """Return isolated-role statement counts split by execution responsibility.

    The administrative connection reads ``pg_stat_statements`` with
    ``track=all``. Top-level application statements, transaction controls, and
    pool-checkout probes are classified independently; trigger/function queries
    are returned as nested statements.

    Args:
        engine: Route database engine. The administrative URL is read from the
            environment when available.

    Returns:
        The measured statement split, or None when no administrative URL is
        configured or the statement extension is unavailable.
    """
    admin_url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if admin_url is None:
        return None
    admin_engine = create_async_engine(admin_url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with admin_engine.connect() as admin:
            try:
                row = await admin.execute(
                    text(
                        """
                        WITH role_statements AS (
                            SELECT s.calls,
                                   s.toplevel,
                                   lower(regexp_replace(
                                       btrim(s.query),
                                       '[[:space:]]+',
                                       ' ',
                                       'g'
                                   )) AS normalized_query
                            FROM pg_stat_statements s
                            JOIN pg_roles r ON r.oid = s.userid
                            WHERE r.rolname = 'roll_test_dml'
                              AND s.dbid = (
                                  SELECT oid FROM pg_database
                                  WHERE datname = current_database()
                              )
                        ),
                        classified AS (
                            SELECT calls,
                                   toplevel,
                                   normalized_query IN ('select 1', 'select $1')
                                       AS is_runtime_overhead,
                                   (
                                       normalized_query IN (
                                           'begin', 'commit', 'rollback', 'abort', 'end'
                                       )
                                       OR normalized_query LIKE 'begin %'
                                       OR normalized_query LIKE 'start transaction %'
                                       OR normalized_query LIKE 'commit %'
                                       OR normalized_query LIKE 'rollback %'
                                       OR normalized_query LIKE 'abort %'
                                       OR normalized_query LIKE 'end %'
                                       OR normalized_query LIKE 'set local %'
                                       OR normalized_query LIKE 'set transaction %'
                                       OR normalized_query LIKE 'savepoint %'
                                       OR normalized_query LIKE 'release savepoint %'
                                       OR normalized_query LIKE 'prepare transaction %'
                                   ) AS is_transaction_control
                            FROM role_statements
                        )
                        SELECT
                            COALESCE(
                                SUM(calls) FILTER (
                                    WHERE toplevel
                                      AND NOT is_runtime_overhead
                                      AND NOT is_transaction_control
                                ),
                                0
                            ) AS application,
                            COALESCE(
                                SUM(calls) FILTER (
                                    WHERE toplevel AND is_transaction_control
                                ),
                                0
                            ) AS transaction_control,
                            COALESCE(
                                SUM(calls) FILTER (
                                    WHERE toplevel AND is_runtime_overhead
                                ),
                                0
                            ) AS runtime_overhead,
                            COALESCE(
                                SUM(calls) FILTER (WHERE NOT toplevel),
                                0
                            ) AS nested
                        FROM classified
                        """
                    )
                )
            except DBAPIError:
                return None
            values = row.one()
            return StatementBreakdown(
                application=int(values[0]),
                transaction_control=int(values[1]),
                runtime_overhead=int(values[2]),
                nested=int(values[3]),
            )
    finally:
        await admin_engine.dispose()


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
    application = (
        str(measurement.db_application_statements)
        if measurement.db_application_statements is not None
        else "n/a"
    )
    control = (
        str(measurement.db_transaction_control_statements)
        if measurement.db_transaction_control_statements is not None
        else "n/a"
    )
    overhead = (
        str(measurement.db_runtime_overhead_statements)
        if measurement.db_runtime_overhead_statements is not None
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
        f"db_application_statements={application} "
        f"db_transaction_control_statements={control} "
        f"db_runtime_overhead_statements={overhead} "
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
    await reset_statement_stats()
    xacts_before, blocks_before, statements_before = await db_counters(engine)
    breakdown_before = await db_statement_breakdown(engine)
    nested_before = await db_nested_statements(engine)
    result, raw, wall, cpu = await run_rust_example(binary, env)
    xacts_after, blocks_after, statements_after = await db_counters(engine)
    breakdown_after = await db_statement_breakdown(engine)
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
        db_application_statements=(
            breakdown_after.application - breakdown_before.application
            if breakdown_after is not None and breakdown_before is not None
            else None
        ),
        db_transaction_control_statements=(
            breakdown_after.transaction_control - breakdown_before.transaction_control
            if breakdown_after is not None and breakdown_before is not None
            else None
        ),
        db_runtime_overhead_statements=(
            breakdown_after.runtime_overhead - breakdown_before.runtime_overhead
            if breakdown_after is not None and breakdown_before is not None
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
