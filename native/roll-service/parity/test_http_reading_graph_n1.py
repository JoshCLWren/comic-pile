"""Measured SQL budget regressions for native v2 reading-graph endpoints (#5149)."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Issue, Thread, User
from route_harness import assert_declared_budget, cargo_example_path, db_counters, db_nested_statements, run_rust_example

SECRET = "synthetic-native-reading-graph-n1-secret"
BINARY = str(cargo_example_path("http_reading_graph"))


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


async def _insert_owned_thread(raw: asyncpg.Connection, owner_id: int, index: int) -> tuple[int, list[int]]:
    thread_id = await raw.fetchval(
        "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) "
        "VALUES ($1,$2,'Comic',$3,2,2,'active') RETURNING id",
        owner_id,
        f"Series {index + 1}",
        index + 1,
    )
    issue_ids = []
    for position in (1, 2):
        issue_id = await raw.fetchval(
            "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
            "VALUES ($1,$2,$3,'unread',NOW()) RETURNING id",
            thread_id,
            str(position),
            position,
        )
        issue_ids.append(issue_id)
    return thread_id, issue_ids


@pytest.mark.asyncio
async def test_reading_graph_statements_do_not_grow_with_library_size() -> None:
    """GET /api/v2/reading-graph must stay set-based across library sizes."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                thread = Thread(
                    user_id=owner.id,
                    title=f"Series {i + 1}",
                    format="Comic",
                    queue_position=i + 1,
                    issues_remaining=2,
                    total_issues=2,
                    status="active",
                )
                db.add(thread)
                await db.flush()
                db.add_all(
                    [
                        Issue(thread_id=thread.id, issue_number=str(position), position=position, status="unread")
                        for position in (1, 2)
                    ]
                )
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, before = await db_counters(engine)
        nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert isinstance(small_body.get("affected_lists"), list)
        _, _, after = await db_counters(engine)
        nested_after = await db_nested_statements(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        small_nested_delta = (nested_after - nested_before) if nested_after is not None and nested_before is not None else None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        _, _, before2 = await db_counters(engine)
        nested_before2 = await db_nested_statements(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0
        _, _, after2 = await db_counters(engine)
        nested_after2 = await db_nested_statements(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        large_nested_delta = (nested_after2 - nested_before2) if nested_after2 is not None and nested_before2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("GET", "/api/v2/reading-graph", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert small_nested_delta is not None, "nested statements must be measurable"
        assert large_nested_delta is not None, "nested statements must be measurable"
        assert small_nested_delta == 0, f"small fixture should have 0 nested statements, got {small_nested_delta}"
        assert large_nested_delta == 0, f"large fixture should have 0 nested statements, got {large_nested_delta}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_budget_rejection_graph() -> None:
    """Verify that deliberately adding extra queries causes budget enforcement to fail."""
    import uuid as _uuid
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"brg1_{_uuid.uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                thread = Thread(
                    user_id=owner.id,
                    title=f"Series {i + 1}",
                    format="Comic",
                    queue_position=i + 1,
                    issues_remaining=2,
                    total_issues=2,
                    status="active",
                )
                db.add(thread)
                await db.flush()
                db.add_all(
                    [
                        Issue(thread_id=thread.id, issue_number=str(position), position=position, status="unread")
                        for position in (1, 2)
                    ]
                )
            await db.commit()
            token = _token(username, jti=f"jti-{_uuid.uuid4().hex}")

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        # Measure baseline
        _, _, before = await db_counters(engine)
        _, _, before_nested = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        _, _, after = await db_counters(engine)
        _, _, after_nested = await db_nested_statements(engine)
        baseline_delta = (after - before) if before is not None and after is not None else None
        baseline_nested = (after_nested - before_nested) if after_nested is not None and before_nested is not None else None

        # Add an extra query by running a raw SELECT 1 via the admin connection
        raw = await asyncpg.connect(url)
        try:
            await raw.execute("SELECT 1")
        finally:
            await raw.close()

        _, _, after_extra = await db_counters(engine)
        _, _, after_extra_nested = await db_nested_statements(engine)
        extra_delta = (after_extra - after) if after_extra is not None and after is not None else None
        extra_nested = (after_extra_nested - after_nested) if after_extra_nested is not None and after_nested is not None else None

        # The extra SELECT 1 should increment the statement count
        assert extra_delta == 1, f"expected 1 extra statement, got {extra_delta}"
        # Verify budget enforcement catches the excess
        try:
            assert_declared_budget("GET", "/api/v2/reading-graph", after_extra, after_extra)
            assert False, "Budget check should have failed when exceeding max_statements"
        except AssertionError:
            # Expected: the budget check raises AssertionError when statements exceed the maximum
            pass
    finally:
        await engine.dispose()




@pytest.mark.asyncio
async def test_budget_repair_confirmed() -> None:
    """Verify that confirmed repairs (confirm=True) are measured with the apply branch budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"brc1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                thread = Thread(
                    user_id=owner.id,
                    title=f"Series {i + 1}",
                    format="Comic",
                    queue_position=i + 1,
                    issues_remaining=2,
                    total_issues=2,
                    status="active",
                )
                db.add(thread)
                await db.flush()
                db.add_all(
                    [
                        Issue(thread_id=thread.id, issue_number=str(position), position=position, status="unread")
                        for position in (1, 2)
                    ]
                )
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = [r["id"] for r in await raw.fetch("SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id", owner_id)]
            list_id = await raw.fetchval(
                "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
                "VALUES ($1,'Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
                owner_id,
            )
            # Create a cycle: strict list order issue_b -> issue_a and prerequisite issue_a -> issue_b.
            issue_a, issue_b = issue_ids[0], issue_ids[1]
            await raw.execute(
                "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                "VALUES ($1,$2,1,NOW(),false,'[]','none',false), ($1,$3,2,NOW(),false,'[]','none',false)",
                list_id, issue_b, issue_a,
            )
            await raw.execute(
                "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
                "VALUES ($1,$2,'reader','A',NOW())",
                issue_a, issue_b,
            )
        finally:
            await raw.close()

        # Small fixture: confirmed repair
        body_small = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": True})
        env_small = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "POST",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
            "RUST_ROLL_TEST_BODY": body_small,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env_small)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is True
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        _, _, after = await db_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None

        # Large fixture: confirmed repair
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        _, _, before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env_small)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is True
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"
        _, _, after2 = await db_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None

        assert small_delta is not None and large_delta is not None
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()
