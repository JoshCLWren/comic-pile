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
from route_harness import assert_declared_budget, cargo_example_path, db_counters, run_rust_example

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
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("default_die") == 6
        assert small_body.get("ladder") == [2, 4, 6, 8, 10, 12, 20]
        assert isinstance(small_body.get("die"), int)
        assert "last_roll" in small_body
        _, _, s_after = await db_counters(engine)
        small_delta = (
            s_after - s_before if s_before is not None and s_after is not None else None
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

        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("default_die") == 6
        assert large_body.get("die") == small_body.get("die")
        _, _, s_after2 = await db_counters(engine)
        large_delta = (
            s_after2 - s_before2 if s_before2 is not None and s_after2 is not None else None
        )

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", "/api/v2/roll/die-state", small_delta, large_delta)
        assert large_delta <= small_delta, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()
