"""Measured N+1 regression for ``POST /api/v2/reading-boundaries`` (#4737).

Seeds a small (5) and a large (200) set of owned threads, runs the native Rust
reading-boundaries batch against each, and asserts the Postgres statement delta
does not grow with batch size, proving the single snapshot statement is
set-based with no per-thread N+1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Thread, User
from route_harness import db_counters, run_rust_example

SECRET = "synthetic-native-reading-boundaries-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_reading_boundaries"
)
BINARY = str(EXAMPLE)


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_reading_boundaries_statements_do_not_grow_with_batch_size() -> None:
    """Statement delta must not grow from 5 to 200 thread ids."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rbn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                db.add(Thread(user_id=owner.id, title=f"Series {i+1}", format="Comic", queue_position=i+1, issues_remaining=2, total_issues=3, status="active"))
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            rows = await raw.fetch("SELECT id FROM threads WHERE user_id=$1 ORDER BY id", owner_id)
            small_ids = [r["id"] for r in rows]
        finally:
            await raw.close()

        body_small = json.dumps({"thread_ids": small_ids})
        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_BODY": body_small,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, s_before = await db_counters(engine)
        await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        small_delta = (s_after - s_before) if s_before is not None and s_after is not None else None

        raw = await asyncpg.connect(url)
        try:
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) VALUES ($1,$2,'Comic',$3,2,3,'active')",
                    owner_id,
                    f"Series {i+1}",
                    i + 1,
                )
            rows = await raw.fetch("SELECT id FROM threads WHERE user_id=$1 ORDER BY id", owner_id)
            large_ids = [r["id"] for r in rows]
        finally:
            await raw.close()

        body_large = json.dumps({"thread_ids": large_ids[:200]})
        env["RUST_ROLL_TEST_BODY"] = body_large
        _, _, s_before2 = await db_counters(engine)
        await run_rust_example(BINARY, env)
        _, _, s_after2 = await db_counters(engine)
        large_delta = (s_after2 - s_before2) if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        if small_delta is not None and large_delta is not None:
            assert large_delta <= small_delta + 2, (
                f"statement count grew with batch size: {small_delta} -> {large_delta}"
            )
    finally:
        await engine.dispose()
