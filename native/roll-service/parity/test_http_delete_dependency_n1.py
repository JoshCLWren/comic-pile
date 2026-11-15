"""Measured N+1 regression for ``DELETE /api/v2/dependencies/{dependency_id}`` (#5148).

Seeds a small (5) and a large (200) library for the same reader, deletes a
dependency in each, and asserts the Postgres statement delta does not grow
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
from route_harness import cargo_example_path, assert_declared_budget, db_counters, run_rust_example

SECRET = "synthetic-native-delete-dependency-secret"
EXAMPLE = cargo_example_path("http_delete_dependency")
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_delete_dependency_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 threads."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"dd_{uuid4().hex[:12]}"
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
            source_issues = []
            target_issues = []
            for i in range(5):
                si = Issue(
                    thread_id=source_thread.id,
                    issue_number=str(i + 1),
                    position=i + 1,
                    status="unread",
                )
                db.add(si)
                source_issues.append(si)
                ti = Issue(
                    thread_id=target_thread.id,
                    issue_number=str(i + 1),
                    position=i + 1,
                    status="unread",
                )
                db.add(ti)
                target_issues.append(ti)
            await db.flush()
            # Create a dependency
            from sqlalchemy import text
            await db.execute(
                text(
                    "INSERT INTO dependencies (source_issue_id, target_issue_id, origin, classification, provenance, created_at) "
                    "VALUES (:s, :t, 'reader', 'A', 'Reader-authored through the Dependency Builder', NOW())"
                ),
                {"s": source_issues[0].id, "t": target_issues[0].id},
            )
            await db.commit()

        raw = await asyncpg.connect(url)
        try:
            dependency_id = await raw.fetchval(
                "SELECT id FROM dependencies "
                "WHERE source_issue_id = (SELECT id FROM issues WHERE thread_id = $1 ORDER BY position LIMIT 1) "
                "AND target_issue_id = (SELECT id FROM issues WHERE thread_id = $2 ORDER BY position LIMIT 1)",
                source_thread.id,
                target_thread.id,
            )
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
        finally:
            await raw.close()

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-delete-dependency-fixture",
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
            "RUST_ROLL_TEST_DEPENDENCY_ID": str(dependency_id),
            "RUST_ROLL_POOL_SIZE": "2",
        }
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        _, _, s_after = await db_counters(engine)
        small_delta = (
            (s_after - s_before) if s_before is not None and s_after is not None else None
        )

        # Grow to 200 threads (100 source, 100 target) with many dependencies
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
            # Create many dependencies
            for i in range(100):
                src_tid = await raw.fetchval(
                    "SELECT id FROM threads WHERE user_id=$1 AND title=$2", owner_id, f"Source Series {i+1}"
                )
                tgt_tid = await raw.fetchval(
                    "SELECT id FROM threads WHERE user_id=$1 AND title=$2", owner_id, f"Target Series {i+1}"
                )
                if src_tid and tgt_tid:
                    src_iid = await raw.fetchval(
                        "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position LIMIT 1", src_tid
                    )
                    tgt_iid = await raw.fetchval(
                        "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position LIMIT 1", tgt_tid
                    )
                    if src_iid and tgt_iid:
                        await raw.execute(
                            "INSERT INTO dependencies (source_issue_id, target_issue_id, origin, classification, provenance, created_at) "
                            "VALUES ($1, $2, 'reader', 'A', 'Reader-authored through the Dependency Builder', NOW())",
                            src_iid,
                            tgt_iid,
                        )
        finally:
            await raw.close()

        # Delete a dependency in the large library
        raw = await asyncpg.connect(url)
        try:
            large_dependency_id = await raw.fetchval(
                "SELECT id FROM dependencies "
                "WHERE source_issue_id = (SELECT id FROM issues WHERE thread_id = (SELECT id FROM threads WHERE user_id=$1 AND title='Source Series 100' LIMIT 1) ORDER BY position LIMIT 1) "
                "AND target_issue_id = (SELECT id FROM issues WHERE thread_id = (SELECT id FROM threads WHERE user_id=$1 AND title='Target Series 100' LIMIT 1) ORDER BY position LIMIT 1)",
                owner_id,
            )
        finally:
            await raw.close()

        env["RUST_ROLL_TEST_DEPENDENCY_ID"] = str(large_dependency_id)

        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        _, _, s_after2 = await db_counters(engine)
        large_delta = (
            (s_after2 - s_before2)
            if s_before2 is not None and s_after2 is not None
            else None
        )

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("DELETE", "/api/v2/dependencies/{dependency_id}", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()