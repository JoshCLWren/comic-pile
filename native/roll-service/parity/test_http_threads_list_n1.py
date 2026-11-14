"""Measured N+1 regression for ``GET /api/v2/threads`` (#4737).

Seeds a small (5) and a large (200) library for the same reader, runs the
native Rust threads collection against each, and asserts the Postgres statement
delta does not grow with library size, proving the single-page statement is
set-based with no per-row N+1.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Thread, User
from route_harness import cargo_example_path, assert_declared_budget, db_counters, run_rust_example

SECRET = "synthetic-native-threads-n1-secret"
EXAMPLE = (
    cargo_example_path("http_threads_list")
)
BINARY = str(EXAMPLE)


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


async def _seed(db: AsyncSession, owner: User, count: int, start: int = 0) -> None:
    for index in range(start, start + count):
        db.add(
            Thread(
                user_id=owner.id,
                title=f"Series {index + 1}",
                format="Comic",
                queue_position=index + 1,
                issues_remaining=2,
                total_issues=3,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_threads_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 threads."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"tn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            await _seed(db, owner, 5)
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_URI": "/api/v2/threads?page_size=200",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        x_before, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict) and small_body.get("active_count") == 5
        x_after, _, s_after = await db_counters(engine)
        small_delta = (s_after - s_before) if s_before is not None and s_after is not None else None

        # Grow the library to 200.
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = await db.get(User, owner.id) if False else None
        # Re-fetch owner by username not available; seed extra rows via raw SQL instead.
        import asyncpg

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for index in range(5, 200):
                await raw.execute(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) "
                    "VALUES ($1,$2,'Comic',$3,2,3,'active')",
                    owner_id,
                    f"Series {index + 1}",
                    index + 1,
                )
        finally:
            await raw.close()

        x_before2, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict) and large_body.get("active_count") == 200
        assert len(large_body["threads"]) == 200
        x_after2, _, s_after2 = await db_counters(engine)
        large_delta = (s_after2 - s_before2) if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", "/api/v2/threads", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()
