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
from route_harness import (
    assert_declared_budget,
    cargo_example_path,
    db_counters,
    db_nested_statements,
    run_rust_example,
)

SECRET = "synthetic-native-reading-graph-n1-secret"
BINARY = str(cargo_example_path("http_reading_graph"))


async def _statement_counters(engine) -> tuple[int | None, int | None]:
    """Return (top-level, nested) statement counts for the isolated route role."""
    _, _, top = await db_counters(engine)
    nested = await db_nested_statements(engine)
    return top, nested


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
        before, nested_before = await _statement_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert isinstance(small_body.get("affected_lists"), list)
        after, nested_after = await _statement_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        nested_small_delta = (
            (nested_after - nested_before)
            if nested_before is not None and nested_after is not None
            else None
        )

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        before2, nested_before2 = await _statement_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0
        after2, nested_after2 = await _statement_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        nested_large_delta = (
            (nested_after2 - nested_before2)
            if nested_before2 is not None and nested_after2 is not None
            else None
        )

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        # Nested trigger/function statements are measured separately and must
        # stay flat and at zero for these read-only routes (track=all required).
        assert nested_small_delta is not None and nested_large_delta is not None, (
            "pg_stat_statements.track=all is required to measure nested statements"
        )
        assert nested_small_delta == 0 and nested_large_delta == 0, (
            f"nested statements appeared: {nested_small_delta} -> {nested_large_delta}"
        )
        assert_declared_budget("GET", "/api/v2/reading-graph", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_preview_statements_do_not_grow_with_library_size() -> None:
    """POST /api/v2/reading-graph/repairs preview must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrn1_{uuid4().hex[:12]}"
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

        body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": False})
        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "POST",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
            "RUST_ROLL_TEST_BODY": body,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        before, nested_before = await _statement_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        graph = small_body.get("graph")
        # The handler returns the graph after the proposed repair is applied in
        # memory (reading_graph.rs:686-697), so a successful preview shows the
        # acyclic result even though `applied` is false and nothing persisted.
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert graph.get("cycles") == []
        assert graph.get("repairs") == []
        after, nested_after = await _statement_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        nested_small_delta = (
            (nested_after - nested_before)
            if nested_before is not None and nested_after is not None
            else None
        )

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        before2, nested_before2 = await _statement_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is False
        assert large_body.get("status_before") == "cycle"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"
        assert large_graph.get("cycles") == []
        assert large_graph.get("repairs") == []
        after2, nested_after2 = await _statement_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        nested_large_delta = (
            (nested_after2 - nested_before2)
            if nested_before2 is not None and nested_after2 is not None
            else None
        )

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert nested_small_delta is not None and nested_large_delta is not None, (
            "pg_stat_statements.track=all is required to measure nested statements"
        )
        assert nested_small_delta == 0 and nested_large_delta == 0, (
            f"nested statements appeared: {nested_small_delta} -> {nested_large_delta}"
        )
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_extra_and_per_row_queries() -> None:
    """Prove the checks used above reject an extra query and an N+1 pattern."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        method, path = "GET", "/api/v2/reading-graph"

        # Extra query: inject statements under the isolated route role and show
        # the same assert_declared_budget used by the route test rejects the
        # over-budget measurement.
        _, _, before = await db_counters(engine)
        assert before is not None, "pg_stat_statements is required"
        connection = await asyncpg.connect(url)
        try:
            for _ in range(20):
                await connection.execute("SELECT 1")
        finally:
            await connection.close()
        _, _, after = await db_counters(engine)
        assert after is not None
        extra_delta = after - before
        assert extra_delta >= 20, f"injected queries not measured: {extra_delta}"
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget(method, path, extra_delta)

        # N+1 (per-row) queries: a small and a large row set yield growing
        # counts, so the small-vs-large growth invariant used by the route test
        # must reject the large measurement.
        async def _per_row_queries(count: int) -> int:
            _, _, start = await db_counters(engine)
            connection = await asyncpg.connect(url)
            try:
                for _ in range(count):
                    await connection.fetchval("SELECT 1")
            finally:
                await connection.close()
            _, _, end = await db_counters(engine)
            assert start is not None and end is not None
            return end - start

        small_n1 = await _per_row_queries(5)
        large_n1 = await _per_row_queries(200)
        assert large_n1 > small_n1 + 2, f"expected N+1 growth, got {small_n1} -> {large_n1}"
        with pytest.raises(AssertionError, match="statement count grew"):
            assert large_n1 <= small_n1 + 2, f"statement count grew: {small_n1} -> {large_n1}"
    finally:
        await engine.dispose()
