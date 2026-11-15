"""Measured N+1 regression for ``GET /api/v2/issues/{issue_id}/comicvine`` (#5148).

Seeds a small (5) and a large (200) library for the same reader, reads comicvine
intelligence for an issue in each, and asserts the Postgres statement delta
does not grow with library size.
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

SECRET = "synthetic-native-comicvine-issue-secret"
EXAMPLE = cargo_example_path("http_comicvine_issue")
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_comicvine_issue_statements_do_not_grow_with_library_size() -> None:
    """Statement delta must not grow from 5 to 200 issues."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"ci_{uuid4().hex[:12]}"
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
            for i in range(5):
                db.add(
                    Issue(
                        thread_id=thread.id,
                        issue_number=str(i + 1),
                        position=i + 1,
                        status="unread",
                    )
                )
            await db.commit()

        raw = await asyncpg.connect(url)
        try:
            issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position LIMIT 1",
                thread.id,
            )
            await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            # Create a confirmed comicvine mapping for the issue
            ext_id = await raw.fetchval(
                "INSERT INTO external_identities (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) "
                "VALUES ('comicvine', 'issue', '12345', 'https://comicvine.gamespot.com/issue/12345', '{}', NOW(), NOW()) "
                "RETURNING id",
            )
            await raw.execute(
                "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, confidence, created_at, updated_at) "
                "VALUES ($1, $2, 'confirmed', 1.0, NOW(), NOW())",
                issue_id,
                ext_id,
            )
        finally:
            await raw.close()

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-comicvine-issue-fixture",
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
        }
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        intelligence = small_body.get("intelligence")
        assert intelligence is not None, "expected comicvine intelligence object"
        _, _, s_after = await db_counters(engine)
        small_delta = (
            (s_after - s_before) if s_before is not None and s_after is not None else None
        )

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

        # Read comicvine intelligence for a different issue in the large set
        raw = await asyncpg.connect(url)
        try:
            new_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position OFFSET 10 LIMIT 1",
                thread.id,
            )
            # Create a confirmed comicvine mapping for the new issue
            ext_id = await raw.fetchval(
                "INSERT INTO external_identities (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) "
                "VALUES ('comicvine', 'issue', '67890', 'https://comicvine.gamespot.com/issue/67890', '{}', NOW(), NOW()) "
                "RETURNING id",
            )
            await raw.execute(
                "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, confidence, created_at, updated_at) "
                "VALUES ($1, $2, 'confirmed', 1.0, NOW(), NOW())",
                new_issue_id,
                ext_id,
            )
        finally:
            await raw.close()

        env["RUST_ROLL_TEST_ISSUE_ID"] = str(new_issue_id)

        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        intelligence = large_body.get("intelligence")
        assert intelligence is not None, "expected comicvine intelligence object"
        _, _, s_after2 = await db_counters(engine)
        large_delta = (
            (s_after2 - s_before2)
            if s_before2 is not None and s_after2 is not None
            else None
        )

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", "/api/v2/issues/{issue_id}/comicvine", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()