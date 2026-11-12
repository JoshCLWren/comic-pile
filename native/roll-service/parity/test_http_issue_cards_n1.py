"""Measured N+1 regression for ``POST /api/v2/issues/cards`` (#4737).

Seeds a small (5) and a large (200) set of owned issues, runs the native Rust
issue-card projection against each, and asserts the Postgres statement delta
does not grow with batch size, proving the single ANY-filtered statement is
set-based with no per-card N+1.
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

from app.models import Issue, Thread, User
from route_harness import assert_declared_budget, db_counters, run_rust_example

SECRET = "synthetic-native-issue-cards-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_issue_cards"
)
BINARY = str(EXAMPLE)


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_issue_cards_statements_do_not_grow_with_batch_size() -> None:
    """Statement delta must not grow from 5 to 200 issue ids."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"cardsn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            thread = Thread(
                user_id=owner.id,
                title="Series",
                format="Comic",
                queue_position=1,
                issues_remaining=5,
                total_issues=5,
            )
            db.add(thread)
            await db.flush()
            for i in range(5):
                db.add(Issue(thread_id=thread.id, issue_number=str(i + 1), position=i + 1, status="unread"))
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        # fetch actual issue ids
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            rows = await raw.fetch("SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id", owner_id)
            small_issue_ids = [r["id"] for r in rows]
        finally:
            await raw.close()

        body_small = json.dumps({"issue_ids": small_issue_ids})
        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_BODY": body_small,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        small_items = small_body.get("items")
        assert isinstance(small_items, list) and len(small_items) == 5
        _, _, s_after = await db_counters(engine)
        small_delta = (s_after - s_before) if s_before is not None and s_after is not None else None

        # Grow to 200 issues.
        raw = await asyncpg.connect(url)
        try:
            thread_id = await raw.fetchval("SELECT id FROM threads WHERE user_id=$1 LIMIT 1", owner_id)
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id, issue_number, position, status, created_at) VALUES ($1,$2,$3,'unread',NOW())",
                    thread_id,
                    str(i + 1),
                    i + 1,
                )
            rows = await raw.fetch("SELECT id FROM issues WHERE thread_id=$1 ORDER BY id", thread_id)
            large_issue_ids = [r["id"] for r in rows]
        finally:
            await raw.close()

        body_large = json.dumps({"issue_ids": large_issue_ids})
        env["RUST_ROLL_TEST_BODY"] = body_large
        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        large_items = large_body.get("items")
        assert isinstance(large_items, list) and len(large_items) == 200
        _, _, s_after2 = await db_counters(engine)
        large_delta = (s_after2 - s_before2) if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("POST", "/api/v2/issues/cards", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with batch size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()
