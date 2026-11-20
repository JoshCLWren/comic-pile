"""Measured SQL budget regressions for native v2 reading-list endpoints (#5149)."""

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

SECRET = "synthetic-native-reading-lists-n1-secret"
BINARY = str(cargo_example_path("http_reading_lists"))
LIST_ROUTE = "GET /api/v2/reading-lists"
CREATE_ROUTE = "POST /api/v2/reading-lists"
DELETE_ROUTE = "DELETE /api/v2/reading-lists/{list_id}"
DETAIL_ROUTE = "GET /api/v2/reading-lists/{list_id}"
UPDATE_ROUTE = "PUT /api/v2/reading-lists/{list_id}"
READER_ROUTE = "GET /api/v2/reading-lists/{list_id}/reader"


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


def _body_list(measurement: RouteMeasurement) -> list[object]:
    assert isinstance(measurement.body, list), measurement.body
    return measurement.body


def _entries(measurement: RouteMeasurement) -> list[object]:
    body = _body_dict(measurement)
    entries = body.get("entries")
    assert isinstance(entries, list), entries
    return entries


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


async def _insert_list(
    raw: asyncpg.Connection, owner_id: int, name: str, issue_ids: list[int]
) -> int:
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'loose',NOW(),NOW()) RETURNING id",
        owner_id,
        name,
    )
    for position, issue_id in enumerate(issue_ids, start=1):
        await raw.execute(
            "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
            "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
            list_id,
            issue_id,
            position,
        )
    return list_id


async def _grow_threads(
    raw: asyncpg.Connection, owner_id: int, start: int, stop: int
) -> list[int]:
    issue_ids: list[int] = []
    for index in range(start, stop):
        _, new_ids = await _insert_owned_thread(raw, owner_id, index)
        issue_ids.extend(new_ids)
    return issue_ids


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


def _assert_declared_growth(small: RouteMeasurement, large: RouteMeasurement) -> None:
    top_small = small.db_statements
    top_large = large.db_statements
    assert top_small is not None and top_large is not None
    assert top_large > top_small, f"200-entry batch did not add statements: {top_small} -> {top_large}"


async def _measure_with_injected_queries(
    url: str,
    engine: AsyncEngine,
    binary: str,
    env: dict[str, str],
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
async def test_list_reading_lists_statements_do_not_grow_with_list_count() -> None:
    """GET /api/v2/reading-lists stays set-based and separately measured for 5 and 200 lists."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlln1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = await _grow_threads(raw, owner_id, 0, 5)
            for index in range(5):
                await _insert_list(raw, owner_id, f"List {index + 1}", [issue_ids[index]])
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-lists")
        small = await measure_route(BINARY, env, engine, LIST_ROUTE, "5 lists")
        _assert_measured(small, "GET", "/api/v2/reading-lists", 200)
        small_body = _body_list(small)
        assert len(small_body) == 5
        assert all(isinstance(item, dict) and item.get("issue_count") == 1 for item in small_body)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for index in range(5, 200):
                _, new_ids = await _insert_owned_thread(raw, owner_id, index)
                await _insert_list(raw, owner_id, f"List {index + 1}", [new_ids[0]])
        finally:
            await raw.close()

        large = await measure_route(BINARY, env, engine, LIST_ROUTE, "200 lists")
        _assert_measured(large, "GET", "/api/v2/reading-lists", 200)
        assert len(_body_list(large)) == 200
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id} stays set-based for 5 and 200 entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlgn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = await _grow_threads(raw, owner_id, 0, 5)
            list_id = await _insert_list(raw, owner_id, "Detail", issue_ids[::2])
        finally:
            await raw.close()

        env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}")
        small = await measure_route(BINARY, env, engine, DETAIL_ROUTE, "5 entries")
        _assert_measured(small, "GET", "/api/v2/reading-lists/{list_id}", 200)
        small_body = _body_dict(small)
        assert small_body.get("id") == list_id
        assert small_body.get("issue_count") == 5
        assert len(_entries(small)) == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            new_ids = await _grow_threads(raw, owner_id, 5, 200)
            for issue_id in new_ids:
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
                    list_id,
                    issue_id,
                    issue_id,
                )
        finally:
            await raw.close()

        large = await measure_route(BINARY, env, engine, DETAIL_ROUTE, "200 entries")
        _assert_measured(large, "GET", "/api/v2/reading-lists/{list_id}", 200)
        large_body = _body_dict(large)
        assert large_body.get("issue_count") == 200
        assert len(_entries(large)) == 200
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_list_reader_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id}/reader stays set-based for 5 and 200 entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlrn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = await _grow_threads(raw, owner_id, 0, 5)
            list_id = await _insert_list(raw, owner_id, "Reader", issue_ids[::2])
        finally:
            await raw.close()

        env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}/reader")
        small = await measure_route(BINARY, env, engine, READER_ROUTE, "5 entries")
        _assert_measured(small, "GET", "/api/v2/reading-lists/{list_id}/reader", 200)
        small_body = _body_dict(small)
        assert small_body.get("list_id") == list_id
        assert small_body.get("execution_mode") == "option_e"
        entries = small_body.get("entries")
        assert isinstance(entries, list) and len(entries) == 5
        assert all(
            isinstance(entry, dict)
            and entry.get("availability")
            in {"available", "later", "blocked", "read", "excluded", "inactive"}
            for entry in entries
        )

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            new_ids = await _grow_threads(raw, owner_id, 5, 200)
            for issue_id in new_ids:
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
                    list_id,
                    issue_id,
                    issue_id,
                )
        finally:
            await raw.close()

        large = await measure_route(BINARY, env, engine, READER_ROUTE, "200 entries")
        _assert_measured(large, "GET", "/api/v2/reading-lists/{list_id}/reader", 200)
        large_body = _body_dict(large)
        assert len(_entries(large)) == 200
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_reading_list_statements_bounded_for_long_target() -> None:
    """DELETE stays fixed at the top level even when the target list holds 200 entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rldn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = await _grow_threads(raw, owner_id, 0, 5)
            small_id = await _insert_list(raw, owner_id, "Delete-small", issue_ids[::2])
        finally:
            await raw.close()

        env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{small_id}")
        small = await measure_route(BINARY, env, engine, DELETE_ROUTE, "5-entry target")
        _assert_measured(small, "DELETE", "/api/v2/reading-lists/{list_id}", 204)
        assert small.body is None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            large_ids = await _grow_threads(raw, owner_id, 5, 205)
            large_id = await _insert_list(raw, owner_id, "Delete-large", large_ids[::2])
        finally:
            await raw.close()

        env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{large_id}")
        large = await measure_route(BINARY, env, engine, DELETE_ROUTE, "200-entry target")
        _assert_measured(large, "DELETE", "/api/v2/reading-lists/{list_id}", 204)
        assert large.body is None

        raw = await asyncpg.connect(url)
        try:
            for list_id in (small_id, large_id):
                remaining = await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", list_id
                )
                assert remaining == 0
        finally:
            await raw.close()
        _assert_fixed_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_reading_list_statements_respect_budget() -> None:
    """POST /api/v2/reading-lists is measured for 5- and 200-entry supported batches."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlcn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            small_ids = await _grow_threads(raw, owner_id, 0, 5)
        finally:
            await raw.close()

        body = json.dumps({"name": "Small", "mode": "loose", "issue_ids": small_ids[::2]})
        env = _run_env(token, "POST", "/api/v2/reading-lists", body=body)
        small = await measure_route(BINARY, env, engine, CREATE_ROUTE, "5 entries")
        _assert_measured(small, "POST", "/api/v2/reading-lists", 201)
        small_body = _body_dict(small)
        assert small_body.get("name") == "Small"
        assert small_body.get("issue_count") == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            large_ids = await _grow_threads(raw, owner_id, 5, 205)
        finally:
            await raw.close()

        body = json.dumps({"name": "Large", "mode": "loose", "issue_ids": large_ids[::2]})
        env = _run_env(token, "POST", "/api/v2/reading-lists", body=body)
        large = await measure_route(BINARY, env, engine, CREATE_ROUTE, "200 entries")
        _assert_measured(large, "POST", "/api/v2/reading-lists", 201)
        assert _body_dict(large).get("issue_count") == 200
        _assert_declared_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_reading_list_statements_respect_budget() -> None:
    """PUT /api/v2/reading-lists/{id} is measured for 5- and 200-entry supported batches."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlun1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            small_ids = await _grow_threads(raw, owner_id, 0, 5)
            list_id = await _insert_list(raw, owner_id, "Up", small_ids[1::2])
        finally:
            await raw.close()

        body = json.dumps({"name": "Up-small", "mode": "loose", "issue_ids": small_ids[::2]})
        env = _run_env(token, "PUT", f"/api/v2/reading-lists/{list_id}", body=body)
        small = await measure_route(BINARY, env, engine, UPDATE_ROUTE, "5 entries")
        _assert_measured(small, "PUT", "/api/v2/reading-lists/{list_id}", 200)
        small_body = _body_dict(small)
        assert small_body.get("name") == "Up-small"
        assert small_body.get("issue_count") == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            large_ids = await _grow_threads(raw, owner_id, 5, 205)
        finally:
            await raw.close()

        full_ids = small_ids[::2] + large_ids[::2]
        body = json.dumps({"name": "Up-large", "mode": "loose", "issue_ids": full_ids[:200]})
        env = _run_env(token, "PUT", f"/api/v2/reading-lists/{list_id}", body=body)
        large = await measure_route(BINARY, env, engine, UPDATE_ROUTE, "200 entries")
        _assert_measured(large, "PUT", "/api/v2/reading-lists/{list_id}", 200)
        assert _body_dict(large).get("issue_count") == 200
        _assert_declared_growth(small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_lists_budget_rejects_injected_extra_query() -> None:
    """One deliberate extra query beyond headroom fails the list route's declared budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlxqn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = _run_env(token, "GET", "/api/v2/reading-lists")
        normal = await measure_route(BINARY, env, engine, LIST_ROUTE, "rejection baseline")
        assert normal.db_statements is not None
        maximum = declared_budget_max("GET", "/api/v2/reading-lists")
        assert normal.db_statements <= maximum
        injected_count = await _measure_with_injected_queries(
            url, engine, BINARY, env, maximum - normal.db_statements + 1
        )
        assert injected_count > maximum
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-lists", injected_count)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_lists_budget_rejects_injected_n_plus_one() -> None:
    """A deliberate per-list query pattern fails the list route budget and growth check."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlln1q_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = await _grow_threads(raw, owner_id, 0, 5)
            for index in range(5):
                await _insert_list(raw, owner_id, f"List {index + 1}", [issue_ids[index]])
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-lists")
        small = await _measure_with_injected_queries(url, engine, BINARY, env, 5)
        maximum = declared_budget_max("GET", "/api/v2/reading-lists")
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-lists", small)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for index in range(5, 200):
                _, new_ids = await _insert_owned_thread(raw, owner_id, index)
                await _insert_list(raw, owner_id, f"List {index + 1}", [new_ids[0]])
            list_count = await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE user_id=$1", owner_id
            )
        finally:
            await raw.close()

        large = await _measure_with_injected_queries(
            url, engine, BINARY, env, int(list_count)
        )
        assert large > small + 2, f"injected N+1 did not grow: {small} -> {large}"
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget("GET", "/api/v2/reading-lists", large)
    finally:
        await engine.dispose()
