"""Route measurement helpers for reading-graph and reading-list SQL budgets."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from route_harness import (
    BLOCK_BYTES,
    RouteMeasurement,
    assert_declared_budget,
    db_counters,
    db_nested_statements,
    format_measurement,
    run_rust_example,
)


def assert_fixed_statement_count(
    small: int | None,
    large: int | None,
    *,
    kind: str,
) -> None:
    """Require available, identical statement counts at both fixture sizes."""
    assert small is not None and large is not None, (
        f"{kind} statements require pg_stat_statements.track=all"
    )
    assert large == small, f"{kind} statement count grew: {small} -> {large}"


def assert_fixed_budget(
    method: str,
    path: str,
    small: RouteMeasurement,
    large: RouteMeasurement,
) -> None:
    """Enforce declared top-level maxima and fixed top-level/nested growth."""
    assert_declared_budget(
        method,
        path,
        small.db_statements,
        large.db_statements,
    )
    assert_fixed_statement_count(
        small.db_statements,
        large.db_statements,
        kind="top-level",
    )
    assert_fixed_statement_count(
        small.db_nested_statements,
        large.db_nested_statements,
        kind="nested",
    )


async def measure_reading_route(
    binary: str,
    env: dict[str, str],
    engine: AsyncEngine,
    route: str,
    fixture: str,
) -> tuple[dict[str, object], RouteMeasurement]:
    """Measure any JSON HTTP response while retaining its original body shape."""
    xacts_before, blocks_before, statements_before = await db_counters(engine)
    nested_before = await db_nested_statements(engine)
    response, raw, wall, cpu = await run_rust_example(binary, env)
    xacts_after, blocks_after, statements_after = await db_counters(engine)
    nested_after = await db_nested_statements(engine)
    response_body = response.get("body")
    measurement = RouteMeasurement(
        route=route,
        fixture=fixture,
        status=int(response["status"]),
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
        body=response_body if isinstance(response_body, dict) else {},
    )
    print(format_measurement(measurement), flush=True)
    return response, measurement
