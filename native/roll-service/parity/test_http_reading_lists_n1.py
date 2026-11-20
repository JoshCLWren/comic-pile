"""Measured SQL budget regressions for native v2 reading-list endpoints (#5149).

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

SECRET = "synthetic-native-reading-lists-n1-secret"
BINARY = str(cargo_example_path("http_reading_lists"))
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


def _assert_budget_and_no_growth(
    operation: tuple[str, str], small: int, large: int
) -> None:
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
            "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,"
            "checkpoint_target_issue_ids,gate,skipped) "
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


@pytest.mark.asyncio
async def test_list_reading_lists_statements_do_not_grow_with_list_count() -> None:
    """GET /api/v2/reading-lists must stay set-based across list counts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("GET", "/api/v2/reading-lists")
    try:
        username = f"rlln1_{uuid4().hex[:12]}"
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
                for position in (1, 2):
                    db.add(
                        Issue(
                            thread_id=thread.id,
                            issue_number=str(position),
                            position=position,
                            status="unread",
                        )
                    )
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_rows = await raw.fetch(
                "SELECT id FROM issues WHERE thread_id IN "
                "(SELECT id FROM threads WHERE user_id=$1) ORDER BY id",
                owner_id,
            )
            issue_ids = [row["id"] for row in issue_rows]
            for i in range(5):
                await _insert_list(raw, owner_id, f"List {i + 1}", [issue_ids[i]])
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-lists")
        small, small_delta, small_nested = await _measure(engine, env)
        assert small.get("status") == 200, small
        small_body = small.get("body")
        assert isinstance(small_body, list) and len(small_body) == 5
        assert [entry["issue_count"] for entry in small_body] == [1] * 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            existing = await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_lists WHERE user_id=$1", owner_id
            )
            # Add more threads/issues/lists up to 200 total lists.
            for i in range(int(existing), 200):
                _, new_issue_ids = await _insert_owned_thread(raw, owner_id, i)
                await _insert_list(raw, owner_id, f"List {i + 1}", [new_issue_ids[0]])
        finally:
            await raw.close()

        large, large_delta, large_nested = await _measure(engine, env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, list) and len(large_body) == 200
        assert [entry["issue_count"] for entry in large_body] == [1] * 200

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id} must stay set-based across entry counts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("GET", "/api/v2/reading-lists/{list_id}")
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
        small, small_delta, small_nested = await _measure(engine, env)
        assert small.get("status") == 200, small
        body = small.get("body")
        assert isinstance(body, dict)
        assert body.get("id") == list_id
        assert body.get("issue_count") == 5
        assert isinstance(body.get("entries"), list) and len(body["entries"]) == 5
        assert [entry["position"] for entry in body["entries"]] == [1, 2, 3, 4, 5]

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,"
                    "is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
                    list_id,
                    ids[0],
                    i,
                )
        finally:
            await raw.close()

        large, large_delta, large_nested = await _measure(engine, env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        large_entries = large_body.get("entries")
        assert isinstance(large_entries, list) and len(large_entries) == 200

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_list_reader_statements_do_not_grow_with_entry_count() -> None:
    """GET /api/v2/reading-lists/{id}/reader must stay set-based across entry counts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("GET", "/api/v2/reading-lists/{list_id}/reader")
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
        small, small_delta, small_nested = await _measure(engine, env)
        assert small.get("status") == 200, small
        body = small.get("body")
        assert isinstance(body, dict)
        assert body.get("list_id") == list_id
        assert body.get("execution_mode") == "option_e"
        entries = body.get("entries")
        assert isinstance(entries, list) and len(entries) == 5
        assert all(
            entry.get("availability")
            in {"available", "later", "blocked", "read", "excluded", "inactive"}
            for entry in entries
        )

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                await raw.execute(
                    "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,"
                    "is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                    "VALUES ($1,$2,$3,NOW(),false,'[]','none',false)",
                    list_id,
                    ids[0],
                    i,
                )
        finally:
            await raw.close()

        large, large_delta, large_nested = await _measure(engine, env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict)
        large_entries = large_body.get("entries")
        assert isinstance(large_entries, list) and len(large_entries) == 200

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_reading_list_statements_bounded() -> None:
    """DELETE /api/v2/reading-lists/{id} must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("DELETE", "/api/v2/reading-lists/{list_id}")
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
            small_issue_ids = []
            for i in range(205):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                small_issue_ids.append(ids[0])
            small_id = await _insert_list(raw, owner_id, "Delete small", small_issue_ids[:1])
            large_id = await _insert_list(raw, owner_id, "Delete large", small_issue_ids[1:201])
        finally:
            await raw.close()

        small_env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{small_id}")
        small, small_delta, small_nested = await _measure(engine, small_env)
        assert small.get("status") == 204, small
        assert small.get("body") is None

        large_env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{large_id}")
        large, large_delta, large_nested = await _measure(engine, large_env)
        assert large.get("status") == 204, large
        assert large.get("body") is None

        raw = await asyncpg.connect(url)
        try:
            for list_id in (small_id, large_id):
                remaining = await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_lists WHERE id=$1", list_id
                )
                assert remaining == 0, f"reading list {list_id} was not deleted"
                entries = await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id
                )
                assert entries == 0, f"reading list {list_id} entries survived the delete"
        finally:
            await raw.close()

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """POST /api/v2/reading-lists must stay within its budget for 5 and 200 entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("POST", "/api/v2/reading-lists")
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

        body_small = json.dumps(
            {"name": "Small", "mode": "loose", "issue_ids": issue_ids_small}
        )
        env = _run_env(token, "POST", "/api/v2/reading-lists", body=body_small)
        small, small_delta, small_nested = await _measure(engine, env)
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

        body_large = json.dumps(
            {"name": "Large", "mode": "loose", "issue_ids": issue_ids_large}
        )
        large_env = _run_env(token, "POST", "/api/v2/reading-lists", body=body_large)
        large, large_delta, large_nested = await _measure(engine, large_env)
        assert large.get("status") == 201, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200

        raw = await asyncpg.connect(url)
        try:
            for list_id, expected in ((small_body["id"], 5), (large_body["id"], 200)):
                stored = await raw.fetchval(
                    "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id
                )
                assert stored == expected, f"list {list_id} stored {stored} of {expected} entries"
        finally:
            await raw.close()

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_reading_list_statements_do_not_grow_with_entry_count() -> None:
    """PUT /api/v2/reading-lists/{id} must stay within its budget for 5 and 200 entries."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("PUT", "/api/v2/reading-lists/{list_id}")
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
            list_id = await _insert_list(raw, owner_id, "Update", issue_ids_small[:3])
        finally:
            await raw.close()

        body_small = json.dumps(
            {"name": "Update small", "mode": "loose", "issue_ids": issue_ids_small}
        )
        env = _run_env(token, "PUT", f"/api/v2/reading-lists/{list_id}", body=body_small)
        small, small_delta, small_nested = await _measure(engine, env)
        assert small.get("status") == 200, small
        small_body = small.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("name") == "Update small"
        assert small_body.get("issue_count") == 5

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids_large = []
            for i in range(5, 205):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                issue_ids_large.append(ids[0])
            full_ids = issue_ids_small + issue_ids_large
        finally:
            await raw.close()

        body_large = json.dumps(
            {"name": "Update large", "mode": "loose", "issue_ids": full_ids[:200]}
        )
        large_env = _run_env(token, "PUT", f"/api/v2/reading-lists/{list_id}", body=body_large)
        large, large_delta, large_nested = await _measure(engine, large_env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200

        raw = await asyncpg.connect(url)
        try:
            stored = await raw.fetchval(
                "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1", list_id
            )
            assert stored == 200, f"updated list stored {stored} of 200 entries"
        finally:
            await raw.close()

        _assert_budget_and_no_growth(operation, small_delta, large_delta)
        _assert_no_nested_growth(operation, small_nested, large_nested)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_injected_extra_query_and_n_plus_1_fail_reading_list_budget() -> None:
    """An added query and an N+1 loop must fail the reading-list budget guard."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    operation = ("GET", "/api/v2/reading-lists")
    try:
        username = f"rlxn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            _, ids = await _insert_owned_thread(raw, owner_id, 0)
            await _insert_list(raw, owner_id, "Injected", [ids[0]])
        finally:
            await raw.close()

        env = _run_env(token, "GET", "/api/v2/reading-lists")
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
