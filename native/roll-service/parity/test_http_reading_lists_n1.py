"""Measured SQL budget regressions for native v2 reading-list endpoints (#5149)."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.models import User
from reading_budget_harness import assert_fixed_budget, measure_reading_route
from route_harness import cargo_example_path

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


async def _seed_owner(engine: AsyncEngine, username: str) -> str:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(User(username=username))
        await db.commit()
    return _token(username, jti=f"jti-{uuid4().hex}")


async def _insert_owned_thread(
    raw: asyncpg.Connection,
    owner_id: int,
    index: int,
) -> tuple[int, list[int]]:
    """Insert one canonical thread with two unread issues outside measurement."""
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


async def _insert_threads(
    raw: asyncpg.Connection,
    owner_id: int,
    start: int,
    count: int,
) -> list[int]:
    first_issue_ids = []
    for index in range(start, start + count):
        _, issue_ids = await _insert_owned_thread(raw, owner_id, index)
        first_issue_ids.append(int(issue_ids[0]))
    return first_issue_ids


async def _append_entries(
    raw: asyncpg.Connection,
    list_id: int,
    issue_ids: list[int],
    *,
    start_position: int = 1,
) -> None:
    positions = list(range(start_position, start_position + len(issue_ids)))
    await raw.execute(
        "INSERT INTO custom_cbl_entries "
        "(list_id,issue_id,position,created_at,is_checkpoint,"
        "checkpoint_target_issue_ids,gate,skipped) "
        "SELECT $1, issue_id, position, NOW(), false, '[]', 'none', false "
        "FROM unnest($2::int[], $3::int[]) AS entry(issue_id, position)",
        list_id,
        issue_ids,
        positions,
    )


async def _insert_list(
    raw: asyncpg.Connection,
    owner_id: int,
    name: str,
    issue_ids: list[int],
) -> int:
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'loose',NOW(),NOW()) RETURNING id",
        owner_id,
        name,
    )
    await _append_entries(raw, int(list_id), issue_ids)
    return int(list_id)


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


def _dict_body(response: dict[str, object], status: int) -> dict[str, object]:
    assert response.get("status") == status, response
    body = response.get("body")
    assert isinstance(body, dict)
    return body


def _list_body(response: dict[str, object], status: int) -> list[object]:
    assert response.get("status") == status, response
    body = response.get("body")
    assert isinstance(body, list)
    return body


async def _owner_id(raw: asyncpg.Connection, username: str) -> int:
    return int(await raw.fetchval("SELECT id FROM users WHERE username=$1", username))


@pytest.mark.asyncio
async def test_list_reading_lists_statements_do_not_grow_with_list_count() -> None:
    """GET collection stays set-based from 5 through 200 lists."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlln1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            issue_ids = await _insert_threads(raw, owner_id, 0, 5)
            for index, issue_id in enumerate(issue_ids):
                await _insert_list(raw, owner_id, f"List {index + 1}", [issue_id])
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-lists")
        small_response, small = await measure_reading_route(
            BINARY, env, engine, LIST_ROUTE, "small"
        )
        small_body = _list_body(small_response, 200)
        assert len(small_body) == 5
        assert isinstance(small_body[0], dict)
        assert small_body[0].get("issue_count") == 1

        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            issue_ids = await _insert_threads(raw, owner_id, 5, 195)
            for index, issue_id in enumerate(issue_ids, start=5):
                await _insert_list(raw, owner_id, f"List {index + 1}", [issue_id])
        finally:
            await raw.close()

        large_response, large = await measure_reading_route(
            BINARY, env, engine, LIST_ROUTE, "large-200"
        )
        assert len(_list_body(large_response, 200)) == 200
        assert_fixed_budget("GET", "/api/v2/reading-lists", small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """GET detail stays set-based from 5 through 200 target entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlgn1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            issue_ids = await _insert_threads(raw, owner_id, 0, 5)
            list_id = await _insert_list(raw, owner_id, "Detail", issue_ids)
        finally:
            await raw.close()

        env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}")
        small_response, small = await measure_reading_route(
            BINARY, env, engine, DETAIL_ROUTE, "small"
        )
        small_body = _dict_body(small_response, 200)
        assert small_body.get("id") == list_id
        assert small_body.get("issue_count") == 5
        assert isinstance(small_body.get("entries"), list)
        assert len(small_body["entries"]) == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            issue_ids = await _insert_threads(raw, owner_id, 5, 195)
            await _append_entries(raw, list_id, issue_ids, start_position=6)
        finally:
            await raw.close()

        large_response, large = await measure_reading_route(
            BINARY, env, engine, DETAIL_ROUTE, "large-200"
        )
        large_body = _dict_body(large_response, 200)
        assert large_body.get("issue_count") == 200
        assert isinstance(large_body.get("entries"), list)
        assert len(large_body["entries"]) == 200
        assert_fixed_budget("GET", "/api/v2/reading-lists/{list_id}", small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_list_reader_statements_do_not_grow_with_entry_count() -> None:
    """GET reader stays set-based from 5 through 200 projected entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlrn1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            issue_ids = await _insert_threads(raw, owner_id, 0, 5)
            list_id = await _insert_list(raw, owner_id, "Reader", issue_ids)
        finally:
            await raw.close()

        env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}/reader")
        small_response, small = await measure_reading_route(
            BINARY, env, engine, READER_ROUTE, "small"
        )
        small_body = _dict_body(small_response, 200)
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
            owner_id = await _owner_id(raw, username)
            issue_ids = await _insert_threads(raw, owner_id, 5, 195)
            await _append_entries(raw, list_id, issue_ids, start_position=6)
        finally:
            await raw.close()

        large_response, large = await measure_reading_route(
            BINARY, env, engine, READER_ROUTE, "large-200"
        )
        large_body = _dict_body(large_response, 200)
        large_entries = large_body.get("entries")
        assert isinstance(large_entries, list) and len(large_entries) == 200
        assert_fixed_budget("GET", "/api/v2/reading-lists/{list_id}/reader", small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_reading_list_statements_do_not_grow_with_target_entries() -> None:
    """DELETE removes one-entry and 200-entry targets with the same fixed SQL."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rldn1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            small_issue_ids = await _insert_threads(raw, owner_id, 0, 1)
            small_id = await _insert_list(raw, owner_id, "Delete Small", small_issue_ids)
        finally:
            await raw.close()

        small_env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{small_id}")
        small_response, small = await measure_reading_route(
            BINARY, small_env, engine, DELETE_ROUTE, "small-one-entry"
        )
        assert small_response.get("status") == 204, small_response
        assert small_response.get("body") is None

        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", small_id
            ) == 0
            owner_id = await _owner_id(raw, username)
            large_issue_ids = await _insert_threads(raw, owner_id, 1, 200)
            large_id = await _insert_list(raw, owner_id, "Delete Large", large_issue_ids)
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", large_id
            ) == 200
        finally:
            await raw.close()

        large_env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{large_id}")
        large_response, large = await measure_reading_route(
            BINARY, large_env, engine, DELETE_ROUTE, "large-200-entries"
        )
        assert large_response.get("status") == 204, large_response
        assert large_response.get("body") is None
        assert_fixed_budget("DELETE", "/api/v2/reading-lists/{list_id}", small, large)

        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", large_id
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", large_id
            ) == 0
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """POST uses one set-based entry insert for both 5 and 200 issues."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlcn1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            small_issue_ids = await _insert_threads(raw, owner_id, 0, 5)
        finally:
            await raw.close()

        small_env = _run_env(
            token,
            "POST",
            "/api/v2/reading-lists",
            body=json.dumps({"name": "Small", "mode": "loose", "issue_ids": small_issue_ids}),
        )
        small_response, small = await measure_reading_route(
            BINARY, small_env, engine, CREATE_ROUTE, "small"
        )
        small_body = _dict_body(small_response, 201)
        assert small_body.get("name") == "Small"
        assert small_body.get("issue_count") == 5
        assert isinstance(small_body.get("entries"), list)
        assert len(small_body["entries"]) == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            large_issue_ids = small_issue_ids + await _insert_threads(raw, owner_id, 5, 195)
        finally:
            await raw.close()

        large_env = _run_env(
            token,
            "POST",
            "/api/v2/reading-lists",
            body=json.dumps({"name": "Large", "mode": "loose", "issue_ids": large_issue_ids}),
        )
        large_response, large = await measure_reading_route(
            BINARY, large_env, engine, CREATE_ROUTE, "large-200"
        )
        large_body = _dict_body(large_response, 201)
        assert large_body.get("issue_count") == 200
        assert isinstance(large_body.get("entries"), list)
        assert len(large_body["entries"]) == 200
        assert_fixed_budget("POST", "/api/v2/reading-lists", small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """PUT uses one set-based replacement insert for both 5 and 200 issues."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rlun1_{uuid4().hex[:12]}"
        token = await _seed_owner(engine, username)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            small_issue_ids = await _insert_threads(raw, owner_id, 0, 5)
            list_id = await _insert_list(raw, owner_id, "Up", small_issue_ids[:3])
        finally:
            await raw.close()

        small_env = _run_env(
            token,
            "PUT",
            f"/api/v2/reading-lists/{list_id}",
            body=json.dumps(
                {"name": "Up-small", "mode": "loose", "issue_ids": small_issue_ids}
            ),
        )
        small_response, small = await measure_reading_route(
            BINARY, small_env, engine, UPDATE_ROUTE, "small"
        )
        small_body = _dict_body(small_response, 200)
        assert small_body.get("name") == "Up-small"
        assert small_body.get("issue_count") == 5
        assert isinstance(small_body.get("entries"), list)
        assert len(small_body["entries"]) == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await _owner_id(raw, username)
            large_issue_ids = small_issue_ids + await _insert_threads(raw, owner_id, 5, 195)
        finally:
            await raw.close()

        large_env = _run_env(
            token,
            "PUT",
            f"/api/v2/reading-lists/{list_id}",
            body=json.dumps(
                {"name": "Up-large", "mode": "loose", "issue_ids": large_issue_ids}
            ),
        )
        large_response, large = await measure_reading_route(
            BINARY, large_env, engine, UPDATE_ROUTE, "large-200"
        )
        large_body = _dict_body(large_response, 200)
        assert large_body.get("issue_count") == 200
        assert isinstance(large_body.get("entries"), list)
        assert len(large_body["entries"]) == 200
        assert_fixed_budget("PUT", "/api/v2/reading-lists/{list_id}", small, large)

        raw = await asyncpg.connect(url)
        try:
            assert await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id
            ) == 200
        finally:
            await raw.close()
    finally:
        await engine.dispose()
