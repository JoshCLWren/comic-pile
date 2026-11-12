"""Measured N+1 regression for ``GET /api/v2/roll/bootstrap`` (#4737).

Seeds a small (5) and a large (200) library for the same reader, runs the
native Rust Roll bootstrap against each, and asserts the Postgres statement
delta does not grow with library size.
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread, User
from route_harness import assert_declared_budget, db_counters, run_rust_example

SECRET = "synthetic-native-http-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_bootstrap"
)
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_bootstrap_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 threads."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"bsn1_{uuid4().hex[:12]}"
        now = datetime.now(UTC)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                t = Thread(user_id=owner.id, title=f"Series {i+1}", format="Comic", queue_position=i+1, issues_remaining=2, total_issues=2, status="active")
                db.add(t)
                await db.flush()
                db.add(Issue(thread_id=t.id, issue_number="1", position=1, status="unread"))
            await db.commit()

        token = jwt.encode({"sub": username, "jti": "native-http-fixture", "type": "access", "exp": int((now + timedelta(hours=1)).timestamp())}, SECRET, "HS256")
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }
        init_response, _, _, _ = await run_rust_example(
            BINARY, {**env, "RUST_ROLL_TEST_INIT_ONLY": "1"}
        )
        assert init_response.get("status") == 200, init_response
        env["RUST_ROLL_TEST_SKIP_INITIALIZATION"] = "1"
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        small_rollable = small_body.get("rollable")
        assert isinstance(small_rollable, list) and len(small_rollable) == 5
        _, _, s_after = await db_counters(engine)
        small_delta = (s_after - s_before) if s_before is not None and s_after is not None else None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                tid = await raw.fetchval(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) VALUES ($1,$2,'Comic',$3,2,2,'active') RETURNING id",
                    owner_id, f"Series {i+1}", i + 1,
                )
                await raw.execute("INSERT INTO issues (thread_id,issue_number,position,status,created_at) VALUES ($1,'1',1,'unread',NOW())", tid)
        finally:
            await raw.close()

        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        large_rollable = large_body.get("rollable")
        # Roll presents at most the current d6 faces. The extra face proves
        # the 200-thread fixture reached the projection rather than returning
        # the same truncated five-row result.
        assert isinstance(large_rollable, list) and len(large_rollable) == 6
        _, _, s_after2 = await db_counters(engine)
        large_delta = (s_after2 - s_before2) if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", "/api/v2/roll/bootstrap", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()
