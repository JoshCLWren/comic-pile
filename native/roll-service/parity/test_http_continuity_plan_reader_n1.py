"""Measured SQL budget for ``GET /api/v2/continuity-plans/{plan_id}/reader`` (#5146).

Seeds a small and a large authoritative Reading List for the same Option E
continuity plan, runs the mounted native Rust reader against the canonical
Alembic schema on each, and asserts:

* the real HTTP response is ``200`` and carries the expected Option E shape
  (plan id, lanes, per-issue availability and progress);
* the isolated ``roll_test_dml`` role's top-level and nested
  ``pg_stat_statements`` deltas do not grow with library size, proving the
  reader is set-based with no per-row N+1;
* the measured statements stay within the declared ``max_statements`` budget
  (which includes the bounded pool-checkout probes);
* the budget guard is not vacuous: one statement above the ceiling, and a
  per-row (N+1) growth pattern, both fail the corresponding budget checks.

Statement counts are isolated to the route role through
``RUST_ROLL_TEST_DATABASE_URL``; a missing ``pg_stat_statements`` view fails
the measured assertions rather than passing a low count.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import (
    ContinuityPlan,
    CustomCBLEntry,
    CustomCBLList,
    Issue,
    ReadingPlanSource,
    Thread,
    User,
)
from route_harness import (
    SQL_BUDGET_SOURCES,
    assert_declared_budget,
    cargo_example_path,
    db_counters,
    db_nested_statements,
    run_rust_example,
)

SECRET = "synthetic-continuity-plan-reader-n1-secret"
STORED_EPOCH = 1_767_225_600
ROUTE = ("GET", "/api/v2/continuity-plans/{plan_id}/reader")
BINARY = str(cargo_example_path("http_continuity_plans"))

SMALL_ISSUES = 3
LARGE_ISSUES = 90
GROWTH_TOLERANCE = 2


def _token(username: str, *, jti: str) -> str:
    """Mint an access token whose credential epoch matches the seeded owner."""
    return jwt.encode(
        {
            "sub": username,
            "jti": jti,
            "type": "access",
            "pc": STORED_EPOCH,
            "exp": 4_102_444_800,
        },
        SECRET,
        algorithm="HS256",
    )


def _assert_no_growth(small: int, large: int) -> None:
    """Fail when the statement count grows with the library size (N+1 guard)."""
    assert large <= small + GROWTH_TOLERANCE, (
        f"statement count grew with library size: {small} -> {large}"
    )


async def _seed_plan(
    db: AsyncSession,
    owner: User,
    *,
    issue_count: int,
    suffix: str,
) -> int:
    """Create one thread with ``issue_count`` issues and its authoritative list.

    Returns:
        The identifier of the freshly seeded Option E continuity plan.
    """
    thread = Thread(
        user_id=owner.id,
        title=f"Reader Series {suffix}",
        format="Comic",
        queue_position=1,
        issues_remaining=max(issue_count - 1, 0),
        total_issues=issue_count,
        status="active",
    )
    db.add(thread)
    await db.flush()

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="read" if position < issue_count else "unread",
        )
        for position in range(1, issue_count + 1)
    ]
    db.add_all(issues)
    await db.flush()

    reading_list = CustomCBLList(user_id=owner.id, name=f"Reader List {suffix}", mode="strict")
    db.add(reading_list)
    await db.flush()

    db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=issue.position)
            for issue in issues
        ]
    )
    plan = ContinuityPlan(
        user_id=owner.id,
        name=f"Reader Plan {suffix}",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    db.add(plan)
    await db.flush()
    db.add(
        ReadingPlanSource(
            plan_id=plan.id,
            raw_source_path=f"custom-cbl:{reading_list.id}",
            custom_cbl_list_id=reading_list.id,
        )
    )
    await db.commit()
    return plan.id


@pytest.mark.asyncio
async def test_reader_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from a small to a large Reading List."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"cpreader_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username, password_changed_at=None)
            db.add(owner)
            await db.flush()
            owner_id = owner.id
            small_plan_id = await _seed_plan(
                db, owner, issue_count=SMALL_ISSUES, suffix="small"
            )

        token = _token(username, jti=f"jti-{uuid4().hex}")
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        _, _, small_top_before = await db_counters(engine)
        small_nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(
            BINARY,
            {**env, "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{small_plan_id}/reader"},
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("execution_mode") == "option_e"
        assert small_body.get("plan_id") == small_plan_id
        lanes = small_body.get("lanes")
        assert isinstance(lanes, list) and len(lanes) == 1
        assert len(lanes[0]["issues"]) == SMALL_ISSUES
        assert small_body["progress"] == {
            "total_issues": SMALL_ISSUES,
            "read_issues": SMALL_ISSUES - 1,
        }
        _, _, small_top_after = await db_counters(engine)
        small_nested_after = await db_nested_statements(engine)
        small_top = (
            small_top_after - small_top_before
            if small_top_before is not None and small_top_after is not None
            else None
        )
        small_nested = (
            small_nested_after - small_nested_before
            if small_nested_before is not None and small_nested_after is not None
            else None
        )

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner_row = await db.get(User, owner_id)
            assert owner_row is not None
            large_plan_id = await _seed_plan(
                db, owner_row, issue_count=LARGE_ISSUES, suffix="large"
            )

        _, _, large_top_before = await db_counters(engine)
        large_nested_before = await db_nested_statements(engine)
        large_response, _, _, _ = await run_rust_example(
            BINARY,
            {**env, "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{large_plan_id}/reader"},
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        large_lanes = large_body.get("lanes")
        assert isinstance(large_lanes, list) and len(large_lanes) == 1
        assert len(large_lanes[0]["issues"]) == LARGE_ISSUES
        _, _, large_top_after = await db_counters(engine)
        large_nested_after = await db_nested_statements(engine)
        large_top = (
            large_top_after - large_top_before
            if large_top_before is not None and large_top_after is not None
            else None
        )
        large_nested = (
            large_nested_after - large_nested_before
            if large_nested_before is not None and large_nested_after is not None
            else None
        )

        print(f"reader small_top={small_top} large_top={large_top}", flush=True)
        assert small_top is not None and large_top is not None, "pg_stat_statements is required"
        assert small_nested is not None and large_nested is not None, (
            "pg_stat_statements track=all is required for nested statements"
        )
        assert_declared_budget(ROUTE[0], ROUTE[1], small_top, large_top)
        _assert_no_growth(small_top, large_top)
        # Nested trigger/function work is measured separately and stays flat.
        assert small_nested == 0
        _assert_no_growth(small_nested, large_nested)
    finally:
        await engine.dispose()


def test_reader_budget_rejects_extra_statement_and_n1() -> None:
    """Prove the reader budget guards fail on an extra query and on N+1 growth."""
    document = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))
    budget = next(
        entry["sql_budget"]
        for entry in document["operations"]
        if entry["method"] == ROUTE[0] and entry["path"] == ROUTE[1]
    )
    maximum = budget["max_statements"]
    assert maximum > 0

    # A single deliberately added query must exceed the ceiling and fail.
    with pytest.raises(AssertionError):
        assert_declared_budget(ROUTE[0], ROUTE[1], maximum + 1)

    # A per-row (N+1) pattern must fail the growth guard.
    with pytest.raises(AssertionError):
        _assert_no_growth(maximum, maximum + LARGE_ISSUES)

    # The pinned ceiling itself must be accepted by the same guards.
    assert_declared_budget(ROUTE[0], ROUTE[1], maximum)
    _assert_no_growth(maximum, maximum)