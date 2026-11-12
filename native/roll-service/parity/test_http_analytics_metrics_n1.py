"""Measured N+1 regression for ``GET /api/v2/analytics/metrics`` (#4737).

Seeds a small (5) and a large (200) set of owned threads/events, runs the
native Rust analytics metrics endpoint against each, and asserts the Postgres
statement delta does not grow with data size, proving the single folded
statement is set-based with no per-row N+1.
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Event, Thread, User
from route_harness import assert_declared_budget, db_counters, run_rust_example

SECRET = "synthetic-native-analytics-metrics-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_analytics_metrics"
)
BINARY = str(EXAMPLE)


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_analytics_metrics_statements_do_not_grow_with_data_size() -> None:
    """Statement delta must not grow from 5 to 200 rows."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"amn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                t = Thread(user_id=owner.id, title=f"Series {i+1}", format="Comic", queue_position=i+1, issues_remaining=2, total_issues=3, status="active")
                db.add(t)
                await db.flush()
                db.add(Event(user_id=owner.id, type="roll", thread_id=t.id, die=6, result=1, timestamp=datetime.now(UTC)))
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_URI": "/api/v2/analytics/metrics",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict) and small_body.get("total_threads") == 5
        _, _, s_after = await db_counters(engine)
        small_delta = (s_after - s_before) if s_before is not None and s_after is not None else None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                tid = await raw.fetchval(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) VALUES ($1,$2,'Comic',$3,2,3,'active') RETURNING id",
                    owner_id, f"Series {i+1}", i + 1,
                )
                await raw.execute(
                    "INSERT INTO events (user_id,type,thread_id,die,result,timestamp) VALUES ($1,'roll',$2,6,1,NOW())",
                    owner_id, tid,
                )
        finally:
            await raw.close()

        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict) and large_body.get("total_threads") == 200
        _, _, s_after2 = await db_counters(engine)
        large_delta = (s_after2 - s_before2) if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", "/api/v2/analytics/metrics", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with data size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()
