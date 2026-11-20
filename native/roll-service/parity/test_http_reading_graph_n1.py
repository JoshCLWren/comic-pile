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
from reading_budget_harness import (
    assert_fixed_budget,
    assert_fixed_statement_count,
    measure_reading_route,
)
from route_harness import assert_declared_budget, cargo_example_path

SECRET = "synthetic-native-reading-graph-n1-secret"
BINARY = str(cargo_example_path("http_reading_graph"))
GRAPH_ROUTE = "GET /api/v2/reading-graph"
REPAIR_ROUTE = "POST /api/v2/reading-graph/repairs"


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


async def _seed_owner(engine: AsyncEngine, username: str, count: int) -> str:
    """Create an owner and two unread issues per thread."""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        owner = User(username=username)
        db.add(owner)
        await db.flush()
        for index in range(count):
            thread = Thread(
                user_id=owner.id,
                title=f"Series {index + 1}",
                format="Comic",
                queue_position=index + 1,
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
    return _token(username, jti=f"jti-{uuid4().hex}")


async def _insert_owned_thread(
    raw: asyncpg.Connection,
    owner_id: int,
    index: int,
) -> tuple[int, list[int]]:
    """Grow the canonical fixture without including seed SQL in route counters."""
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


async def _insert_cycle_list(
    raw: asyncpg.Connection,
    owner_id: int,
    name: str,
    issue_a: int,
    issue_b: int,
) -> int:
    """Create strict order opposite to an existing prerequisite."""
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'strict',NOW(),NOW()) RETURNING id",
        owner_id,
        name,
    )
    await raw.execute(
        "INSERT INTO custom_cbl_entries "
        "(list_id,issue_id,position,created_at,is_checkpoint,"
        "checkpoint_target_issue_ids,gate,skipped) "
        "VALUES ($1,$2,1,NOW(),false,'[]','none',false), "
        "($1,$3,2,NOW(),false,'[]','none',false)",
        list_id,
        issue_b,
        issue_a,
    )
    return int(list_id)


def _env(token: str, method: str, uri: str, *, body: str | None = None) -> dict[str, str]:
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


def _assert_graph_ok(response: dict[str, object]) -> None:
    assert response.get("status") == 200, response
    body = response.get("body")
    assert isinstance(body, dict)
    assert body.get("status") == "ok"
    assert body.get("cycles") == []
    assert isinstance(body.get("affected_lists"), list)


def _assert_preview(response: dict[str, object]) -> None:
    assert response.get("status") == 200, response
    body = response.get("body")
    assert isinstance(body, dict)
    assert body.get("applied") is False
    assert body.get("status_before") == "cycle"
    assert body.get("status_after") == "ok"
    graph = body.get("graph")
    assert isinstance(graph, dict)
    assert graph.get("status") == "ok"
    assert graph.get("cycles") == []


def _assert_confirmed(response: dict[str, object]) -> None:
    assert response.get("status") == 200, response
    body = response.get("body")
    assert isinstance(body, dict)
    assert body.get("applied") is True
    assert body.get("status_before") == "cycle"
    assert body.get("status_after") == "ok"
    assert body.get("removed") == "Reading List deleted"
    graph = body.get("graph")
    assert isinstance(graph, dict)
    assert graph.get("status") == "ok"
    assert graph.get("cycles") == []


@pytest.mark.asyncio
async def test_reading_graph_fixed_budget_and_controlled_rejections() -> None:
    """Measure GET growth and reject injected extra and per-row route queries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username, 5)
        env = _env(token, "GET", "/api/v2/reading-graph")

        small_response, small = await measure_reading_route(
            BINARY, env, engine, GRAPH_ROUTE, "small"
        )
        _assert_graph_ok(small_response)
        small_n1_response, small_n1 = await measure_reading_route(
            BINARY,
            {**env, "RUST_ROLL_TEST_QUERY_INJECTION": "per-row"},
            engine,
            GRAPH_ROUTE,
            "small-controlled-n-plus-1",
        )
        _assert_graph_ok(small_n1_response)
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-graph", small_n1.db_statements)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for index in range(5, 200):
                await _insert_owned_thread(raw, owner_id, index)
        finally:
            await raw.close()

        large_response, large = await measure_reading_route(
            BINARY, env, engine, GRAPH_ROUTE, "large-200"
        )
        _assert_graph_ok(large_response)
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("unresolved_reference_count") == 0
        assert_fixed_budget("GET", "/api/v2/reading-graph", small, large)

        extra_response, extra = await measure_reading_route(
            BINARY,
            {**env, "RUST_ROLL_TEST_QUERY_INJECTION": "extra"},
            engine,
            GRAPH_ROUTE,
            "large-controlled-extra-query",
        )
        _assert_graph_ok(extra_response)
        assert extra.db_statements == (
            large.db_statements + 1 if large.db_statements is not None else None
        )
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-graph", extra.db_statements)

        large_n1_response, large_n1 = await measure_reading_route(
            BINARY,
            {**env, "RUST_ROLL_TEST_QUERY_INJECTION": "per-row"},
            engine,
            GRAPH_ROUTE,
            "large-controlled-n-plus-1",
        )
        _assert_graph_ok(large_n1_response)
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-graph", large_n1.db_statements)
        with pytest.raises(AssertionError, match="statement count grew"):
            assert_fixed_statement_count(
                small_n1.db_statements,
                large_n1.db_statements,
                kind="controlled N+1 top-level",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_preview_and_confirmed_repairs_have_fixed_budgets() -> None:
    """Measure both repair branches and verify confirmed deletions persist."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrn1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username, 5)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            rows = await raw.fetch(
                "SELECT id FROM issues WHERE thread_id IN "
                "(SELECT id FROM threads WHERE user_id=$1) ORDER BY id",
                owner_id,
            )
            issue_a, issue_b = (int(rows[0]["id"]), int(rows[1]["id"]))
            small_list_id = await _insert_cycle_list(
                raw, owner_id, "Small Cycle List", issue_a, issue_b
            )
            await raw.execute(
                "INSERT INTO dependencies "
                "(source_issue_id,target_issue_id,origin,classification,created_at) "
                "VALUES ($1,$2,'reader','A',NOW())",
                issue_a,
                issue_b,
            )
        finally:
            await raw.close()

        preview_env = _env(
            token,
            "POST",
            "/api/v2/reading-graph/repairs",
            body=json.dumps(
                {"action": "delete_list", "list_id": small_list_id, "confirm": False}
            ),
        )
        preview_response, small_preview = await measure_reading_route(
            BINARY, preview_env, engine, REPAIR_ROUTE, "preview-small"
        )
        _assert_preview(preview_response)

        confirm_env = _env(
            token,
            "POST",
            "/api/v2/reading-graph/repairs",
            body=json.dumps(
                {"action": "delete_list", "list_id": small_list_id, "confirm": True}
            ),
        )
        confirmed_response, small_confirmed = await measure_reading_route(
            BINARY, confirm_env, engine, REPAIR_ROUTE, "confirmed-small"
        )
        _assert_confirmed(confirmed_response)

        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", small_list_id
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", small_list_id
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM dependencies WHERE source_issue_id=$1 AND target_issue_id=$2",
                issue_a,
                issue_b,
            ) == 1
            for index in range(5, 200):
                await _insert_owned_thread(raw, owner_id, index)
            large_list_id = await _insert_cycle_list(
                raw, owner_id, "Large Cycle List", issue_a, issue_b
            )
        finally:
            await raw.close()

        large_preview_env = _env(
            token,
            "POST",
            "/api/v2/reading-graph/repairs",
            body=json.dumps(
                {"action": "delete_list", "list_id": large_list_id, "confirm": False}
            ),
        )
        large_preview_response, large_preview = await measure_reading_route(
            BINARY, large_preview_env, engine, REPAIR_ROUTE, "preview-large-200"
        )
        _assert_preview(large_preview_response)
        assert_fixed_budget(
            "POST",
            "/api/v2/reading-graph/repairs",
            small_preview,
            large_preview,
        )

        large_confirm_env = _env(
            token,
            "POST",
            "/api/v2/reading-graph/repairs",
            body=json.dumps(
                {"action": "delete_list", "list_id": large_list_id, "confirm": True}
            ),
        )
        large_confirmed_response, large_confirmed = await measure_reading_route(
            BINARY, large_confirm_env, engine, REPAIR_ROUTE, "confirmed-large-200"
        )
        _assert_confirmed(large_confirmed_response)
        assert_fixed_budget(
            "POST",
            "/api/v2/reading-graph/repairs",
            small_confirmed,
            large_confirmed,
        )

        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", large_list_id
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", large_list_id
            ) == 0
        finally:
            await raw.close()
    finally:
        await engine.dispose()
