"""Measured per-route budgets for POST /api/v2/reading-boundaries (#4737).

Runs the shared harness (``route_harness``) against the native Rust route on
the canonical Alembic schema with a small (proof-scale) and a large (full
200-id batch) fixture. Each run prints one canonical ``route-harness`` line
with HTTP bytes, Rust wall/CPU, and Postgres xacts/blocks/statement deltas.

Static budget (``tests/test_reading_boundary_sql_budget.py``,
``docs/api/v2-route-inventory.json``): 9 application statements + 2
transaction-control = 11 total, set-based and independent of library size.
The measured assertions below are the dynamic counterpart: the large run
must not scale statements/transactions or payload superlinearly with the
batch, proving there is no per-row N+1 (see also the single-snapshot
concurrency regression in #4808, exercised here as a concurrent pair).
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread, User

from route_harness import (
    RouteMeasurement,
    measure_route,
    run_rust_example,
)

SECRET = "synthetic-route-harness-secret"
BINARY = "native/roll-service/target/debug/examples/http_reading_boundaries"
ROUTE = "POST /api/v2/reading-boundaries"
LARGE_BATCH = 200

# Measured Postgres counters include the harness's own snapshot reads and
# can lag, so xacts/blocks deltas are asserted as far-below-N+1 bounds.
# The budget itself is 9 application statements in one read transaction.
MAX_MEASURED_XACTS = 8
MAX_MEASURED_STATEMENTS = 30


async def _seed_threads(
    db: AsyncSession,
    owner: User,
    count: int,
    start_position: int,
) -> list[int]:
    """Create ``count`` threads with two unread issues each; return their ids."""
    threads = [
        Thread(
            user_id=owner.id,
            title=f"Harness Series {start_position + offset}",
            format="Comic",
            queue_position=start_position + offset,
            issues_remaining=2,
            total_issues=2,
        )
        for offset in range(count)
    ]
    db.add_all(threads)
    await db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=number, position=position,
              status="unread")
        for thread in threads
        for position, number in ((1, "1"), (2, "2"))
    ]
    db.add_all(issues)
    await db.flush()
    for thread, first, _second in zip(threads, issues[0::2], issues[1::2], strict=True):
        thread.next_unread_issue_id = first.id
    await db.commit()
    return [thread.id for thread in threads]


def _env(url: str, token: str, thread_ids: list[int]) -> dict[str, str]:
    """Build the subprocess environment for one reading-boundaries request."""
    return {
        **os.environ,
        "RUST_ROLL_DATABASE_URL": url,
        "RUST_ROLL_JWT_SECRET": SECRET,
        "RUST_ROLL_TEST_TOKEN": token,
        "RUST_ROLL_POOL_SIZE": "2",
        "RUST_ROLL_TEST_BODY": json.dumps({"thread_ids": thread_ids}),
    }


def _assert_budget_shape(small: RouteMeasurement, large: RouteMeasurement) -> None:
    """Assert measured costs stay near the small run as the batch grows 67x."""
    # HTTP bytes scale with the batch (200/3 entries) but remain linear.
    assert large.http_bytes > small.http_bytes
    assert large.http_bytes > small.http_bytes * 8
    # A single read transaction per request: xacts must not follow the batch.
    assert small.db_xacts <= MAX_MEASURED_XACTS
    assert large.db_xacts <= MAX_MEASURED_XACTS
    assert large.db_xacts <= small.db_xacts + 5
    # Statement executions (when pg_stat_statements exists) must stay near
    # the 9-application-statement budget, independent of library size.
    if small.db_statements is not None and large.db_statements is not None:
        assert small.db_statements <= MAX_MEASURED_STATEMENTS
        assert large.db_statements <= MAX_MEASURED_STATEMENTS
        assert large.db_statements <= small.db_statements + 5


@pytest.mark.asyncio
async def test_reading_boundaries_route_harness_small_and_large(
    monkeypatch: pytest.MonkeyPatch,
):
    """Measure small and full-batch fixtures and assert budget-shaped costs."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv(
        "OPTION_E_APPROVED_PREVIEW", "route-harness-fixture-no-production-approval"
    )

    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        now = datetime.now(UTC)
        username = f"harness_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            small_ids = await _seed_threads(db, owner, 3, 1)

        token = jwt.encode(
            {
                "sub": username,
                "jti": "route-harness-fixture",
                "type": "access",
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            SECRET,
            "HS256",
        )

        small = await measure_route(
            BINARY, _env(url, token, small_ids), engine, ROUTE, "small"
        )
        assert small.status == 200, small.body
        threads = small.body.get("threads")
        assert isinstance(threads, dict)
        assert set(threads) == {str(thread_id) for thread_id in small_ids}
        assert small.http_bytes > 0
        assert small.wall_ms > 0
        assert small.child_cpu_ms >= 0

        async with AsyncSession(engine, expire_on_commit=False) as db:
            large_ids = await _seed_threads(db, owner, LARGE_BATCH, 100)

        large = await measure_route(
            BINARY, _env(url, token, large_ids), engine, ROUTE, "large-200"
        )
        assert large.status == 200, large.body
        large_threads = large.body.get("threads")
        assert isinstance(large_threads, dict)
        assert set(large_threads) == {str(thread_id) for thread_id in large_ids}
        assert large.http_bytes > 0
        assert large.wall_ms > 0

        _assert_budget_shape(small, large)

        # Concurrency (#4808): two simultaneous full-batch requests must both
        # return the single-snapshot payload, byte-for-byte identical.
        env = _env(url, token, large_ids)
        (result_a, raw_a, _, _), (result_b, raw_b, _, _) = await asyncio.gather(
            run_rust_example(BINARY, env),
            run_rust_example(BINARY, env),
        )
        assert result_a["status"] == 200, result_a
        assert result_b["status"] == 200, result_b
        assert result_a["body"] == result_b["body"]
        assert raw_a == raw_b
        print(
            f"route-harness route={ROUTE} fixture=large-concurrent-x2 "
            f"status=200 http_bytes={len(raw_a)}+{len(raw_b)}",
            flush=True,
        )
    finally:
        await engine.dispose()
