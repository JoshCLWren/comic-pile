"""Measured N+1 regression for ``POST /api/v2/dependencies/`` (#5148).

Seeds a small (5) and a large (200) library for the same reader, creates a
dependency in each, and asserts the Postgres statement delta does not grow
with library size.
"""

from __future__ import annotations

import json
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

SECRET = "synthetic-native-create-dependency-secret"
EXAMPLE = cargo_example_path("http_create_dependency")
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_create_dependency_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 threads."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"cd_{uuid4().hex[:12]}"
        now = datetime.now(UTC)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            # Create source and target threads
            source_thread = Thread(
                user_id=owner.id,
                title="Source Series",
                format="Comic",
                queue_position=1,
                issues_remaining=5,
                total_issues=5,
                status="active",
            )
            db.add(source_thread)
            await db.flush()
            target_thread = Thread(
                user_id=owner.id,
                title="Target Series",
                format="Comic",
                queue_position=2,
                issues_remaining=5,
                total_issues=5,
                status="active",
            )
            db.add(target_thread)
            await db.flush()
            # Add issues to both threads
            for i in range(5):
                db.add(
                    Issue(
                        thread_id=source_thread.id,
                        issue_number=str(i + 1),
                        position=i + 1,
                        status="unread",
                    )
                )
                db.add(
                    Issue(
                        thread_id=target_thread.id,
                        issue_number=str(i + 1),
                        position=i + 1,
                        status="unread",
                    )
                )
            await db.commit()

        raw = await asyncpg.connect(url)
        try:
            source_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position LIMIT 1",
                source_thread.id,
            )
            target_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position LIMIT 1",
                target_thread.id,
            )
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
        finally:
            await raw.close()

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-create-dependency-fixture",
                "type": "access",
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            SECRET,
            "HS256",
        )
        body = json.dumps(
            {
                "source_type": "issue",
                "source_id": source_issue_id,
                "target_type": "issue",
                "target_id": target_issue_id,
            }
        )
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_BODY": body,
            "RUST_ROLL_POOL_SIZE": "2",
        }
        n_before = await db_nested_statements(engine)
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 201, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        small_dependency_id = small_body.get("id")
        assert isinstance(small_dependency_id, int)
        _, _, s_after = await db_counters(engine)
        n_after = await db_nested_statements(engine)
        small_delta = (
            (s_after - s_before) if s_before is not None and s_after is not None else None
        )
        small_nested = (
            (n_after - n_before) if n_before is not None and n_after is not None else None
        )

        # Grow to 200 threads (100 source, 100 target)
        raw = await asyncpg.connect(url)
        try:
            for i in range(5, 100):
                tid = await raw.fetchval(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) VALUES ($1,$2,'Comic',$3,5,5,'active') RETURNING id",
                    owner_id,
                    f"Source Series {i+1}",
                    i * 2 + 1,
                )
                for j in range(5):
                    await raw.execute(
                        "INSERT INTO issues (thread_id,issue_number,position,status,created_at) VALUES ($1,$2,$3,'unread',NOW())",
                        tid,
                        str(j + 1),
                        j + 1,
                    )
            for i in range(5, 100):
                tid = await raw.fetchval(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) VALUES ($1,$2,'Comic',$3,5,5,'active') RETURNING id",
                    owner_id,
                    f"Target Series {i+1}",
                    i * 2 + 2,
                )
                for j in range(5):
                    await raw.execute(
                        "INSERT INTO issues (thread_id,issue_number,position,status,created_at) VALUES ($1,$2,$3,'unread',NOW())",
                        tid,
                        str(j + 1),
                        j + 1,
                    )
        finally:
            await raw.close()

        # Create a new dependency in the large library
        raw = await asyncpg.connect(url)
        try:
            new_source_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=(SELECT id FROM threads WHERE user_id=$1 AND title='Source Series 100' LIMIT 1) ORDER BY position LIMIT 1",
                owner_id,
            )
            new_target_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=(SELECT id FROM threads WHERE user_id=$1 AND title='Target Series 100' LIMIT 1) ORDER BY position LIMIT 1",
                owner_id,
            )
        finally:
            await raw.close()

        body = json.dumps(
            {
                "source_type": "issue",
                "source_id": new_source_issue_id,
                "target_type": "issue",
                "target_id": new_target_issue_id,
            }
        )
        env["RUST_ROLL_TEST_BODY"] = body

        n_before2 = await db_nested_statements(engine)
        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 201, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        large_dependency_id = large_body.get("id")
        assert isinstance(large_dependency_id, int)
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

        print(
            f"small_delta={small_delta} large_delta={large_delta} "
            f"small_nested={small_nested} large_nested={large_nested}",
            flush=True,
        )
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        # The dependencies row also fires the compatibility trigger. Nested
        # trigger statements are measured separately from the declared
        # application/transaction-control budget and must not grow with data.
        assert small_nested is not None and large_nested is not None, (
            "pg_stat_statements track=all is required for nested trigger statements"
        )
        assert large_nested <= small_nested + 2, (
            f"nested trigger statements grew with library size: "
            f"{small_nested} -> {large_nested}"
        )
        assert_declared_budget("POST", "/api/v2/dependencies/", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()