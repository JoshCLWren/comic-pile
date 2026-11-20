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
    RouteMeasurement,
    assert_declared_budget,
    cargo_example_path,
    db_counters,
    declared_budget_max,
    measure_route,
    run_rust_example,
)

SECRET = "synthetic-native-reading-graph-n1-secret"
BINARY = str(cargo_example_path("http_reading_graph"))
GET_ROUTE = "GET /api/v2/reading-graph"
REPAIR_ROUTE = "POST /api/v2/reading-graph/repairs"


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


def _run_env(token: str, method: str, uri: str, *, body: str | None = None) -> dict[str, str]:
    env: dict[str, str] = {
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


def _body_dict(measurement: RouteMeasurement) -> dict[str, object]:
    assert isinstance(measurement.body, dict), measurement.body
    return measurement.body


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
    issue_ids: list[int] = []
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


async def _grow_library(raw: asyncpg.Connection, owner_id: int, start: int = 5) -> None:
    for index in range(start, 200):
        await _insert_owned_thread(raw, owner_id, index)


async def _seed_cycle(raw: asyncpg.Connection, owner_id: int, index: int) -> int:
    _, issue_ids = await _insert_owned_thread(raw, owner_id, index)
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'strict',NOW(),NOW()) RETURNING id",
        owner_id,
        f"Cycle List {index}",
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


def _assert_measured(measurement: RouteMeasurement, method: str, path: str, status: int) -> None:
    assert measurement.status == status, measurement.body
    assert measurement.db_statements is not None, "pg_stat_statements top-level counters are required"
    assert measurement.db_nested_statements is not None, (
        "pg_stat_statements.track=all is required for separate nested measurement"
    )
    assert_declared_budget(method, path, measurement.db_statements)


def _assert_fixed_growth(small: RouteMeasurement, large: RouteMeasurement) -> None:
    top_small = small.db_statements
    top_large = large.db_statements
    assert top_small is not None and top_large is not None
    assert top_large <= top_small + 2, f"top-level statements grew: {top_small} -> {top_large}"


async def _measure_with_injected_queries(
    url: str,
    engine: AsyncEngine,
    binary: str,
    env: dict[str, str],
    route: str,
    fixture: str,
    injection_count: int,
) -> int:
    """Measure a route plus deliberately injected queries under the route role."""
    _, _, before = await db_counters(engine)
    response, _, _, _ = await run_rust_example(binary, env)
    assert response.get("status") == 200, response
    raw = await asyncpg.connect(url)
    try:
        for _ in range(injection_count):
            await raw.execute("SELECT 1")
    finally:
        await raw.close()
    _, _, after = await db_counters(engine)
    assert before is not None and after is not None
    return after - before


@pytest.mark.asyncio
async def test_reading_graph_statements_do_not_grow_with_library_size() -> None:
    """GET /api/v2/reading-graph stays set-based and separately measured for 5 and 200 threads."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for index in range(5):
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
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = _run_env(token, "GET", "/api/v2/reading-graph")
        small = await measure_route(BINARY, env, engine, GET_ROUTE, "5 threads")
        _assert_measured(small, "GET", "/api/v2/reading-graph", 200)
        small_body = _body_dict(small)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert isinstance(small_body.get("affected_lists"), list)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            await _grow_library(raw, owner_id)
        finally:
            await raw.close()

        large = await measure_route(BINARY, env, engine, GET_ROUTE, "200 threads")
        _assert_measured(large, "GET", "/api/v2/reading-graph", 200)
        large_body = _body_dict(large)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repair_preview_measures_repaired_graph() -> None:
    """POST repair preview measures the graph after the proposed repair, not the input cycle."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for index in range(5):
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
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            list_id = await _seed_cycle(raw, owner_id, 100)
        finally:
            await raw.close()

        body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": False})
        env = _run_env(token, "POST", "/api/v2/reading-graph/repairs", body=body)
        small = await measure_route(BINARY, env, engine, REPAIR_ROUTE, "preview 5 threads")
        _assert_measured(small, "POST", "/api/v2/reading-graph/repairs", 200)
        small_body = _body_dict(small)
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
            await _grow_library(raw, owner_id)
        finally:
            await raw.close()

        large = await measure_route(BINARY, env, engine, REPAIR_ROUTE, "preview 200 threads")
        _assert_measured(large, "POST", "/api/v2/reading-graph/repairs", 200)
        large_body = _body_dict(large)
        assert large_body.get("applied") is False
        assert large_body.get("status_before") == "cycle"
        assert large_body.get("status_after") == "ok"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict)
        assert large_graph.get("status") == "ok"
        assert large_graph.get("cycles") == []
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_confirmed_repair_measures_apply_branch() -> None:
    """Confirmed repairs are measured for small and large graphs and persist the result."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgcrn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            small_list_id = await _seed_cycle(raw, owner_id, 200)
        finally:
            await raw.close()

        body = json.dumps({"action": "delete_list", "list_id": small_list_id, "confirm": True})
        env = _run_env(token, "POST", "/api/v2/reading-graph/repairs", body=body)
        small = await measure_route(BINARY, env, engine, REPAIR_ROUTE, "confirm 5 threads")
        _assert_measured(small, "POST", "/api/v2/reading-graph/repairs", 200)
        small_body = _body_dict(small)
        assert small_body.get("applied") is True
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        small_graph = small_body.get("graph")
        assert isinstance(small_graph, dict) and small_graph.get("status") == "ok"

        raw = await asyncpg.connect(url)
        try:
            remaining = await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", small_list_id
            )
            assert remaining == 0
            await _grow_library(raw, owner_id)
            large_list_id = await _seed_cycle(raw, owner_id, 300)
        finally:
            await raw.close()

        body = json.dumps({"action": "delete_list", "list_id": large_list_id, "confirm": True})
        env = _run_env(token, "POST", "/api/v2/reading-graph/repairs", body=body)
        large = await measure_route(BINARY, env, engine, REPAIR_ROUTE, "confirm 200 threads")
        _assert_measured(large, "POST", "/api/v2/reading-graph/repairs", 200)
        large_body = _body_dict(large)
        assert large_body.get("applied") is True
        assert large_body.get("status_before") == "cycle"
        assert large_body.get("status_after") == "ok"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"

        raw = await asyncpg.connect(url)
        try:
            remaining = await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", large_list_id
            )
            assert remaining == 0
        finally:
            await raw.close()
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_injected_extra_query() -> None:
    """One deliberate extra query beyond headroom fails the same declared budget check."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgxqn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = _run_env(token, "GET", "/api/v2/reading-graph")
        normal = await measure_route(BINARY, env, engine, GET_ROUTE, "rejection baseline")
        assert normal.db_statements is not None
        maximum = declared_budget_max("GET", "/api/v2/reading-graph")
        assert normal.db_statements <= maximum
        injected_count = await _measure_with_injected_queries(
            url, engine, BINARY, env, GET_ROUTE, "extra query", maximum - normal.db_statements + 1
        )
        assert injected_count > maximum
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-graph", injected_count)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_injected_n_plus_one() -> None:
    """A deliberate per-issue query pattern fails the graph route budget and growth check."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1q_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for index in range(5):
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
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = _run_env(token, "GET", "/api/v2/reading-graph")
        small = await _measure_with_injected_queries(
            url, engine, BINARY, env, GET_ROUTE, "N+1 10 issues", 10
        )
        maximum = declared_budget_max("GET", "/api/v2/reading-graph")
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-graph", small)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            await _grow_library(raw, owner_id)
            issue_count = await raw.fetchval(
                "SELECT count(*) FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1",
                owner_id,
            )
        finally:
            await raw.close()

        large = await _measure_with_injected_queries(
            url, engine, BINARY, env, GET_ROUTE, f"N+1 {issue_count} issues", int(issue_count)
        )
        assert large > small + 2, f"injected N+1 did not grow: {small} -> {large}"
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-graph", large)
    finally:
        await engine.dispose()
