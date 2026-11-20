"""Budget-violation controls shared by the native auth N+1 tests (#5147).

Each measured route test proves its success path stays inside the reviewed
``sql_budget``. These helpers prove the same budgets actually **fail** when a
route would issue more statements: one query injected under the isolated
``roll_test_dml`` role stands in for a deliberately added extra query, and one
query per seeded row stands in for a per-row N+1 pattern. Both are measured
through the same ``pg_stat_statements`` counter the positive assertions use,
so a counter that stopped working fails here instead of silently passing every
budget.

This module is shared harness code, not a test: it holds no ``test_`` functions.
"""

from __future__ import annotations

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncEngine

from route_harness import assert_declared_budget, db_counters

#: Far-future expiry so a measurement never depends on wall-clock drift.
FIXTURE_TOKEN_EXPIRY = 4_102_444_800


def auth_token(
    username: str,
    *,
    jti: str,
    secret: str,
    token_type: str,
    password_epoch: int = 0,
) -> str:
    """Mint one native-compatible access or refresh credential for a fixture.

    Args:
        username: ``sub`` claim naming the seeded account.
        jti: Token identifier the revocation table is keyed by.
        secret: HS256 secret the native verifier is configured with.
        token_type: ``access`` or ``refresh``, matching the native claim check.
        password_epoch: ``pc`` claim; the credential epoch the token was minted at.

    Returns:
        The signed JWT.
    """
    assert token_type in {"access", "refresh"}
    return jwt.encode(
        {
            "sub": username,
            "jti": jti,
            "type": token_type,
            "pc": password_epoch,
            "exp": FIXTURE_TOKEN_EXPIRY,
        },
        secret,
        algorithm="HS256",
    )


async def grow_accounts(url: str, prefix: str, start: int, total: int) -> None:
    """Add peer accounts until the fixture holds ``total`` rows.

    Args:
        url: DSN of the isolated ``roll_test_dml`` role.
        prefix: Per-test account prefix that keeps fixtures isolated.
        start: First peer index that does not exist yet.
        total: Row count the fixture must reach.

    Returns:
        None.
    """
    raw = await asyncpg.connect(url)
    try:
        for index in range(start, total):
            await raw.execute(
                "INSERT INTO users (username, email) VALUES ($1, $2)",
                f"{prefix}_peer{index}",
                f"{prefix}_peer{index}@example.invalid",
            )
    finally:
        await raw.close()


async def _injected_statements(engine: AsyncEngine, url: str, count: int) -> int:
    """Inject ``count`` statements under the isolated route role and measure them.

    Args:
        engine: Route database engine used to read the statement counters.
        url: DSN of the isolated ``roll_test_dml`` role.
        count: Number of statements to issue.

    Returns:
        The measured statement delta, which must equal ``count``.
    """
    raw = await asyncpg.connect(url)
    try:
        _, _, before = await db_counters(engine)
        for _ in range(count):
            await raw.execute("SELECT 1")
        _, _, after = await db_counters(engine)
    finally:
        await raw.close()
    assert before is not None and after is not None, (
        "pg_stat_statements must measure injected queries"
    )
    injected = after - before
    assert injected == count, f"expected {count} measured statements, saw {injected}"
    return injected


async def extra_query_fails_budget(
    engine: AsyncEngine,
    url: str,
    *,
    method: str,
    path: str,
    measured: int,
) -> None:
    """Prove one added query pushes the route past its declared maximum.

    Args:
        engine: Route database engine used to read the statement counters.
        url: DSN of the isolated ``roll_test_dml`` role.
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.
        measured: Statements the route's own success path measured.

    Returns:
        None; a budget that still admits the extra query raises AssertionError.
    """
    injected = await _injected_statements(engine, url, 1)
    with pytest.raises(AssertionError, match="declared maximum"):
        assert_declared_budget(method, path, measured + injected)


async def per_row_queries_fail_budget(
    engine: AsyncEngine,
    url: str,
    *,
    method: str,
    path: str,
    measured: int,
    rows: int,
) -> None:
    """Prove one query per row (N+1) pushes the route past its declared maximum.

    Args:
        engine: Route database engine used to read the statement counters.
        url: DSN of the isolated ``roll_test_dml`` role.
        method: HTTP method of the declared operation.
        path: Route path of the declared operation.
        measured: Statements the route's own success path measured.
        rows: Row count of the large fixture, the N+1 statement count.

    Returns:
        None; a budget that still admits the per-row fan-out raises
        AssertionError.
    """
    injected = await _injected_statements(engine, url, rows)
    with pytest.raises(AssertionError, match="declared maximum"):
        assert_declared_budget(method, path, measured + injected)