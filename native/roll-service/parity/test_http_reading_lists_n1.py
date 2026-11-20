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
    SQL_BUDGET_SOURCES,
    assert_declared_budget,
    cargo_example_path,
    db_counters,
    db_nested_statements,
    run_rust_example,
)

SECRET = "synthetic-native-reading-lists-n1-secret"
BINARY = str(cargo_example_path("http_reading_lists"))


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


async def _insert_list(raw: asyncpg.Connection, owner_id: int, name: str, issue_ids: list[int]) -> int:
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
    *,
    check_growth: bool = True,
) -> None:
    """Apply the same maximum and no-growth checks used by the route tests."""
    assert_declared_budget(method, path, small, large)
    assert small is not None and large is not None
    if check_growth:
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
async def test_list_reading_lists_statements_do_not_grow_with_list_count() -> None:
    """GET /api/v2/reading-lists must stay set-based across list counts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlln1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            threads = []
            for i in range(5):
                t = Thread(user_id=owner.id, title=f"Series {i+1}", format="Comic", queue_position=i+1, issues_remaining=2, total_issues=2, status="active")
                db.add(t)
                await db.flush()
                for p in (1, 2):
                    db.add(Issue(thread_id=t.id, issue_number=str(p), position=p, status="unread"))
                threads.append(t)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_rows = await raw.fetch("SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id", owner_id)
            issue_ids = [r["id"] for r in issue_rows]
            for i in range(5):
                await _insert_list(raw, owner_id, f"List {i+1}", [issue_ids[i]])
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-lists")
        small, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small.get("status") == 200, small
        body = small.get("body")
        assert isinstance(body, list) and len(body) == 5
        assert body[0]["issue_count"] == 1

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            existing = await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE user_id=$1", owner_id)
            # Add more threads/issues/lists up to 200 total lists.
            for i in range(int(existing), 200):
                _, new_issue_ids = await _insert_owned_thread(raw, owner_id, i)
                await _insert_list(raw, owner_id, f"List {i+1}", [new_issue_ids[0]])
        finally:
            await raw.close()

        large, large_delta, large_nested = await _measured_route(
            engine, env, url=url, fixture="large"
        )
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, list) and len(large_body) == 200

        _assert_route_budget("GET", "/api/v2/reading-lists", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id} must stay set-based across entry counts."""
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
            small_issue_ids = []
            for i in range(5):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                small_issue_ids.append(ids[0])
            list_id = await _insert_list(raw, owner_id, "Detail", small_issue_ids)
        finally:
            await raw.close()

        env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}")
        small, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small.get("status") == 200, small
        body = small.get("body")
        assert isinstance(body, dict)
        assert body.get("id") == list_id
        assert body.get("issue_count") == 5
        assert isinstance(body.get("entries"), list) and len(body["entries"]) == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
                    list_id, ids[0], i + 1,
                )
        finally:
            await raw.close()

        large, large_delta, large_nested = await _measured_route(
            engine, env, url=url, fixture="large"
        )
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        assert len(large_body.get("entries", [])) == 200

        _assert_route_budget("GET", "/api/v2/reading-lists/{list_id}", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_list_reader_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id}/reader must stay set-based across entry counts."""
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
            small_issue_ids = []
            for i in range(5):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                small_issue_ids.append(ids[0])
            list_id = await _insert_list(raw, owner_id, "Reader", small_issue_ids)
        finally:
            await raw.close()

        env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}/reader")
        small, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small.get("status") == 200, small
        body = small.get("body")
        assert isinstance(body, dict)
        assert body.get("list_id") == list_id
        assert body.get("execution_mode") == "option_e"
        entries = body.get("entries")
        assert isinstance(entries, list) and len(entries) == 5
        assert all(e.get("availability") in {"available", "later", "blocked", "read", "excluded", "inactive"} for e in entries)

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
                    list_id, ids[0], i + 1,
                )
        finally:
            await raw.close()

        large, large_delta, large_nested = await _measured_route(
            engine, env, url=url, fixture="large"
        )
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict)
        assert len(large_body.get("entries", [])) == 200

        _assert_route_budget("GET", "/api/v2/reading-lists/{list_id}/reader", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_reading_list_statements_bounded() -> None:
    """DELETE /api/v2/reading-lists/{id} must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rldn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        async def _seed_one(*, entry_count: int) -> int:
            raw = await asyncpg.connect(url)
            try:
                owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
                issue_ids = []
                for index in range(entry_count):
                    _, issue_pair = await _insert_owned_thread(
                        raw, owner_id, int(uuid4().int % 100000) + index
                    )
                    issue_ids.append(issue_pair[0])
                return await _insert_list(raw, owner_id, f"D-{uuid4().hex[:6]}", issue_ids)
            finally:
                await raw.close()

        small_id = await _seed_one(entry_count=1)
        env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{small_id}")
        small, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small.get("status") == 204, small
        assert small.get("body") is None

        # The large target itself has 200 entries; a per-entry DELETE would
        # grow the measured count and fail the fixed budget.
        large_id = await _seed_one(entry_count=200)
        env2 = _run_env(token, "DELETE", f"/api/v2/reading-lists/{large_id}")
        large, large_delta, large_nested = await _measured_route(
            engine, env2, url=url, fixture="large"
        )
        assert large.get("status") == 204, large

        _assert_route_budget("DELETE", "/api/v2/reading-lists/{list_id}", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_reading_list_statements_respect_budget() -> None:
    """POST /api/v2/reading-lists must stay within declared max for small and large entry counts."""
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
            issue_ids_small = []
            for i in range(5):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                issue_ids_small.append(ids[0])
        finally:
            await raw.close()

        body_small = json.dumps({"name": "Small", "mode": "loose", "issue_ids": issue_ids_small})
        env = _run_env(token, "POST", "/api/v2/reading-lists", body=body_small)
        small, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small.get("status") == 201, small
        small_body = small.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("name") == "Small"
        assert small_body.get("issue_count") == 5
        assert len(small_body.get("entries", [])) == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids_large = []
            for i in range(5, 205):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                issue_ids_large.append(ids[0])
        finally:
            await raw.close()

        body_large = json.dumps({"name": "Large", "mode": "loose", "issue_ids": issue_ids_large})
        env2 = _run_env(token, "POST", "/api/v2/reading-lists", body=body_large)
        large, large_delta, large_nested = await _measured_route(
            engine, env2, url=url, fixture="large"
        )
        assert large.get("status") == 201, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        assert len(large_body.get("entries", [])) == 200

        _assert_route_budget("POST", "/api/v2/reading-lists", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_reading_list_statements_respect_budget() -> None:
    """PUT /api/v2/reading-lists/{id} must stay within declared max for small and large entry counts."""
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
            issue_ids_small = []
            for i in range(5):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                issue_ids_small.append(ids[0])
            list_id = await _insert_list(raw, owner_id, "Up", issue_ids_small[:3])
        finally:
            await raw.close()

        body_small = json.dumps({"name": "Up-small", "mode": "loose", "issue_ids": issue_ids_small})
        env = _run_env(token, "PUT", f"/api/v2/reading-lists/{list_id}", body=body_small)
        small, small_delta, small_nested = await _measured_route(
            engine, env, url=url, fixture="small"
        )
        assert small.get("status") == 200, small
        small_body = small.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("name") == "Up-small"
        assert small_body.get("issue_count") == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids_large = []
            for i in range(5, 205):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                issue_ids_large.append(ids[0])
            # reuse existing list with large payload
            full_ids = issue_ids_small + issue_ids_large
        finally:
            await raw.close()

        body_large = json.dumps({"name": "Up-large", "mode": "loose", "issue_ids": full_ids[:200]})
        env2 = _run_env(token, "PUT", f"/api/v2/reading-lists/{list_id}", body=body_large)
        large, large_delta, large_nested = await _measured_route(
            engine, env2, url=url, fixture="large"
        )
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        assert len(large_body.get("entries", [])) == 200

        _assert_route_budget("PUT", "/api/v2/reading-lists/{list_id}", small_delta, large_delta)
        assert large_nested <= small_nested + 2, (
            f"nested statements grew: {small_nested} -> {large_nested}"
        )
    finally:
        await engine.dispose()
