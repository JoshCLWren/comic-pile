"""Measured SQL budget regressions for native v2 reading-graph endpoints (#5149).

Each case runs one real authenticated request through the native Rust router
against the canonical Alembic schema and reads ``pg_stat_statements`` with
``track=all`` for the isolated ``roll_test_dml`` role. Top-level and nested
(trigger/function) statements are measured separately, small and large fixtures
prove the declared ``max_statements`` and ``grows_with_data`` contract, and
injected extra/N+1 statements prove the budget guard rejects regressions.
"""

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
GROWTH_TOLERANCE = 2
N_PLUS_ONE_STATEMENTS = 200


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


async def _statement_tracking() -> str:
    """Return the cluster-wide ``pg_stat_statements`` tracking mode."""
    connection = await asyncpg.connect(os.environ["RUST_ROLL_TEST_DATABASE_URL"])
    try:
        tracking = await connection.fetchval("SHOW pg_stat_statements.track")
    finally:
        await connection.close()
    assert isinstance(tracking, str)
    return tracking


async def _counters(engine) -> tuple[int, int]:
    """Return cumulative top-level and nested statement counts for the route role."""
    _, _, statements = await db_counters(engine)
    nested = await db_nested_statements(engine)
    assert statements is not None, "pg_stat_statements must measure this route"
    assert nested is not None, "pg_stat_statements must track nested statements (track=all)"
    return statements, nested


async def _measure(engine, env: dict[str, str]) -> tuple[dict[str, object], int, int]:
    """Run one route invocation and return its body, top-level delta, nested delta."""
    assert await _statement_tracking() == "all", "pg_stat_statements.track must be 'all'"
    statements_before, nested_before = await _counters(engine)
    response, _, _, _ = await run_rust_example(BINARY, env)
    statements_after, nested_after = await _counters(engine)
    return response, statements_after - statements_before, nested_after - nested_before


async def _injected_statements(engine, count: int) -> int:
    """Run ``count`` service-role statements and return their measured count."""
    _, _, before = await db_counters(engine)
    connection = await asyncpg.connect(os.environ["RUST_ROLL_PARITY_DATABASE_URL"])
    try:
        for _ in range(count):
            await connection.execute("SELECT 1")
    finally:
        await connection.close()
    _, _, after = await db_counters(engine)
    assert before is not None and after is not None, "pg_stat_statements must be enabled"
    return after - before


def _assert_budget_and_no_growth(operation: tuple[str, str], small: int, large: int) -> None:
    """Enforce the declared maximum and the ``grows_with_data: false`` contract."""
    assert_declared_budget(operation[0], operation[1], small, large)
    assert large <= small + GROWTH_TOLERANCE, (
        f"{operation[0]} {operation[1]} statements grew with data: {small} -> {large}"
    )


def _assert_no_nested_growth(operation: tuple[str, str], small: int, large: int) -> None:
    """These routes issue no trigger or function SQL for either fixture size."""
    assert small == 0 and large == 0, (
        f"{operation[0]} {operation[1]} nested statements: {small} -> {large}"
    )


async def _insert_owned_thread(
    raw: asyncpg.Connection, owner_id: int, index: int
) -> tuple[int, list[int]]:
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


async def _insert_cycle(
    raw: asyncpg.Connection, owner_id: int, name: str, first_thread_index: int
) -> int:
    """Insert a strict two-entry list whose order cycles with a prerequisite edge."""
    _, issues_a = await _insert_owned_thread(raw, owner_id, first_thread_index)
    _, issues_b = await _insert_owned_thread(raw, owner_id, first_thread_index + 1)
    issue_a, issue_b = issues_a[0], issues_b[0]
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'strict',NOW(),NOW()) RETURNING id",
        owner_id,
        name,
    )
    # Strict list order issue_b -> issue_a while prerequisite issue_a -> issue_b.
    await raw.execute(
        "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,"
        "checkpoint_target_issue_ids,gate,skipped) "
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


def _run_env(token: str, method: str, uri: str, *, body: str | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "RUST_ROLL_TEST_TOKEN": token,
        "RUST_ROLL_TEST_METHOD": method,
        "RUST_ROLL_TEST_URI": uri,
        "RUST_ROLL_DATABASE_URL": os.environ["RUST_ROLL_PARITY_DATABASE_URL"],
        "RUST_ROLL_JWT_SECRET": SECRET,
    }
    if body is not None:
        env["RUST_ROLL_TEST_BODY"] = body
    return env


@pytest.mark.asyncio
async def test_reading_graph_statements_do_not_grow_with_library_size() -> None:
    """GET /api/v2/reading-graph must stay set-based across library sizes."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("GET", "/api/v2/reading-graph")
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
                        Issue(
                            thread_id=thread.id,
                            issue_number=str(position),
                            position=position,
                            status="unread",
                        )
                        for position in (1, 2)
                    ]
                )
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = _run_env(token, "GET", "/api/v2/reading-graph")
        small_response, small_delta, small_nested = await _measure(engine, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert small_body.get("cyclic_issue_ids") == []
        assert isinstance(small_body.get("affected_lists"), list)
        assert small_body.get("affected_threads") == []

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measure(engine, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_preview_statements_do_not_grow_with_library_size() -> None:
    """POST /api/v2/reading-graph/repairs preview must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("POST", "/api/v2/reading-graph/repairs")
    try:
        username = f"rgrn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5):
                await _insert_owned_thread(raw, owner_id, i)
            list_id = await _insert_cycle(raw, owner_id, "Preview cycle", 5)
        finally:
            await raw.close()

        body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": False})
        env = _run_env(token, "POST", "/api/v2/reading-graph/repairs", body=body)
        small_response, small_delta, small_nested = await _measure(engine, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        assert small_body.get("removed") == "Reading List deleted"
        # The preview projects the repaired graph without persisting the repair.
        preview_graph = small_body.get("graph")
        assert isinstance(preview_graph, dict)
        assert preview_graph.get("status") == "ok"
        assert preview_graph.get("cycles") == []
        assert preview_graph.get("repairs") == []

        raw = await asyncpg.connect(url)
        try:
            persisted = await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", list_id
            )
            assert persisted == 1, "a preview repair must not delete the reading list"
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measure(engine, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is False
        assert large_body.get("status_before") == "cycle"
        assert large_body.get("status_after") == "ok"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict)
        assert large_graph.get("status") == "ok"
        assert large_graph.get("cycles") == []

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_confirm_statements_do_not_grow_with_library_size() -> None:
    """POST /api/v2/reading-graph/repairs confirm must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("POST", "/api/v2/reading-graph/repairs")
    try:
        username = f"rgcn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5):
                await _insert_owned_thread(raw, owner_id, i)
            small_list = await _insert_cycle(raw, owner_id, "Confirm small", 5)
        finally:
            await raw.close()

        small_body = json.dumps(
            {"action": "delete_list", "list_id": small_list, "confirm": True}
        )
        env = _run_env(token, "POST", "/api/v2/reading-graph/repairs", body=small_body)
        small_response, small_delta, small_nested = await _measure(engine, env)
        assert small_response.get("status") == 200, small_response
        small_result = small_response.get("body")
        assert isinstance(small_result, dict)
        assert small_result.get("applied") is True
        assert small_result.get("status_before") == "cycle"
        assert small_result.get("status_after") == "ok"
        assert small_result.get("removed") == "Reading List deleted"
        confirmed_graph = small_result.get("graph")
        assert isinstance(confirmed_graph, dict) and confirmed_graph.get("status") == "ok"

        raw = await asyncpg.connect(url)
        try:
            assert (
                await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", small_list)
                == 0
            )
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", small_list
                )
                == 0
            )
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
            large_list = await _insert_cycle(raw, owner_id, "Confirm large", 200)
        finally:
            await raw.close()

        large_body = json.dumps(
            {"action": "delete_list", "list_id": large_list, "confirm": True}
        )
        large_env = _run_env(token, "POST", "/api/v2/reading-graph/repairs", body=large_body)
        large_response, large_delta, large_nested = await _measure(engine, large_env)
        assert large_response.get("status") == 200, large_response
        large_result = large_response.get("body")
        assert isinstance(large_result, dict)
        assert large_result.get("applied") is True
        assert large_result.get("status_before") == "cycle"
        assert large_result.get("status_after") == "ok"

        raw = await asyncpg.connect(url)
        try:
            assert (
                await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", large_list)
                == 0
            )
        finally:
            await raw.close()

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_injected_extra_query_and_n_plus_1_fail_reading_graph_budget() -> None:
    """An added query and an N+1 loop must fail the reading-graph budget guard."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("GET", "/api/v2/reading-graph")
    try:
        username = f"rgxn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-graph")
        response, measured, _ = await _measure(engine, env)
        assert response.get("status") == 200, response
        assert_declared_budget(operation[0], operation[1], measured)

        extra = await _injected_statements(engine, 1)
        assert extra == 1, f"injected query measured as {extra} statements"
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget(operation[0], operation[1], measured + extra)

        n_plus_1 = await _injected_statements(engine, N_PLUS_ONE_STATEMENTS)
        assert n_plus_1 == N_PLUS_ONE_STATEMENTS, f"N+1 loop measured as {n_plus_1} statements"
        with pytest.raises(AssertionError, match="declared maximum"):
            _assert_budget_and_no_growth(operation, measured, measured + n_plus_1)
        assert measured + n_plus_1 > measured + GROWTH_TOLERANCE
    finally:
        await engine.dispose()
