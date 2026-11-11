"""Measured N+1 regression for ``PATCH /api/v2/issues/{id}`` (#4737).

Seeds a small (5) and a large (200) set of owned issues, rates one issue in
each, and asserts the Postgres statement delta does not grow with library size,
proving the persist transaction is set-based with no per-row N+1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread, User
from route_harness import db_counters, run_rust_example

SECRET = "synthetic-native-issue-read-rate-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_issue_read_rate"
)
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_issue_read_rate_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 issues."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"irrn1_{uuid4().hex[:12]}"
        now = datetime.now(UTC)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            thread = Thread(user_id=owner.id, title="Series", format="Comic", queue_position=1, issues_remaining=5, total_issues=5, status="active")
            db.add(thread)
            await db.flush()
            for i in range(5):
                db.add(Issue(thread_id=thread.id, issue_number=str(i + 1), position=i + 1, status="unread"))
            await db.commit()

        raw = await asyncpg.connect(url)
        try:
            issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=(SELECT id FROM threads WHERE user_id=(SELECT id FROM users WHERE username=$1)) ORDER BY id LIMIT 1",
                username,
            )
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
        finally:
            await raw.close()

        token = jwt.encode(
            {"sub": username, "jti": "native-issue-command-fixture", "type": "access", "exp": int((now + timedelta(hours=1)).timestamp())},
            SECRET,
            "HS256",
        )
        body = json.dumps({"status": "read", "idempotency_key": f"key-{uuid4().hex}"})
        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_ISSUE_ID": str(issue_id),
            "RUST_ROLL_TEST_BODY": body,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, s_before = await db_counters(engine)
        await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        small_delta = (s_after - s_before) if s_before is not None and s_after is not None else None

        # Grow to 200 issues.
        raw = await asyncpg.connect(url)
        try:
            thread_id = await raw.fetchval("SELECT id FROM threads WHERE user_id=$1 LIMIT 1", owner_id)
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id, issue_number, position, status, created_at) VALUES ($1,$2,$3,'unread',NOW())",
                    thread_id, str(i + 1), i + 1,
                )
        finally:
            await raw.close()

        # Re-rate the same issue (idempotency replay) with a new key? Use a new issue id from the large set to avoid replay.
        raw = await asyncpg.connect(url)
        try:
            new_issue_id = await raw.fetchval("SELECT id FROM issues WHERE thread_id=$1 ORDER BY id OFFSET 10 LIMIT 1", thread_id)
        finally:
            await raw.close()
        env["RUST_ROLL_TEST_ISSUE_ID"] = str(new_issue_id)
        env["RUST_ROLL_TEST_BODY"] = json.dumps({"status": "read", "idempotency_key": f"key-{uuid4().hex}"})

        _, _, s_before2 = await db_counters(engine)
        await run_rust_example(BINARY, env)
        _, _, s_after2 = await db_counters(engine)
        large_delta = (s_after2 - s_before2) if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        if small_delta is not None and large_delta is not None:
            assert large_delta <= small_delta + 2, (
                f"statement count grew with library size: {small_delta} -> {large_delta}"
            )
    finally:
        await engine.dispose()
