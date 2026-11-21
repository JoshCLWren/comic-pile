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
        small_nested = (nested_after - nested_before) if nested_before is not None and nested_after is not None else None

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
        large_nested = (nested_after2 - nested_before2) if nested_before2 is not None and nested_after2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert small_nested is not None and large_nested is not None, "pg_stat_statements.track=all is required for nested statements"
        assert_declared_budget("GET", "/api/v2/reading-graph", small_delta, large_delta, small_nested, large_nested)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_nested <= small_nested + 2, f"nested statement count grew: {small_nested} -> {large_nested}"
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
        _, _, before = await db_counters(engine)
        nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        graph = small_body.get("graph")
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert graph.get("cycles") == []
        _, _, after = await db_counters(engine)
        nested_after = await db_nested_statements(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        small_nested = (nested_after - nested_before) if nested_before is not None and nested_after is not None else None

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
        assert large_body.get("applied") is False
        assert large_body.get("status_before") == "cycle"
        assert large_body.get("status_after") == "ok"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"
        assert large_graph.get("cycles") == []
        _, _, after2 = await db_counters(engine)
        nested_after2 = await db_nested_statements(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        large_nested = (nested_after2 - nested_before2) if nested_before2 is not None and nested_after2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert small_nested is not None and large_nested is not None, "pg_stat_statements.track=all is required for nested statements"
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta, small_nested, large_nested)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_nested <= small_nested + 2, f"nested statement count grew: {small_nested} -> {large_nested}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_extra_query_fails_budget() -> None:
    """A deliberately added extra query must fail the declared budget check."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgx_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            db.add(User(username=username))
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
        response, _, _, _ = await run_rust_example(BINARY, env)
        assert response.get("status") == 200, response
        _, _, after = await db_counters(engine)
        nested_after = await db_nested_statements(engine)
        delta = (after - before) if before is not None and after is not None else None
        nested = (nested_after - nested_before) if nested_before is not None and nested_after is not None else None
        assert delta is not None and nested is not None
        # Deliberately add extra service-role queries until the declared budget is exceeded.
        budget_doc = json.loads((__import__("pathlib").Path(__file__).resolve().parents[3] / "docs/api/sql-budget-sources.json").read_text())
        max_stmts = next(e["sql_budget"]["max_statements"] for e in budget_doc["operations"] if e["method"]=="GET" and e["path"]=="/api/v2/reading-graph")
        raw = await asyncpg.connect(url)
        try:
            for _ in range(max(1, max_stmts - delta + 1)):
                await raw.execute("SELECT 1")
        finally:
            await raw.close()
        _, _, after_extra = await db_counters(engine)
        delta_extra = (after_extra - before) if before is not None and after_extra is not None else None
        assert delta_extra is not None
        with pytest.raises(AssertionError):
            assert_declared_budget("GET", "/api/v2/reading-graph", delta_extra, delta_extra, nested, nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_n1_query_fails_growth_check() -> None:
    """A deliberately introduced per-row N+1 query pattern must fail the growth check."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1x_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                t = Thread(user_id=owner.id, title=f"S{i}", format="Comic", queue_position=i+1, issues_remaining=1, total_issues=1, status="active")
                db.add(t)
                await db.flush()
                db.add(Issue(thread_id=t.id, issue_number="1", position=1, status="unread"))
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
        response, _, _, _ = await run_rust_example(BINARY, env)
        assert response.get("status") == 200
        _, _, after = await db_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        _, _, before2 = await db_counters(engine)
        response2, _, _, _ = await run_rust_example(BINARY, env)
        assert response2.get("status") == 200
        # Deliberately introduce an N+1 pattern: one query per added row.
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            ids = await raw.fetch("SELECT id FROM threads WHERE user_id=$1 ORDER BY id LIMIT 50", owner_id)
            for row in ids:
                await raw.fetchval("SELECT id FROM threads WHERE id=$1", row["id"])
        finally:
            await raw.close()
        _, _, after2 = await db_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        assert small_delta is not None and large_delta is not None
        # The N+1 loop makes the count grow with data; the route growth check must reject it.
        with pytest.raises(AssertionError):
            assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_confirmed_statements_respect_budget() -> None:
    """POST /api/v2/reading-graph/repairs with confirm=true must stay within budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrc_{uuid4().hex[:12]}"
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

        async def _make_cycle() -> int:
            raw = await asyncpg.connect(url)
            try:
                owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
                issue_ids = [r["id"] for r in await raw.fetch(
                    "SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id", owner_id)]
                cid = await raw.fetchval(
                    "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
                    "VALUES ($1,'Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
                    owner_id,
                )
                a, b = issue_ids[0], issue_ids[1]
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,1,NOW(),false,'[]','none',false), ($1,$3,2,NOW(),false,'[]','none',false)",
                    cid, b, a,
                )
                await raw.execute(
                    "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
                    "VALUES ($1,$2,'reader','A',NOW())",
                    a, b,
                )
                return cid
            finally:
                await raw.close()

        list_id = await _make_cycle()
        body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": True})
        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "POST",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
            "RUST_ROLL_TEST_BODY": body,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, before = await db_counters(engine)
        nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is True
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        graph = small_body.get("graph")
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert graph.get("cycles") == []
        # Persisted: list gone.
        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval("SELECT id FROM custom_cbl_lists WHERE id=$1", list_id) is None
        finally:
            await raw.close()
        _, _, after = await db_counters(engine)
        nested_after = await db_nested_statements(engine)
        small_delta = (after - before) if before is not None and after is not None else None
        small_nested = (nested_after - nested_before) if nested_before is not None and nested_after is not None else None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        list_id2 = await _make_cycle()
        body2 = json.dumps({"action": "delete_list", "list_id": list_id2, "confirm": True})
        env["RUST_ROLL_TEST_BODY"] = body2
        _, _, before2 = await db_counters(engine)
        nested_before2 = await db_nested_statements(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is True
        assert large_body.get("status_after") == "ok"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"
        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval("SELECT id FROM custom_cbl_lists WHERE id=$1", list_id2) is None
        finally:
            await raw.close()
        _, _, after2 = await db_counters(engine)
        nested_after2 = await db_nested_statements(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None
        large_nested = (nested_after2 - nested_before2) if nested_before2 is not None and nested_after2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert small_nested is not None and large_nested is not None, "pg_stat_statements.track=all is required for nested statements"
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta, small_nested, large_nested)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_nested <= small_nested + 2, f"nested statement count grew: {small_nested} -> {large_nested}"
    finally:
        await engine.dispose()
