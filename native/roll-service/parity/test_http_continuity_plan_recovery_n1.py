"""Measured SQL budget for the continuity-plan recovery operations (#5146).

Covers both recovery routes against the canonical Alembic schema with the
mounted native Rust binary:

* ``GET /api/v2/continuity-plans/{plan_id}/recovery`` (owner-scoped preview);
* ``POST /api/v2/continuity-plans/{plan_id}/recovery`` (idempotent relink).

Each route is exercised on a small and a large fixture. The isolated
``roll_test_dml`` role's top-level and nested ``pg_stat_statements`` deltas
must not grow with data size (no per-row N+1), must stay within the declared
``max_statements`` budget (including pool-checkout probes), and the real HTTP
response and data shape are asserted. The budget guard is proven non-vacuous:
one extra statement and an N+1 growth pattern both fail.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import (
    ContinuityPlan,
    CustomCBLEntry,
    CustomCBLList,
    Issue,
    ReadingPlanIssue,
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

SECRET = "synthetic-continuity-plan-recovery-n1-secret"
STORED_EPOCH = 1_767_225_600
GET_ROUTE = ("GET", "/api/v2/continuity-plans/{plan_id}/recovery")
POST_ROUTE = ("POST", "/api/v2/continuity-plans/{plan_id}/recovery")
BINARY = str(cargo_example_path("http_continuity_plans"))

SMALL_LISTS = 2
LARGE_LISTS = 60
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
    """Fail when the statement count grows with the fixture size (N+1 guard)."""
    assert large <= small + GROWTH_TOLERANCE, (
        f"statement count grew with fixture size: {small} -> {large}"
    )


async def _seed_thread_with_issues(
    db: AsyncSession, owner: User, *, count: int, suffix: str
) -> list[Issue]:
    """Create one owned thread with ``count`` unread issues."""
    thread = Thread(
        user_id=owner.id,
        title=f"Recovery Series {suffix}",
        format="Comic",
        queue_position=1,
        issues_remaining=count,
        total_issues=count,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=str(position), position=position, status="unread")
        for position in range(1, count + 1)
    ]
    db.add_all(issues)
    await db.flush()
    return issues


async def _seed_linked_plan(
    db: AsyncSession, owner: User, *, issue_count: int, suffix: str
) -> tuple[int, int]:
    """Create a plan linked to exactly one authoritative Reading List.

    Returns:
        The ``(plan_id, list_id)`` of the seeded linked plan.
    """
    issues = await _seed_thread_with_issues(db, owner, count=issue_count, suffix=suffix)
    reading_list = CustomCBLList(user_id=owner.id, name=f"Recovery List {suffix}", mode="strict")
    db.add(reading_list)
    await db.flush()
    db.add_all(
        CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=issue.position)
        for issue in issues
    )
    plan = ContinuityPlan(
        user_id=owner.id,
        name=f"Recovery Plan {suffix}",
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
    db.add_all(
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id=f"reading-list:{reading_list.id}:{issue.id}",
            issue_id=issue.id,
            lane_id="reading-list",
            display_position=issue.position,
        )
        for issue in issues
    )
    await db.commit()
    return plan.id, reading_list.id


async def _seed_orphan_plan(
    db: AsyncSession, owner: User, *, suffix: str
) -> tuple[int, int]:
    """Create an unlinked plan and a target Reading List it can relink to.

    Returns:
        The ``(plan_id, list_id)`` of the seeded orphan plan and target list.
    """
    plan = ContinuityPlan(
        user_id=owner.id,
        name=f"Orphan Plan {suffix}",
        ordering_mode="strict_sequential",
        nodes_json=[],
        lanes_json=[],
    )
    target = CustomCBLList(user_id=owner.id, name=f"Target List {suffix}", mode="loose")
    db.add_all([plan, target])
    await db.flush()
    await db.commit()
    return plan.id, target.id


async def _timestamps(engine, plan_id: int, list_id: int) -> tuple[str, str]:
    """Read the ``updated_at::text`` values the relink optimistic lock compares."""
    async with engine.connect() as connection:
        plan_ts = (
            await connection.execute(
                text("SELECT updated_at::text FROM continuity_plans WHERE id = :id"),
                {"id": plan_id},
            )
        ).scalar_one()
        list_ts = (
            await connection.execute(
                text("SELECT updated_at::text FROM custom_cbl_lists WHERE id = :id"),
                {"id": list_id},
            )
        ).scalar_one()
    return plan_ts, list_ts


def _relink_body(plan_ts: str, list_ts: str, list_id: int) -> str:
    """Build the JSON relink request body for the given optimistic-lock stamps."""
    return json.dumps(
        {
            "list_id": list_id,
            "expected_plan_updated_at": plan_ts,
            "expected_list_updated_at": list_ts,
            "confirm": True,
        }
    )


@pytest.mark.asyncio
async def test_recovery_preview_statements_do_not_grow_with_data() -> None:
    """Preview statement delta must not grow from a small to a large library."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"cprecovery_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username, password_changed_at=None)
            db.add(owner)
            await db.flush()
            owner_id = owner.id
            small_plan_id, small_list_id = await _seed_linked_plan(
                db, owner, issue_count=2, suffix="small"
            )

        token = _token(username, jti=f"jti-{uuid4().hex}")
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        _, _, small_before = await db_counters(engine)
        small_nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(
            BINARY,
            {**env, "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{small_plan_id}/recovery"},
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "linked"
        assert small_body.get("linked_list_id") == small_list_id
        assert isinstance(small_body.get("retained_steps"), list)
        assert small_body["retained_steps"]
        _, _, small_after = await db_counters(engine)
        small_nested_after = await db_nested_statements(engine)
        small_delta = small_after - small_before if small_after is not None else None
        small_nested = (
            small_nested_after - small_nested_before
            if small_nested_before is not None and small_nested_after is not None
            else None
        )

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner_row = await db.get(User, owner_id)
            assert owner_row is not None
            large_plan_id, _ = await _seed_linked_plan(
                db, owner_row, issue_count=4, suffix="large"
            )
            # Many additional candidate lists must stay in one aggregate statement.
            db.add_all(
                CustomCBLList(
                    user_id=owner.id, name=f"Bulk List {position}", mode="loose"
                )
                for position in range(LARGE_LISTS)
            )
            await db.commit()

        _, _, large_before = await db_counters(engine)
        large_nested_before = await db_nested_statements(engine)
        large_response, _, _, _ = await run_rust_example(
            BINARY,
            {**env, "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{large_plan_id}/recovery"},
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "linked"
        large_candidates = large_body.get("candidates")
        assert isinstance(large_candidates, list)
        # The plan's linked list plus the bulk candidate lists are all returned.
        assert len(large_candidates) == LARGE_LISTS + 1
        _, _, large_after = await db_counters(engine)
        large_nested_after = await db_nested_statements(engine)
        large_delta = large_after - large_before if large_after is not None else None
        large_nested = (
            large_nested_after - large_nested_before
            if large_nested_before is not None and large_nested_after is not None
            else None
        )

        print(
            f"recovery-preview small={small_delta} large={large_delta}",
            flush=True,
        )
        assert small_delta is not None and large_delta is not None, (
            "pg_stat_statements is required"
        )
        assert small_nested is not None and large_nested is not None, (
            "pg_stat_statements track=all is required for nested statements"
        )
        assert_declared_budget(GET_ROUTE[0], GET_ROUTE[1], small_delta, large_delta)
        _assert_no_growth(small_delta, large_delta)
        assert small_nested == 0
        _assert_no_growth(small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_relink_statements_do_not_grow_with_data() -> None:
    """Relink statement delta must not grow with unrelated library size."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"cprelink_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username, password_changed_at=None)
            db.add(owner)
            await db.flush()
            owner_id = owner.id
            small_plan_id, small_list_id = await _seed_orphan_plan(db, owner, suffix="small")

        token = _token(username, jti=f"jti-{uuid4().hex}")
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        plan_ts, list_ts = await _timestamps(engine, small_plan_id, small_list_id)
        body = _relink_body(plan_ts, list_ts, small_list_id)

        _, _, small_before = await db_counters(engine)
        small_nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(
            BINARY,
            {
                **env,
                "RUST_ROLL_TEST_METHOD": "POST",
                "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{small_plan_id}/recovery",
                "RUST_ROLL_TEST_BODY": body,
            },
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "relinked"
        assert small_body.get("list_id") == small_list_id
        _, _, small_after = await db_counters(engine)
        small_nested_after = await db_nested_statements(engine)
        small_delta = small_after - small_before if small_after is not None else None
        small_nested = (
            small_nested_after - small_nested_before
            if small_nested_before is not None and small_nested_after is not None
            else None
        )

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner_row = await db.get(User, owner_id)
            assert owner_row is not None
            large_plan_id, large_list_id = await _seed_orphan_plan(
                db, owner_row, suffix="large"
            )
            # Unrelated bulk data the relink path never reads must not add statements.
            db.add_all(
                CustomCBLList(user_id=owner.id, name=f"Bulk Target {position}", mode="loose")
                for position in range(LARGE_LISTS)
            )
            await db.commit()

        plan_ts, list_ts = await _timestamps(engine, large_plan_id, large_list_id)
        body = _relink_body(plan_ts, list_ts, large_list_id)

        _, _, large_before = await db_counters(engine)
        large_nested_before = await db_nested_statements(engine)
        large_response, _, _, _ = await run_rust_example(
            BINARY,
            {
                **env,
                "RUST_ROLL_TEST_METHOD": "POST",
                "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{large_plan_id}/recovery",
                "RUST_ROLL_TEST_BODY": body,
            },
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "relinked"
        assert large_body.get("list_id") == large_list_id
        _, _, large_after = await db_counters(engine)
        large_nested_after = await db_nested_statements(engine)
        large_delta = large_after - large_before if large_after is not None else None
        large_nested = (
            large_nested_after - large_nested_before
            if large_nested_before is not None and large_nested_after is not None
            else None
        )

        print(f"recovery-relink small={small_delta} large={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, (
            "pg_stat_statements is required"
        )
        assert small_nested is not None and large_nested is not None, (
            "pg_stat_statements track=all is required for nested statements"
        )
        assert_declared_budget(POST_ROUTE[0], POST_ROUTE[1], small_delta, large_delta)
        _assert_no_growth(small_delta, large_delta)
        assert small_nested == 0
        _assert_no_growth(small_nested, large_nested)
    finally:
        await engine.dispose()


def test_recovery_budgets_reject_extra_statement_and_n1() -> None:
    """Prove the recovery budget guards fail on an extra query and on N+1 growth."""
    document = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))
    for route in (GET_ROUTE, POST_ROUTE):
        budget = next(
            entry["sql_budget"]
            for entry in document["operations"]
            if entry["method"] == route[0] and entry["path"] == route[1]
        )
        maximum = budget["max_statements"]
        assert maximum > 0

        # A single deliberately added query must exceed the ceiling and fail.
        with pytest.raises(AssertionError):
            assert_declared_budget(route[0], route[1], maximum + 1)

        # A per-row (N+1) pattern must fail the growth guard.
        with pytest.raises(AssertionError):
            _assert_no_growth(maximum, maximum + LARGE_LISTS)

        # The pinned ceiling itself must be accepted by the same guards.
        assert_declared_budget(route[0], route[1], maximum)
        _assert_no_growth(maximum, maximum)