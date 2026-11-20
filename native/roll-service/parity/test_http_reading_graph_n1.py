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
    SQL_BUDGET_SOURCES,
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


async def _seed_cycle(raw: asyncpg.Connection, owner_id: int, offset: int = 0) -> int:
    """Seed one reader-owned list/dependency cycle and return the list id."""
    issue_ids = [
        row["id"]
        for row in await raw.fetch(
            "SELECT id FROM issues WHERE thread_id IN "
            "(SELECT id FROM threads WHERE user_id=$1) ORDER BY id OFFSET $2 LIMIT 2",
            owner_id,
            offset,
        )
    ]
    assert len(issue_ids) == 2, "cycle fixture needs two owned issues"
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,'Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
        owner_id,
    )
    issue_a, issue_b = issue_ids
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


def _budget_maximum(method: str, path: str) -> int:
    """Read one declared maximum from the editable SQL budget source."""
    document = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))
    matching = [
        entry
        for entry in document["operations"]
        if entry["method"] == method and entry["path"] == path
    ]
    assert len(matching) == 1, f"missing or duplicate SQL budget: {method} {path}"
    return int(matching[0]["sql_budget"]["max_statements"])


def _assert_route_budget(
    method: str,
    path: str,
    small: int | None,
    large: int | None,
) -> None:
    """Apply the same maximum and no-growth checks used by the route tests."""
    assert_declared_budget(method, path, small, large)
    assert small is not None and large is not None
    assert large <= small + 2, f"statement count grew: {small} -> {large}"


async def _measured_route(
    engine: AsyncEngine,
    env: dict[str, str],
    *,
    url: str,
    fixture: str,
    extra_statements: int = 0,
    per_row_ids: tuple[int, ...] = (),
) -> tuple[dict[str, object], int, int]:
    """Measure one invocation's top-level and nested statements separately.

    Optional injected queries run under the same isolated service role inside
    the measurement window to prove the budget checks reject regressions.
    """
    nested_before = await db_nested_statements(engine)
    _, _, before = await db_counters(engine)
    response, _, _, _ = await run_rust_example(BINARY, env)
    if extra_statements or per_row_ids:
        connection = await asyncpg.connect(url)
        try:
            for _ in range(extra_statements):
                await connection.execute("SELECT 1")
            for row_id in per_row_ids:
                await connection.fetchval("SELECT $1::int", row_id)
        finally:
            await connection.close()
    _, _, after = await db_counters(engine)
    nested_after = await db_nested_statements(engine)
    assert before is not None and after is not None, "pg_stat_statements is required"
    assert nested_before is not None and nested_after is not None, (
        "pg_stat_statements.track must be all; track=top hides nested statements"
    )
    statements, nested = after - before, nested_after - nested_before
    assert statements >= 0 and nested >= 0
    print(
        f"route-budget route={env['RUST_ROLL_TEST_URI']} fixture={fixture} "
        f"db_statements={statements} db_nested_statements={nested}",
        flush=True,
    )
    return response, statements, nested


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
        small_response, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("status") == "ok"
        assert small_body.get("cycles") == []
        assert isinstance(small_body.get("affected_lists"), list)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measured_route(
            engine, env, url=url, fixture="large"
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("status") == "ok"
        assert large_body.get("cycles") == []
        assert large_body.get("unresolved_reference_count") == 0

        _assert_route_budget("GET", "/api/v2/reading-graph", small_delta, large_delta)
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
            list_id = await _seed_cycle(raw, owner_id)
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
        small_response, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="preview-small"
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        # Preview returns the projected graph after the proposed repair; nothing
        # is persisted, so the cycle remains in the database.
        graph = small_body.get("graph")
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert graph.get("repairs") == []
        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", list_id) == 1
        finally:
            await raw.close()

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measured_route(
            engine, env, url=url, fixture="preview-large"
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is False
        assert large_body.get("status_before") == "cycle"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"

        _assert_route_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_confirmed_repair_statements_and_persistence() -> None:
    """Confirmed repairs must be measured and verified against persisted state."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgcrn1_{uuid4().hex[:12]}"
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

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            small_list_id = await _seed_cycle(raw, owner_id, offset=0)
        finally:
            await raw.close()

        def confirm_env(list_id: int) -> dict[str, str]:
            return {
                **os.environ,
                "RUST_ROLL_TEST_TOKEN": token,
                "RUST_ROLL_TEST_METHOD": "POST",
                "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
                "RUST_ROLL_TEST_BODY": json.dumps(
                    {"action": "delete_list", "list_id": list_id, "confirm": True}
                ),
                "RUST_ROLL_DATABASE_URL": url,
                "RUST_ROLL_JWT_SECRET": SECRET,
            }

        small_response, small_delta, small_nested = await _measured_route(
            engine, confirm_env(small_list_id), url=url, fixture="confirm-small"
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is True
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        small_graph = small_body.get("graph")
        assert isinstance(small_graph, dict) and small_graph.get("status") == "ok"

        raw = await asyncpg.connect(url)
        try:
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", small_list_id
                )
                == 0
            ), "confirmed repair must persist the list deletion"
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
            large_list_id = await _seed_cycle(raw, owner_id, offset=2)
        finally:
            await raw.close()

        large_response, large_delta, large_nested = await _measured_route(
            engine, confirm_env(large_list_id), url=url, fixture="confirm-large"
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is True
        assert large_body.get("status_before") == "cycle"
        assert large_body.get("status_after") == "ok"
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"

        raw = await asyncpg.connect(url)
        try:
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", large_list_id
                )
                == 0
            ), "confirmed repair must persist the large-list deletion"
        finally:
            await raw.close()

        _assert_route_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_budget_rejects_injected_extra_query_and_n1() -> None:
    """The route budget and growth checks reject real extra/per-row queries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgbn1_{uuid4().hex[:12]}"
        thread_ids: list[int] = []
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
                thread_ids.append(thread.id)
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

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        path = "/api/v2/reading-graph"
        maximum = _budget_maximum("GET", path)
        response, baseline, _ = await _measured_route(
            engine, env, url=url, fixture="rejection-baseline"
        )
        assert response.get("status") == 200, response
        assert baseline <= maximum, f"uninjected route already over budget: {baseline}"

        # One extra query beyond the declared headroom must fail the budget.
        _, with_extra, _ = await _measured_route(
            engine,
            env,
            url=url,
            fixture="rejection-extra-query",
            extra_statements=maximum - baseline + 1,
        )
        assert with_extra == maximum + 1
        with pytest.raises(AssertionError, match="declared maximum"):
            _assert_route_budget("GET", path, with_extra, with_extra)

        # A per-thread query (an N+1) must fail the same no-growth check.
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
            assert (
                await raw.fetchval("SELECT count(*) FROM threads WHERE user_id=$1", owner_id)
                == 200
            )
            all_thread_ids = [
                row["id"]
                for row in await raw.fetch(
                    "SELECT id FROM threads WHERE user_id=$1 ORDER BY id", owner_id
                )
            ]
        finally:
            await raw.close()
        _, small_n1, _ = await _measured_route(
            engine, env, url=url, fixture="rejection-n1-small",
            per_row_ids=tuple(thread_ids[:5]),
        )
        _, large_n1, _ = await _measured_route(
            engine, env, url=url, fixture="rejection-n1-large",
            per_row_ids=tuple(all_thread_ids),
        )
        assert large_n1 > small_n1 + 2, f"injected N+1 did not grow: {small_n1} -> {large_n1}"
        with pytest.raises(AssertionError):
            _assert_route_budget("GET", path, small_n1, large_n1)
    finally:
        await engine.dispose()
