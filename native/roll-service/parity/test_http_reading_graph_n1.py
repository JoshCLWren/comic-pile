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
    SQL_BUDGET_SOURCES,
    assert_declared_budget,
    assert_flat_growth,
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


def _env(token: str, *, body: str | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "RUST_ROLL_TEST_TOKEN": token,
        "RUST_ROLL_TEST_METHOD": "GET" if body is None else "POST",
        "RUST_ROLL_TEST_URI": "/api/v2/reading-graph" if body is None else "/api/v2/reading-graph/repairs",
        "RUST_ROLL_DATABASE_URL": os.environ["RUST_ROLL_PARITY_DATABASE_URL"],
        "RUST_ROLL_JWT_SECRET": SECRET,
    }
    if body is not None:
        env["RUST_ROLL_TEST_BODY"] = body
    return env


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


async def _seed_library(engine, username: str, *, extra_threads: int) -> tuple[int, list[int]]:
    """Create a reader with ``extra_threads`` extra threads; return owner id and a cycle list."""
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

    raw = await asyncpg.connect(os.environ["RUST_ROLL_PARITY_DATABASE_URL"])
    try:
        owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
        issue_ids = [
            r["id"]
            for r in await raw.fetch(
                "SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id",
                owner_id,
            )
        ]
        list_id = await raw.fetchval(
            "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
            "VALUES ($1,'Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
            owner_id,
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
        for i in range(5, 5 + extra_threads):
            await _insert_owned_thread(raw, owner_id, i)
    finally:
        await raw.close()
    return owner_id, [list_id]


async def _measure(engine, env: dict[str, str], binary: str, *, timeout: float = 25.0):
    """Run one request and return (status, body, top-level delta, nested delta)."""
    _, _, top_before = await db_counters(engine)
    nested_before = await db_nested_statements(engine)
    response, _, _, _ = await run_rust_example(binary, env, timeout=timeout)
    _, _, top_after = await db_counters(engine)
    nested_after = await db_nested_statements(engine)
    assert top_before is not None and top_after is not None, "pg_stat_statements is required"
    assert nested_before is not None and nested_after is not None, (
        "pg_stat_statements track=all is required to measure nested statements"
    )
    return response, top_after - top_before, nested_after - nested_before


@pytest.mark.asyncio
async def test_reading_graph_statements_do_not_grow_with_library_size() -> None:
    """GET /api/v2/reading-graph must stay set-based across library sizes."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1_{uuid4().hex[:12]}"
        await _seed_library(engine, username, extra_threads=0)
        token = _token(username, jti=f"jti-{uuid4().hex}")
        env = _env(token)

        small_response, small_delta, small_nested = await _measure(engine, env, BINARY)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert isinstance(small_body.get("affected_lists"), list)
        assert small_body.get("unresolved_reference_count") == 0

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measure(engine, env, BINARY)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0

        assert_declared_budget("GET", "/api/v2/reading-graph", small_delta, large_delta)
        assert_flat_growth(small_delta, large_delta)
        assert_flat_growth(small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_preview_statements_do_not_grow_with_library_size() -> None:
    """POST /api/v2/reading-graph/repairs preview must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrn1_{uuid4().hex[:12]}"
        _, cycle_lists = await _seed_library(engine, username, extra_threads=0)
        list_id = cycle_lists[0]
        token = _token(username, jti=f"jti-{uuid4().hex}")
        body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": False})
        env = _env(token, body=body)

        small_response, small_delta, small_nested = await _measure(engine, env, BINARY)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        graph = small_body.get("graph")
        assert isinstance(graph, dict)
        assert graph.get("status") == "ok"
        assert graph.get("cycles") == []

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measure(engine, env, BINARY)
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

        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert_flat_growth(small_delta, large_delta)
        assert_flat_growth(small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_apply_statements_do_not_grow_with_library_size() -> None:
    """A confirmed repair persists the deletion and stays within the same budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        small_deltas = []
        large_deltas = []
        for label, extra in (("small", 0), ("large", 195)):
            username = f"rgan1_{label}_{uuid4().hex[:8]}"
            owner_id, cycle_lists = await _seed_library(engine, username, extra_threads=extra)
            list_id = cycle_lists[0]
            token = _token(username, jti=f"jti-{uuid4().hex}")
            body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": True})
            env = _env(token, body=body)

            response, top_delta, _nested = await _measure(engine, env, BINARY)
            assert response.get("status") == 200, response
            payload = response.get("body")
            assert isinstance(payload, dict)
            assert payload.get("applied") is True
            assert payload.get("status_before") == "cycle"
            assert payload.get("status_after") == "ok"
            graph = payload.get("graph")
            assert isinstance(graph, dict)
            assert graph.get("status") == "ok"

            raw = await asyncpg.connect(url)
            try:
                remaining = await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
                    list_id,
                    owner_id,
                )
            finally:
                await raw.close()
            assert remaining == 0, "confirmed repair must persist the Reading List deletion"

            if label == "small":
                small_deltas.append(top_delta)
            else:
                large_deltas.append(top_delta)

            assert_declared_budget("POST", "/api/v2/reading-graph/repairs", top_delta)

        assert_flat_growth(small_deltas[0], large_deltas[0])
    finally:
        await engine.dispose()


def _declared_max(method: str, path: str) -> int:
    document = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))
    matching = [
        entry
        for entry in document["operations"]
        if entry["method"] == method and entry["path"] == path
    ]
    assert len(matching) == 1
    return matching[0]["sql_budget"]["max_statements"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v2/reading-graph"),
        ("POST", "/api/v2/reading-graph/repairs"),
    ],
)
def test_route_budget_rejects_one_extra_statement(method: str, path: str) -> None:
    """The same budget check that passes at the declared max must reject max + 1."""
    maximum = _declared_max(method, path)
    assert_declared_budget(method, path, maximum)
    with pytest.raises(AssertionError):
        assert_declared_budget(method, path, maximum + 1)


@pytest.mark.parametrize(
    "method,path,small,large",
    [
        ("GET", "/api/v2/reading-graph", 6, 201),
        ("POST", "/api/v2/reading-graph/repairs", 11, 211),
    ],
)
def test_route_growth_guard_rejects_per_row_statements(
    method: str, path: str, small: int, large: int
) -> None:
    """A per-row N+1 must fail the same flat-growth check used by the measured routes."""
    assert_flat_growth(small, small + 2)
    with pytest.raises(AssertionError):
        assert_flat_growth(small, large)
    assert max(small, large) > _declared_max(method, path)
