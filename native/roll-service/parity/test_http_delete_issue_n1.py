"""Measured N+1 regression for ``DELETE /api/v2/issues/{issue_id}`` (#5148).

Seeds a small (5) and a large (200) library for the same reader, deletes an
issue in each, and asserts the Postgres statement delta does not grow
with library size.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread, User
from route_harness import (
    assert_declared_budget,
    cargo_example_path,
    db_counters,
    db_nested_statements,
    run_rust_example,
)

SECRET = "synthetic-native-delete-issue-secret"
EXAMPLE = cargo_example_path("http_delete_issue")
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_delete_issue_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 issues."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"di_{uuid4().hex[:12]}"
        now = datetime.now(UTC)
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
                status="active",
            )
            db.add(thread)
            await db.flush()
            issues = []
            for i in range(5):
                issue = Issue(
                    thread_id=thread.id,
                    issue_number=str(i + 1),
                    position=i + 1,
                    status="unread",
                )
                db.add(issue)
                issues.append(issue)
            await db.commit()

        raw = await asyncpg.connect(url)
        try:
            issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position LIMIT 1",
                thread.id,
            )
            await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
        finally:
            await raw.close()

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-delete-issue-fixture",
                "type": "access",
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            SECRET,
            "HS256",
        )
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_ISSUE_ID": str(issue_id),
            "RUST_ROLL_POOL_SIZE": "2",
        }
        n_before = await db_nested_statements(engine)
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 204, small_response
        _, _, s_after = await db_counters(engine)
        n_after = await db_nested_statements(engine)
        small_delta = (
            (s_after - s_before) if s_before is not None and s_after is not None else None
        )
        small_nested = (
            (n_after - n_before) if n_before is not None and n_after is not None else None
        )

        # The 204 carries no body; prove the owned issue row is actually gone.
        raw = await asyncpg.connect(url)
        try:
            remaining = await raw.fetchval("SELECT count(*) FROM issues WHERE id=$1", issue_id)
        finally:
            await raw.close()
        assert remaining == 0, "deleted issue still exists"

        # Grow to 200 issues
        raw = await asyncpg.connect(url)
        try:
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) VALUES ($1,$2,$3,'unread',NOW())",
                    thread.id,
                    str(i + 1),
                    i + 1,
                )
        finally:
            await raw.close()

        # Delete a different issue from the large set
        raw = await asyncpg.connect(url)
        try:
            new_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position OFFSET 10 LIMIT 1",
                thread.id,
            )
        finally:
            await raw.close()

        env["RUST_ROLL_TEST_ISSUE_ID"] = str(new_issue_id)

        n_before2 = await db_nested_statements(engine)
        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 204, large_response
        _, _, s_after2 = await db_counters(engine)
        n_after2 = await db_nested_statements(engine)
        large_delta = (
            (s_after2 - s_before2)
            if s_before2 is not None and s_after2 is not None
            else None
        )
        large_nested = (
            (n_after2 - n_before2) if n_before2 is not None and n_after2 is not None else None
        )

        raw = await asyncpg.connect(url)
        try:
            remaining = await raw.fetchval(
                "SELECT count(*) FROM issues WHERE id=$1", new_issue_id
            )
        finally:
            await raw.close()
        assert remaining == 0, "deleted issue still exists"

        print(
            f"small_delta={small_delta} large_delta={large_delta} "
            f"small_nested={small_nested} large_nested={large_nested}",
            flush=True,
        )
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        # The delete also fires foreign-key/ownership trigger work. Nested
        # trigger statements are measured separately from the declared
        # application/transaction-control budget and must not grow with data.
        assert small_nested is not None and large_nested is not None, (
            "pg_stat_statements track=all is required for nested trigger statements"
        )
        assert large_nested <= small_nested + 2, (
            f"nested trigger statements grew with library size: "
            f"{small_nested} -> {large_nested}"
        )
        assert_declared_budget("DELETE", "/api/v2/issues/{issue_id}", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()