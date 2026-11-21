"""Measured SQL budget regressions for native v2 reading-graph endpoints (#5149)."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.models import User
from route_harness import (
    RouteMeasurement,
    assert_declared_budget,
    assert_declared_fixed_growth,
    cargo_example_path,
    measure_route_response,
)

SECRET = "synthetic-native-reading-graph-n1-secret"
BINARY = str(cargo_example_path("http_reading_graph"))
GRAPH_PATH = "/api/v2/reading-graph"
REPAIRS_PATH = "/api/v2/reading-graph/repairs"


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


async def _create_owner(engine: AsyncEngine, prefix: str) -> tuple[int, str]:
    """Create one isolated owner and return its database id and access token."""
    username = f"{prefix}_{uuid4().hex[:12]}"
    async with AsyncSession(engine, expire_on_commit=False) as db:
        owner = User(username=username)
        db.add(owner)
        await db.flush()
        owner_id = owner.id
        await db.commit()
    return owner_id, _token(username, jti=f"jti-{uuid4().hex}")


def _run_env(
    token: str,
    method: str,
    uri: str,
    *,
    body: dict[str, object] | None = None,
    extra_queries: int | None = None,
) -> dict[str, str]:
    """Build one isolated native-runner request environment."""
    env = {
        **os.environ,
        "RUST_ROLL_TEST_TOKEN": token,
        "RUST_ROLL_TEST_METHOD": method,
        "RUST_ROLL_TEST_URI": uri,
        "RUST_ROLL_DATABASE_URL": os.environ["RUST_ROLL_PARITY_DATABASE_URL"],
        "RUST_ROLL_JWT_SECRET": SECRET,
    }
    if body is not None:
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
    if extra_queries is None:
        env.pop("RUST_ROLL_TEST_EXTRA_QUERY_COUNT", None)
    else:
        env["RUST_ROLL_TEST_EXTRA_QUERY_COUNT"] = str(extra_queries)
    return env


async def _insert_owned_thread(
    raw: asyncpg.Connection,
    owner_id: int,
    index: int,
) -> None:
    """Insert one owned series and its two unread issues outside measurement."""
    thread_id = await raw.fetchval(
        "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) "
        "VALUES ($1,$2,'Comic',$3,2,2,'active') RETURNING id",
        owner_id,
        f"Series {index + 1}",
        index + 1,
    )
    for position in (1, 2):
        await raw.execute(
            "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
            "VALUES ($1,$2,$3,'unread',NOW())",
            thread_id,
            str(position),
            position,
        )


async def _seed_threads(
    raw: asyncpg.Connection,
    owner_id: int,
    start: int,
    stop: int,
) -> None:
    """Grow the canonical library to the requested thread count."""
    for index in range(start, stop):
        await _insert_owned_thread(raw, owner_id, index)


async def _seed_cycle(raw: asyncpg.Connection, owner_id: int, name: str) -> tuple[int, int]:
    """Create a strict-list/prerequisite cycle and return list/dependency ids."""
    rows = await raw.fetch(
        "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id "
        "WHERE t.user_id=$1 ORDER BY i.id LIMIT 2",
        owner_id,
    )
    assert len(rows) == 2
    issue_a, issue_b = (int(row["id"]) for row in rows)
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
        "VALUES ($1,$2,1,NOW(),false,'[]','none',false),"
        " ($1,$3,2,NOW(),false,'[]','none',false)",
        list_id,
        issue_b,
        issue_a,
    )
    dependency_id = await raw.fetchval(
        "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
        "VALUES ($1,$2,'reader','A',NOW()) RETURNING id",
        issue_a,
        issue_b,
    )
    return int(list_id), int(dependency_id)


def _assert_repaired_response(response: dict[str, object], *, applied: bool) -> None:
    """Check the real post-repair graph returned by preview and apply modes."""
    assert response.get("status") == 200, response
    body = response.get("body")
    assert isinstance(body, dict)
    assert body.get("applied") is applied
    assert body.get("status_before") == "cycle"
    assert body.get("status_after") == "ok"
    graph = body.get("graph")
    assert isinstance(graph, dict)
    assert graph.get("status") == "ok"
    assert graph.get("cycles") == []
    assert graph.get("repairs") == []
    assert graph.get("unresolved_reference_count") == 0


def _assert_fixed_budget(
    method: str,
    path: str,
    small: RouteMeasurement,
    large: RouteMeasurement,
) -> None:
    """Require separate top-level/nested measurements and fixed data growth."""
    assert small.db_statements is not None and large.db_statements is not None
    assert_declared_budget(method, path, small.db_statements, large.db_statements)
    assert_declared_fixed_growth(method, path, small.db_statements, large.db_statements)
    assert small.db_nested_statements is not None and large.db_nested_statements is not None, (
        "nested statement measurement requires pg_stat_statements.track=all"
    )
    assert small.db_nested_statements >= 0 and large.db_nested_statements >= 0
    assert large.db_nested_statements <= small.db_nested_statements + 2, (
        f"nested statement count grew: {small.db_nested_statements} -> "
        f"{large.db_nested_statements}"
    )


async def _assert_cycle_persisted(
    raw: asyncpg.Connection,
    list_id: int,
    dependency_id: int,
) -> None:
    """Prove preview did not mutate the list, entries, or dependency."""
    assert await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", list_id) == 1
    assert await raw.fetchval("SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id) == 2
    assert await raw.fetchval("SELECT count(*) FROM dependencies WHERE id=$1", dependency_id) == 1


async def _assert_repair_persisted(
    raw: asyncpg.Connection,
    list_id: int,
    dependency_id: int,
) -> None:
    """Prove apply removed only the selected list and preserved other records."""
    assert await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", list_id) == 0
    assert await raw.fetchval("SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id) == 0
    assert await raw.fetchval("SELECT count(*) FROM dependencies WHERE id=$1", dependency_id) == 1
    assert await raw.fetchval(
        "SELECT count(*) FROM issues i JOIN dependencies d ON d.id=$1 "
        "WHERE i.id=d.source_issue_id OR i.id=d.target_issue_id",
        dependency_id,
    ) == 2


@pytest.mark.asyncio
async def test_reading_graph_statements_do_not_grow_with_library_size() -> None:
    """GET /api/v2/reading-graph stays set-based across 5 and 200 series."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rgn1")
        raw = await asyncpg.connect(url)
        try:
            await _seed_threads(raw, owner_id, 0, 5)
            env = _run_env(token, "GET", GRAPH_PATH)
            small_response, small = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-graph", "5-series"
            )
            assert small_response.get("status") == 200, small_response
            small_body = small_response.get("body")
            assert isinstance(small_body, dict)
            assert small_body.get("status") == "ok"
            assert small_body.get("cycles") == []
            assert isinstance(small_body.get("affected_lists"), list)

            await _seed_threads(raw, owner_id, 5, 200)
            large_response, large = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-graph", "200-series"
            )
            assert large_response.get("status") == 200, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, dict)
            assert large_body.get("status") == "ok"
            assert large_body.get("cycles") == []
            assert large_body.get("unresolved_reference_count") == 0
            _assert_fixed_budget("GET", GRAPH_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_preview_statements_do_not_grow() -> None:
    """Repair preview returns the repaired graph without persisting the deletion."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rgrn1")
        raw = await asyncpg.connect(url)
        try:
            await _seed_threads(raw, owner_id, 0, 5)
            list_id, dependency_id = await _seed_cycle(raw, owner_id, "Preview cycle")
            env = _run_env(
                token,
                "POST",
                REPAIRS_PATH,
                body={"action": "delete_list", "list_id": list_id, "confirm": False},
            )
            small_response, small = await measure_route_response(
                BINARY, env, engine, "POST /api/v2/reading-graph/repairs", "preview-5-series"
            )
            _assert_repaired_response(small_response, applied=False)
            await _assert_cycle_persisted(raw, list_id, dependency_id)

            await _seed_threads(raw, owner_id, 5, 200)
            large_response, large = await measure_route_response(
                BINARY, env, engine, "POST /api/v2/reading-graph/repairs", "preview-200-series"
            )
            _assert_repaired_response(large_response, applied=False)
            await _assert_cycle_persisted(raw, list_id, dependency_id)
            _assert_fixed_budget("POST", REPAIRS_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_confirmed_repairs_measure_small_and_large() -> None:
    """Confirmed repairs persist exactly one deletion within the same fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rgcn1")
        raw = await asyncpg.connect(url)
        try:
            await _seed_threads(raw, owner_id, 0, 5)
            small_list, small_dependency = await _seed_cycle(raw, owner_id, "Apply small")
            small_env = _run_env(
                token,
                "POST",
                REPAIRS_PATH,
                body={"action": "delete_list", "list_id": small_list, "confirm": True},
            )
            small_response, small = await measure_route_response(
                BINARY, small_env, engine, "POST /api/v2/reading-graph/repairs", "apply-5-series"
            )
            _assert_repaired_response(small_response, applied=True)
            await _assert_repair_persisted(raw, small_list, small_dependency)

            await _seed_threads(raw, owner_id, 5, 200)
            large_list, large_dependency = await _seed_cycle(raw, owner_id, "Apply large")
            large_env = _run_env(
                token,
                "POST",
                REPAIRS_PATH,
                body={"action": "delete_list", "list_id": large_list, "confirm": True},
            )
            large_response, large = await measure_route_response(
                BINARY, large_env, engine, "POST /api/v2/reading-graph/repairs", "apply-200-series"
            )
            _assert_repaired_response(large_response, applied=True)
            await _assert_repair_persisted(raw, large_list, large_dependency)
            _assert_fixed_budget("POST", REPAIRS_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_extra_and_n_plus_one_queries() -> None:
    """Actual runner fault injection must trip both maximum and growth checks."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rgreject")
        raw = await asyncpg.connect(url)
        try:
            await _seed_threads(raw, owner_id, 0, 5)
            baseline_env = _run_env(token, "GET", GRAPH_PATH)
            baseline_response, baseline = await measure_route_response(
                BINARY, baseline_env, engine, "GET /api/v2/reading-graph", "rejection-baseline"
            )
            assert baseline_response.get("status") == 200, baseline_response
            assert baseline.db_statements is not None
            assert_declared_budget("GET", GRAPH_PATH, baseline.db_statements)

            extra_env = _run_env(token, "GET", GRAPH_PATH, extra_queries=1)
            extra_response, extra = await measure_route_response(
                BINARY, extra_env, engine, "GET /api/v2/reading-graph", "one-extra-query"
            )
            assert extra_response.get("status") == 200, extra_response
            assert extra.db_statements == baseline.db_statements + 1
            with pytest.raises(AssertionError, match="declared maximum"):
                assert_declared_budget("GET", GRAPH_PATH, extra.db_statements)

            small_n1_env = _run_env(token, "GET", GRAPH_PATH, extra_queries=5)
            small_n1_response, small_n1 = await measure_route_response(
                BINARY, small_n1_env, engine, "GET /api/v2/reading-graph", "n-plus-one-5-series"
            )
            assert small_n1_response.get("status") == 200, small_n1_response
            assert small_n1.db_statements == baseline.db_statements + 5

            await _seed_threads(raw, owner_id, 5, 12)
            large_response, large_baseline = await measure_route_response(
                BINARY, baseline_env, engine, "GET /api/v2/reading-graph", "large-baseline"
            )
            assert large_response.get("status") == 200, large_response
            large_n1_env = _run_env(token, "GET", GRAPH_PATH, extra_queries=12)
            large_n1_response, large_n1 = await measure_route_response(
                BINARY, large_n1_env, engine, "GET /api/v2/reading-graph", "n-plus-one-12-series"
            )
            assert large_n1_response.get("status") == 200, large_n1_response
            assert large_n1.db_statements == large_baseline.db_statements + 12
            with pytest.raises(AssertionError, match="declared maximum"):
                assert_declared_budget(
                    "GET", GRAPH_PATH, small_n1.db_statements, large_n1.db_statements
                )
            with pytest.raises(AssertionError, match="statement count grew"):
                assert_declared_fixed_growth(
                    "GET", GRAPH_PATH, small_n1.db_statements, large_n1.db_statements
                )
        finally:
            await raw.close()
    finally:
        await engine.dispose()
