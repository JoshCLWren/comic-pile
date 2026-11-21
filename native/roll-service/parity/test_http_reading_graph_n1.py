"""Measured SQL budget regressions for native v2 reading-graph endpoints (#5149)."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

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


async def _counters(engine: AsyncEngine) -> tuple[int | None, int | None]:
    """Snapshot cumulative top-level and nested role statement counts.

    Nested counts require ``pg_stat_statements.track=all``; a ``track=top``
    database returns None so the measurement cannot silently pass.
    """
    _, _, statements = await db_counters(engine)
    nested = await db_nested_statements(engine)
    return statements, nested


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
        before, nested_before = await _counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert isinstance(small_body.get("affected_lists"), list)
        after, nested_after = await _counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        small_nested = (
            nested_after - nested_before
            if nested_before is not None and nested_after is not None
            else None
        )
        assert small_nested is not None, "pg_stat_statements.track=all is required for nested counts"

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        before2, nested_before2 = await _counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0
        after2, nested_after2 = await _counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        large_nested = (
            nested_after2 - nested_before2
            if nested_before2 is not None and nested_after2 is not None
            else None
        )
        assert large_nested is not None, "pg_stat_statements.track=all is required for nested counts"

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget(
            "GET", "/api/v2/reading-graph", small_delta, large_delta, small_nested, large_nested
        )
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
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
        before, nested_before = await _counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        assert small_body.get("removed") == "Reading List deleted"
        # The repair response projects the graph *after* the proposed repair,
        # even in preview mode (applied=False). The original cycle is reported
        # by status_before; the returned graph is already healed.
        graph = small_body.get("graph")
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert graph.get("cycles") == []
        assert graph.get("repairs") == []
        after, nested_after = await _counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        small_nested = (
            nested_after - nested_before
            if nested_before is not None and nested_after is not None
            else None
        )
        assert small_nested is not None, "pg_stat_statements.track=all is required for nested counts"

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        before2, nested_before2 = await _counters(engine)
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
        after2, nested_after2 = await _counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        large_nested = (
            nested_after2 - nested_before2
            if nested_before2 is not None and nested_after2 is not None
            else None
        )
        assert large_nested is not None, "pg_stat_statements.track=all is required for nested counts"

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget(
            "POST", "/api/v2/reading-graph/repairs", small_delta, large_delta, small_nested, large_nested
        )
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


async def _measured_with_injected_queries(
    engine: AsyncEngine,
    url: str,
    env: dict[str, str],
    injected: int,
) -> int:
    """Measure one route call plus ``injected`` deliberate top-level queries."""
    before, _ = await _counters(engine)
    if injected:
        raw = await asyncpg.connect(url)
        try:
            for _ in range(injected):
                await raw.execute("SELECT 1")
        finally:
            await raw.close()
    response, _, _, _ = await run_rust_example(BINARY, env)
    assert response.get("status") == 200, response
    after, _ = await _counters(engine)
    assert before is not None and after is not None, "pg_stat_statements is required"
    return after - before


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_extra_query_and_n1() -> None:
    """One injected extra query and a per-row query must fail the same budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1reject_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            thread = Thread(
                user_id=owner.id,
                title="Budget probe",
                format="Comic",
                queue_position=1,
                issues_remaining=2,
                total_issues=2,
                status="active",
            )
            db.add(thread)
            await db.flush()
            db.add_all(
                [
                    Issue(thread_id=thread.id, issue_number=str(p), position=p, status="unread")
                    for p in (1, 2)
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
        baseline = await _measured_with_injected_queries(engine, url, env, 0)
        with pytest.raises(AssertionError):
            assert_declared_budget(
                "GET",
                "/api/v2/reading-graph",
                await _measured_with_injected_queries(engine, url, env, 1),
            )
        n1 = await _measured_with_injected_queries(engine, url, env, 200)
        with pytest.raises(AssertionError):
            assert_declared_budget("GET", "/api/v2/reading-graph", n1)
        # The same +2 growth threshold used by the small-vs-large route test
        # must also reject an N+1-style per-row increase.
        with pytest.raises(AssertionError):
            assert n1 <= baseline + 2, f"per-row growth not detected: {baseline} -> {n1}"
    finally:
        await engine.dispose()
