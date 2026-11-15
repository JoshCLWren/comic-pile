"""Measured statement-count regression for continuity-plan recovery preview (#5146).

Runs the native Rust GET /api/v2/continuity-plans/{plan_id}/recovery for a
seeded reader and asserts the Postgres statement delta stays bounded, proving
the set-based queries do not grow with candidate/list data size.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User
from route_harness import assert_declared_budget, cargo_example_path, db_counters, run_rust_example

SECRET = "synthetic-native-continuity-recovery-n1-secret"
EXAMPLE = cargo_example_path("http_continuity_plans")
BINARY = str(EXAMPLE)
ROUTE = "/api/v2/continuity-plans/{plan_id}/recovery"


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


async def _seed_plan_with_lists(
    raw: asyncpg.Connection, owner_id: int, *, list_count: int, retained_count: int
) -> int:
    plan_id = await raw.fetchval(
        """
        INSERT INTO continuity_plans
            (user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
        VALUES ($1, $2, 'informational', '[]'::json, '[]'::json, NOW(), NOW())
        RETURNING id
        """,
        owner_id,
        f"Plan {uuid4().hex[:8]}",
    )

    thread_id = await raw.fetchval(
        """
        INSERT INTO threads (user_id, title, format, queue_position, issues_remaining, total_issues, status)
        VALUES ($1, $2, 'Comic', 1, $3, $3, 'active')
        RETURNING id
        """,
        owner_id,
        f"Thread {uuid4().hex[:6]}",
        retained_count,
    )

    for pos in range(retained_count):
        issue_id = await raw.fetchval(
            """
            INSERT INTO issues (thread_id, issue_number, position, status, created_at)
            VALUES ($1, $2, $3, 'unread', NOW())
            RETURNING id
            """,
            thread_id,
            str(pos + 1),
            pos + 1,
        )
        await raw.execute(
            """
            INSERT INTO reading_plan_issues
                (plan_id, occurrence_id, issue_id, lane_id, display_position, label, is_checkpoint)
            VALUES ($1, $2, $3, 'lane-1', $4, $5, false)
            """,
            plan_id,
            f"occ-{pos}",
            issue_id,
            pos,
            f"Retained {pos + 1}",
        )

    for i in range(list_count):
        list_id = await raw.fetchval(
            """
            INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
            VALUES ($1, $2, 'loose', NOW(), NOW())
            RETURNING id
            """,
            owner_id,
            f"List {i + 1}",
        )
        # add a couple entries so jsonb_agg has data in larger fixture
        for pos in range(min(retained_count, 2)):
            issue_number = (pos + 1)
            issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 AND position=$2",
                thread_id,
                issue_number,
            )
            if issue_id is not None:
                await raw.execute(
                    """
                    INSERT INTO custom_cbl_entries
                        (list_id, issue_id, position, gate, skipped, is_checkpoint,
                         checkpoint_target_issue_ids, created_at)
                    VALUES ($1, $2, $3, 'none', false, false, '[]'::jsonb, NOW())
                    """,
                    list_id,
                    issue_id,
                    pos,
                )
    return plan_id


@pytest.mark.asyncio
async def test_continuity_plan_recovery_statements_do_not_grow_with_candidate_data() -> None:
    """Statement delta must not grow from small to larger candidate/list fixture."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"cprn1_{uuid4().hex[:12]}"
        jti = f"jti-{uuid4().hex}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            owner_id = owner.id
            await db.commit()
            token = _token(username, jti=jti)

        raw = await asyncpg.connect(url)
        try:
            small_plan_id = await _seed_plan_with_lists(
                raw, owner_id, list_count=5, retained_count=5
            )
        finally:
            await raw.close()

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": f"/api/v2/continuity-plans/{small_plan_id}/recovery",
        }
        _, _, s_before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("plan_id") == small_plan_id
        assert small_body.get("plan_name")
        assert small_body.get("status") == "orphaned"
        assert small_body.get("linked_list_id") is None
        retained = small_body.get("retained_steps")
        assert isinstance(retained, list) and len(retained) == 5
        candidates = small_body.get("candidates")
        assert isinstance(candidates, list) and len(candidates) >= 5
        first = candidates[0]
        assert isinstance(first, dict)
        assert isinstance(first.get("steps"), list)
        assert "added_steps" in first and "removed_steps" in first
        _, _, s_after = await db_counters(engine)
        small_delta = s_after - s_before if s_before is not None and s_after is not None else None

        raw = await asyncpg.connect(url)
        try:
            large_plan_id = await _seed_plan_with_lists(
                raw, owner_id, list_count=200, retained_count=5
            )
        finally:
            await raw.close()

        env["RUST_ROLL_TEST_URI"] = f"/api/v2/continuity-plans/{large_plan_id}/recovery"
        _, _, s_before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("plan_id") == large_plan_id
        assert large_body.get("status") == "orphaned"
        large_candidates = large_body.get("candidates")
        assert isinstance(large_candidates, list) and len(large_candidates) >= 200
        _, _, s_after2 = await db_counters(engine)
        large_delta = s_after2 - s_before2 if s_before2 is not None and s_after2 is not None else None

        print(f"small_delta={small_delta} large_delta={large_delta}", flush=True)
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", ROUTE, small_delta, large_delta)
        assert large_delta <= small_delta, (
            f"statement count grew with candidate data size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()
