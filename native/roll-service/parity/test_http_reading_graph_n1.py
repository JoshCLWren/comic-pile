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


def _assert_nested_clean(nested_before: int | None, nested_after: int | None, label: str) -> None:
    """Require nested statements to be measured separately and stay absent.

    ``db_nested_statements`` returns ``None`` unless ``pg_stat_statements.track``
    is ``all``, so this also rejects a ``track=top`` measurement setup. The
    reading-graph projection uses only top-level statements; no trigger or
    function issues nested SQL on these routes.
    """
    assert nested_before is not None and nested_after is not None, (
        "pg_stat_statements.track=all is required to measure nested statements"
    )
    assert nested_after - nested_before == 0, (
        f"{label} recorded nested statements: {nested_before} -> {nested_after}"
    )


async def _seed_cycle(
    raw: asyncpg.Connection, owner_id: int, issue_ids: list[int], name: str
) -> int:
    """Persist a two-issue strict-list cycle for repair fixtures."""
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'strict',NOW(),NOW()) RETURNING id",
        owner_id,
        name,
    )
    issue_a, issue_b = issue_ids[0], issue_ids[1]
    await raw.execute(
        "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
        "VALUES ($1,$2,1,NOW(),false,'[]','none',false), ($1,$3,2,NOW(),false,'[]','none',false)",
        list_id,
        issue_b,
        issue_a,
    )
    await raw.execute(
        "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
        "VALUES ($1,$2,'reader','A',NOW())",
        issue_a,
        issue_b,
    )
    return list_id


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

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        _assert_nested_clean(nested_before, nested_after, "graph small")
        _assert_nested_clean(nested_before2, nested_after2, "graph large")
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
        _, _, before = await db_counters(engine)
        nested_before = await db_nested_statements(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        assert small_body.get("removed") == "Reading List deleted"
        # Both repair modes return the post-repair graph, even for a preview.
        graph = small_body.get("graph")
        assert isinstance(graph, dict)
        assert graph.get("status") == "ok"
        assert graph.get("cycles") == []
        assert graph.get("repairs") == []
        _, _, after = await db_counters(engine)
        nested_after = await db_nested_statements(engine)
        small_delta = (after - before) if before is not None and after is not None else None

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
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"
        assert large_body.get("status_after") == "ok"
        _, _, after2 = await db_counters(engine)
        nested_after2 = await db_nested_statements(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        _assert_nested_clean(nested_before, nested_after, "repairs preview small")
        _assert_nested_clean(nested_before2, nested_after2, "repairs preview large")
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()


async def _seed_user_with_cycle(url: str, thread_count: int, name: str) -> tuple[str, int]:
    """Create an isolated owner, ``thread_count`` threads and one repairable cycle."""
    username = f"rgrc1_{uuid4().hex[:12]}"
    raw = await asyncpg.connect(url)
    try:
        owner_id = await raw.fetchval(
            "INSERT INTO users (username) VALUES ($1) RETURNING id", username
        )
        issue_ids: list[int] = []
        for index in range(thread_count):
            _, ids = await _insert_owned_thread(raw, owner_id, index)
            issue_ids.append(ids[0])
        list_id = await _seed_cycle(raw, owner_id, issue_ids, name)
    finally:
        await raw.close()
    return username, list_id


@pytest.mark.asyncio
async def test_reading_graph_repairs_confirmed_statements_within_budget() -> None:
    """Confirmed repairs are measured on both fixture sizes with persisted results."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        deltas: list[int] = []
        for label, thread_count in (("small", 5), ("large", 200)):
            username, list_id = await _seed_user_with_cycle(url, thread_count, f"Cycle-{label}")
            body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": True})
            env = {
                **os.environ,
                "RUST_ROLL_TEST_TOKEN": _token(username, jti=f"jti-{uuid4().hex}"),
                "RUST_ROLL_TEST_METHOD": "POST",
                "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
                "RUST_ROLL_TEST_BODY": body,
                "RUST_ROLL_DATABASE_URL": url,
                "RUST_ROLL_JWT_SECRET": SECRET,
            }
            _, _, before = await db_counters(engine)
            nested_before = await db_nested_statements(engine)
            response, _, _, _ = await run_rust_example(BINARY, env)
            _, _, after = await db_counters(engine)
            nested_after = await db_nested_statements(engine)
            assert response.get("status") == 200, response
            result = response.get("body")
            assert isinstance(result, dict)
            assert result.get("applied") is True
            assert result.get("status_before") == "cycle"
            assert result.get("status_after") == "ok"
            graph = result.get("graph")
            assert isinstance(graph, dict) and graph.get("status") == "ok"

            raw = await asyncpg.connect(url)
            try:
                owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
                list_exists = await raw.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM custom_cbl_lists WHERE id=$1 AND user_id=$2)",
                    list_id,
                    owner_id,
                )
                entry_exists = await raw.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM custom_cbl_entries WHERE list_id=$1)",
                    list_id,
                )
            finally:
                await raw.close()
            assert list_exists is False, f"{label}: repaired list still persisted"
            assert entry_exists is False, f"{label}: repaired list entries still persisted"

            assert before is not None and after is not None, "pg_stat_statements is required"
            _assert_nested_clean(nested_before, nested_after, f"repairs confirmed {label}")
            delta = after - before
            assert_declared_budget("POST", "/api/v2/reading-graph/repairs", delta)
            deltas.append(delta)
        assert deltas[1] <= deltas[0] + 2, f"confirmed repair count grew: {deltas}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_extra_and_per_row_queries() -> None:
    """Injected extra and per-row queries must fail the route's own budget checks."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrj1_{uuid4().hex[:12]}"
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval(
                "INSERT INTO users (username) VALUES ($1) RETURNING id", username
            )
            for index in range(5):
                await _insert_owned_thread(raw, owner_id, index)
        finally:
            await raw.close()
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
        baseline_response, _, _, _ = await run_rust_example(BINARY, env)
        _, _, after = await db_counters(engine)
        assert baseline_response.get("status") == 200
        assert before is not None and after is not None
        baseline = after - before
        assert_declared_budget("GET", "/api/v2/reading-graph", baseline)

        extra_env = {**env, "RUST_ROLL_TEST_EXTRA_STATEMENTS": "1"}
        _, _, extra_before = await db_counters(engine)
        extra_response, _, _, _ = await run_rust_example(BINARY, extra_env)
        _, _, extra_after = await db_counters(engine)
        assert extra_response.get("status") == 200
        assert extra_before is not None and extra_after is not None
        one_extra = extra_after - extra_before
        assert one_extra == baseline + 1, f"injection did not add one query: {baseline} -> {one_extra}"
        with pytest.raises(AssertionError):
            assert_declared_budget("GET", "/api/v2/reading-graph", one_extra)

        raw = await asyncpg.connect(url)
        try:
            for index in range(5, 200):
                await _insert_owned_thread(raw, owner_id, index)
        finally:
            await raw.close()
        _, _, large_before = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        _, _, large_after = await db_counters(engine)
        assert large_response.get("status") == 200
        assert large_before is not None and large_after is not None
        large = large_after - large_before
        assert large == baseline, f"real route grew with data: {baseline} -> {large}"

        n1_env = {**env, "RUST_ROLL_TEST_EXTRA_STATEMENTS": "200"}
        _, _, n1_before = await db_counters(engine)
        n1_response, _, _, _ = await run_rust_example(BINARY, n1_env)
        _, _, n1_after = await db_counters(engine)
        assert n1_response.get("status") == 200
        assert n1_before is not None and n1_after is not None
        per_row = n1_after - n1_before
        assert per_row == large + 200, f"per-row injection failed: {large} -> {per_row}"
        with pytest.raises(AssertionError):
            assert per_row <= baseline + 2
    finally:
        await engine.dispose()
