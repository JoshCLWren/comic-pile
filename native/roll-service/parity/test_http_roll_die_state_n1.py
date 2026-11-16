"""Measured statement-count regression for ``GET /api/v2/roll/die-state`` (#4737).

Runs the native Rust die-state resource for a seeded reader and asserts the
Postgres statement delta stays bounded, proving the single folded statement is
set-based with no per-row N+1.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread, User
from route_harness import (
    StatementBreakdown,
    assert_budget_rejects_extra_and_n_plus_one,
    assert_measured_budget_contract,
    cargo_example_path,
    db_statement_breakdown,
    reset_statement_stats,
    run_rust_example,
)

SECRET = "synthetic-native-roll-die-state-n1-secret"
STORED_EPOCH = 1_767_225_600
EXAMPLE = cargo_example_path("http_roll_resources")
BINARY = str(EXAMPLE)


def _token(username: str, *, jti: str) -> str:
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


@pytest.mark.asyncio
async def test_roll_die_state_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 threads."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rdn1_{uuid4().hex[:12]}"
        jti = f"jti-{uuid4().hex}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(
                username=username,
                password_changed_at=datetime.fromtimestamp(STORED_EPOCH, tz=UTC),
            )
            db.add(owner)
            await db.flush()
            for i in range(5):
                t = Thread(
                    user_id=owner.id,
                    title=f"Series {i + 1}",
                    format="Comic",
                    queue_position=i + 1,
                    issues_remaining=2,
                    total_issues=2,
                    status="active",
                )
                db.add(t)
                await db.flush()
                db.add(
                    Issue(
                        thread_id=t.id,
                        issue_number="1",
                        position=1,
                        status="unread",
                    )
                )
            await db.commit()
            token = _token(username, jti=jti)

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_URI": "/api/v2/roll/die-state",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        await reset_statement_stats()
        breakdown_before = await db_statement_breakdown(engine)
        assert breakdown_before is not None
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("default_die") == 6
        assert small_body.get("ladder") == [2, 4, 6, 8, 10, 12, 20]
        assert isinstance(small_body.get("die"), int)
        assert "last_roll" in small_body
        breakdown_after = await db_statement_breakdown(engine)
        assert breakdown_after is not None
        small_delta = StatementBreakdown(
            application=breakdown_after.application - breakdown_before.application,
            transaction_control=(
                breakdown_after.transaction_control - breakdown_before.transaction_control
            ),
            runtime_overhead=(
                breakdown_after.runtime_overhead - breakdown_before.runtime_overhead
            ),
            nested=breakdown_after.nested - breakdown_before.nested,
        )

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                tid = await raw.fetchval(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) "
                    "VALUES ($1,$2,'Comic',$3,2,2,'active') RETURNING id",
                    owner_id,
                    f"Series {i + 1}",
                    i + 1,
                )
                await raw.execute(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                    "VALUES ($1,'1',1,'unread',NOW())",
                    tid,
                )
        finally:
            await raw.close()

        await reset_statement_stats()
        large_before = await db_statement_breakdown(engine)
        assert large_before is not None
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("default_die") == 6
        assert large_body.get("die") == small_body.get("die")
        large_after = await db_statement_breakdown(engine)
        assert large_after is not None
        large_delta = StatementBreakdown(
            application=large_after.application - large_before.application,
            transaction_control=large_after.transaction_control - large_before.transaction_control,
            runtime_overhead=large_after.runtime_overhead - large_before.runtime_overhead,
            nested=large_after.nested - large_before.nested,
        )

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert_measured_budget_contract(
            "GET",
            "/api/v2/roll/die-state",
            small_delta,
            large_delta,
        )
        # The same budget test must reject a deliberately added extra query and
        # an N+1 burst that only appears for the large fixture.
        assert_budget_rejects_extra_and_n_plus_one(
            "GET",
            "/api/v2/roll/die-state",
            small_delta,
            large_delta,
        )
        assert small_delta.nested == large_delta.nested == 0
    finally:
        await engine.dispose()
