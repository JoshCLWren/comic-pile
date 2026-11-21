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
from route_harness import (
    RouteMeasurement,
    assert_declared_budget,
    assert_declared_fixed_growth,
    cargo_example_path,
    measure_route_response,
)

SECRET = "synthetic-native-reading-lists-n1-secret"
BINARY = str(cargo_example_path("http_reading_lists"))
LISTS_PATH = "/api/v2/reading-lists"
LIST_PATH = "/api/v2/reading-lists/{list_id}"
READER_PATH = "/api/v2/reading-lists/{list_id}/reader"


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
    return env


async def _seed_issue_ids(
    raw: asyncpg.Connection,
    owner_id: int,
    start: int,
    stop: int,
) -> list[int]:
    """Insert canonical series/issues and return the first issue id per series."""
    issue_ids = []
    for index in range(start, stop):
        thread_id = await raw.fetchval(
            "INSERT INTO threads "
            "(user_id,title,format,queue_position,issues_remaining,total_issues,status) "
            "VALUES ($1,$2,'Comic',$3,2,2,'active') RETURNING id",
            owner_id,
            f"Series {index + 1}",
            index + 1,
        )
        for position in (1, 2):
            issue_id = await raw.fetchval(
                "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                "VALUES ($1,$2,$3,'unread',NOW()) RETURNING id",
                thread_id,
                str(position),
                position,
            )
            if position == 1:
                issue_ids.append(int(issue_id))
    return issue_ids


async def _insert_list(
    raw: asyncpg.Connection,
    owner_id: int,
    name: str,
    issue_ids: list[int],
) -> int:
    """Insert one list and all entries with two set-based fixture statements."""
    list_id = await raw.fetchval(
        "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
        "VALUES ($1,$2,NULL,'loose',NOW(),NOW()) RETURNING id",
        owner_id,
        name,
    )
    await raw.execute(
        "INSERT INTO custom_cbl_entries "
        "(list_id,issue_id,position,created_at,is_checkpoint,"
        "checkpoint_target_issue_ids,gate,skipped) "
        "SELECT $1,issue_id,position::int,NOW(),false,'[]','none',false "
        "FROM UNNEST($2::int[]) WITH ORDINALITY AS entry(issue_id,position)",
        list_id,
        issue_ids,
    )
    return int(list_id)


async def _append_entries(
    raw: asyncpg.Connection,
    list_id: int,
    issue_ids: list[int],
    *,
    previous_count: int,
) -> None:
    """Grow an existing list with one set-based fixture statement."""
    await raw.execute(
        "INSERT INTO custom_cbl_entries "
        "(list_id,issue_id,position,created_at,is_checkpoint,"
        "checkpoint_target_issue_ids,gate,skipped) "
        "SELECT $1,issue_id,($2+position)::int,NOW(),false,'[]','none',false "
        "FROM UNNEST($3::int[]) WITH ORDINALITY AS entry(issue_id,position)",
        list_id,
        previous_count,
        issue_ids,
    )


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
        f"nested statement count grew: {small.db_nested_statements} -> {large.db_nested_statements}"
    )


@pytest.mark.asyncio
async def test_list_reading_lists_statements_do_not_grow_with_list_count() -> None:
    """GET /api/v2/reading-lists stays set-based across 5 and 200 lists."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rlln1")
        raw = await asyncpg.connect(url)
        try:
            issue_ids = await _seed_issue_ids(raw, owner_id, 0, 5)
            for index, issue_id in enumerate(issue_ids):
                await _insert_list(raw, owner_id, f"List {index + 1}", [issue_id])
            env = _run_env(token, "GET", LISTS_PATH)
            small_response, small = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-lists", "5-lists"
            )
            assert small_response.get("status") == 200, small_response
            small_body = small_response.get("body")
            assert isinstance(small_body, list) and len(small_body) == 5
            assert all(
                isinstance(item, dict) and item.get("issue_count") == 1 for item in small_body
            )

            new_issue_ids = await _seed_issue_ids(raw, owner_id, 5, 200)
            for offset, issue_id in enumerate(new_issue_ids, start=5):
                await _insert_list(raw, owner_id, f"List {offset + 1}", [issue_id])
            large_response, large = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-lists", "200-lists"
            )
            assert large_response.get("status") == 200, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, list) and len(large_body) == 200
            _assert_fixed_budget("GET", LISTS_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id} stays set-based across 5 and 200 entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rlgn1")
        raw = await asyncpg.connect(url)
        try:
            issue_ids = await _seed_issue_ids(raw, owner_id, 0, 200)
            list_id = await _insert_list(raw, owner_id, "Detail", issue_ids[:5])
            env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}")
            small_response, small = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-lists/{list_id}", "5-entries"
            )
            assert small_response.get("status") == 200, small_response
            small_body = small_response.get("body")
            assert isinstance(small_body, dict)
            assert small_body.get("id") == list_id and small_body.get("issue_count") == 5
            assert isinstance(small_body.get("entries"), list) and len(small_body["entries"]) == 5

            await _append_entries(raw, list_id, issue_ids[5:], previous_count=5)
            large_response, large = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-lists/{list_id}", "200-entries"
            )
            assert large_response.get("status") == 200, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
            assert isinstance(large_body.get("entries"), list) and len(large_body["entries"]) == 200
            _assert_fixed_budget("GET", LIST_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_list_reader_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id}/reader stays set-based across entry counts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rlrn1")
        raw = await asyncpg.connect(url)
        try:
            issue_ids = await _seed_issue_ids(raw, owner_id, 0, 200)
            list_id = await _insert_list(raw, owner_id, "Reader", issue_ids[:5])
            env = _run_env(token, "GET", f"/api/v2/reading-lists/{list_id}/reader")
            small_response, small = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-lists/{list_id}/reader", "5-entries"
            )
            assert small_response.get("status") == 200, small_response
            small_body = small_response.get("body")
            assert isinstance(small_body, dict)
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

            await _append_entries(raw, list_id, issue_ids[5:], previous_count=5)
            large_response, large = await measure_route_response(
                BINARY, env, engine, "GET /api/v2/reading-lists/{list_id}/reader", "200-entries"
            )
            assert large_response.get("status") == 200, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, dict)
            large_entries = large_body.get("entries")
            assert isinstance(large_entries, list) and len(large_entries) == 200
            _assert_fixed_budget("GET", READER_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_reading_list_statements_bounded_for_long_list() -> None:
    """Deleting 1-entry and 200-entry targets uses the same fixed SQL budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rldn1")
        raw = await asyncpg.connect(url)
        try:
            issue_ids = await _seed_issue_ids(raw, owner_id, 0, 200)
            small_id = await _insert_list(raw, owner_id, "Delete small", issue_ids[:1])
            small_env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{small_id}")
            small_response, small = await measure_route_response(
                BINARY, small_env, engine, "DELETE /api/v2/reading-lists/{list_id}", "1-entry"
            )
            assert small_response.get("status") == 204, small_response
            assert small_response.get("body") is None
            assert (
                await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", small_id)
                == 0
            )

            large_id = await _insert_list(raw, owner_id, "Delete large", issue_ids)
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", large_id
                )
                == 200
            )
            large_env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{large_id}")
            large_response, large = await measure_route_response(
                BINARY, large_env, engine, "DELETE /api/v2/reading-lists/{list_id}", "200-entries"
            )
            assert large_response.get("status") == 204, large_response
            assert large_response.get("body") is None
            assert (
                await raw.fetchval("SELECT count(*) FROM custom_cbl_lists WHERE id=$1", large_id)
                == 0
            )
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", large_id
                )
                == 0
            )
            _assert_fixed_budget("DELETE", LIST_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_reading_list_statements_respect_fixed_budget() -> None:
    """Creating 5-entry and 200-entry lists uses one set-based entry insert."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rlcn1")
        raw = await asyncpg.connect(url)
        try:
            issue_ids = await _seed_issue_ids(raw, owner_id, 0, 200)
            small_env = _run_env(
                token,
                "POST",
                LISTS_PATH,
                body={"name": "Small", "mode": "loose", "issue_ids": issue_ids[:5]},
            )
            small_response, small = await measure_route_response(
                BINARY, small_env, engine, "POST /api/v2/reading-lists", "5-entries"
            )
            assert small_response.get("status") == 201, small_response
            small_body = small_response.get("body")
            assert isinstance(small_body, dict)
            assert small_body.get("name") == "Small" and small_body.get("issue_count") == 5
            assert isinstance(small_body.get("entries"), list) and len(small_body["entries"]) == 5
            small_id = small_body.get("id")
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", small_id
                )
                == 5
            )

            large_env = _run_env(
                token,
                "POST",
                LISTS_PATH,
                body={"name": "Large", "mode": "loose", "issue_ids": issue_ids},
            )
            large_response, large = await measure_route_response(
                BINARY, large_env, engine, "POST /api/v2/reading-lists", "200-entries"
            )
            assert large_response.get("status") == 201, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
            assert isinstance(large_body.get("entries"), list) and len(large_body["entries"]) == 200
            large_id = large_body.get("id")
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", large_id
                )
                == 200
            )
            _assert_fixed_budget("POST", LISTS_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_reading_list_statements_respect_fixed_budget() -> None:
    """Replacing 200 entries with 5 and then 200 uses one set-based insert."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_id, token = await _create_owner(engine, "rlun1")
        raw = await asyncpg.connect(url)
        try:
            issue_ids = await _seed_issue_ids(raw, owner_id, 0, 200)
            list_id = await _insert_list(raw, owner_id, "Up", issue_ids)
            small_env = _run_env(
                token,
                "PUT",
                f"/api/v2/reading-lists/{list_id}",
                body={"name": "Up-small", "mode": "loose", "issue_ids": issue_ids[:5]},
            )
            small_response, small = await measure_route_response(
                BINARY, small_env, engine, "PUT /api/v2/reading-lists/{list_id}", "5-entries"
            )
            assert small_response.get("status") == 200, small_response
            small_body = small_response.get("body")
            assert isinstance(small_body, dict)
            assert small_body.get("name") == "Up-small" and small_body.get("issue_count") == 5
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id
                )
                == 5
            )

            large_env = _run_env(
                token,
                "PUT",
                f"/api/v2/reading-lists/{list_id}",
                body={"name": "Up-large", "mode": "loose", "issue_ids": issue_ids},
            )
            large_response, large = await measure_route_response(
                BINARY, large_env, engine, "PUT /api/v2/reading-lists/{list_id}", "200-entries"
            )
            assert large_response.get("status") == 200, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, dict)
            assert large_body.get("name") == "Up-large" and large_body.get("issue_count") == 200
            assert isinstance(large_body.get("entries"), list) and len(large_body["entries"]) == 200
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id
                )
                == 200
            )
            _assert_fixed_budget("PUT", LIST_PATH, small, large)
        finally:
            await raw.close()
    finally:
        await engine.dispose()
