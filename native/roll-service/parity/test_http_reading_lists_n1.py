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
    StatementBreakdown,
    assert_no_statement_growth,
    assert_statement_budget,
    cargo_example_path,
    db_statement_breakdown,
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


async def _measure_route(
    engine: AsyncEngine, env: dict[str, str]
) -> tuple[dict[str, object], StatementBreakdown]:
    """Run one real HTTP request and return its isolated SQL statement split."""
    before = await db_statement_breakdown(engine)
    response, _, _, _ = await run_rust_example(BINARY, env)
    after = await db_statement_breakdown(engine)
    assert before is not None and after is not None, (
        "pg_stat_statements.track=all and the administrative URL are required"
    )
    measured = StatementBreakdown(
        application=after.application - before.application,
        transaction_control=after.transaction_control - before.transaction_control,
        runtime_overhead=after.runtime_overhead - before.runtime_overhead,
        nested=after.nested - before.nested,
    )
    print(f"reading-list statements={measured}", flush=True)
    return response, measured


def _assert_fixed_route_budget(
    method: str,
    path: str,
    small: StatementBreakdown,
    large: StatementBreakdown,
) -> None:
    """Enforce absolute, component-level, nested, and growth budgets."""
    assert_statement_budget(method, path, small, large, require_maximum=True)
    assert_no_statement_growth(method, path, small, large)


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
        small, small_statements = await _measure_route(engine, env)
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

        large, large_statements = await _measure_route(engine, env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, list) and len(large_body) == 200

        _assert_fixed_route_budget(
            "GET", "/api/v2/reading-lists", small_statements, large_statements
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
        small, small_statements = await _measure_route(engine, env)
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

        large, large_statements = await _measure_route(engine, env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        assert len(large_body.get("entries", [])) == 200

        _assert_fixed_route_budget(
            "GET", "/api/v2/reading-lists/{list_id}", small_statements, large_statements
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
        small, small_statements = await _measure_route(engine, env)
        assert small.get("status") == 200, small
        body = small.get("body")
        assert isinstance(body, dict)
        assert body.get("list_id") == list_id
        assert body.get("execution_mode") == "option_e"
        entries = body.get("entries")
        assert isinstance(entries, list) and len(entries) == 5
        assert all(
            e.get("availability")
            in {"available", "later", "blocked", "read", "excluded", "inactive"}
            for e in entries
        )

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

        large, large_statements = await _measure_route(engine, env)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict)
        assert len(large_body.get("entries", [])) == 200

        _assert_fixed_route_budget(
            "GET",
            "/api/v2/reading-lists/{list_id}/reader",
            small_statements,
            large_statements,
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

        async def _seed_one() -> int:
            raw = await asyncpg.connect(url)
            try:
                owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
                _, ids = await _insert_owned_thread(raw, owner_id, int(uuid4().int % 100000))
                return await _insert_list(raw, owner_id, f"D-{uuid4().hex[:6]}", [ids[0]])
            finally:
                await raw.close()

        small_id = await _seed_one()
        env = _run_env(token, "DELETE", f"/api/v2/reading-lists/{small_id}")
        small, small_statements = await _measure_route(engine, env)
        assert small.get("status") == 204, small
        assert small.get("body") is None

        # The large target itself contains many entries. Growing only unrelated
        # lists would miss a query-per-entry deletion regression.
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            long_issue_ids: list[int] = []
            for i in range(5, 200):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                long_issue_ids.append(ids[0])
            large_id = await _insert_list(raw, owner_id, "Long delete", long_issue_ids)
        finally:
            await raw.close()

        env2 = _run_env(token, "DELETE", f"/api/v2/reading-lists/{large_id}")
        large, large_statements = await _measure_route(engine, env2)
        assert large.get("status") == 204, large
        assert large.get("body") is None

        _assert_fixed_route_budget(
            "DELETE", "/api/v2/reading-lists/{list_id}", small_statements, large_statements
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

        body_small = json.dumps(
            {
                "name": "Small",
                "mode": "loose",
                "issue_ids": issue_ids_small,
                "checkpoint_issue_ids": [issue_ids_small[1]],
                "checkpoint_targets": {str(issue_ids_small[1]): [issue_ids_small[2]]},
                "entry_intents": {
                    str(issue_ids_small[0]): {"gate": "none", "skipped": True},
                    str(issue_ids_small[1]): {"gate": "none", "skipped": False},
                },
            }
        )
        env = _run_env(token, "POST", "/api/v2/reading-lists", body=body_small)
        small, small_statements = await _measure_route(engine, env)
        assert small.get("status") == 201, small
        small_body = small.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("name") == "Small"
        assert small_body.get("issue_count") == 5
        small_entries = small_body.get("entries")
        assert isinstance(small_entries, list) and len(small_entries) == 5
        assert small_entries[0]["skipped"] is True
        assert small_entries[1]["is_checkpoint"] is True
        assert small_entries[1]["checkpoint_target_issue_ids"] == [issue_ids_small[2]]

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
        _, _, before2 = await db_counters(engine)
        large, _, _, _ = await run_rust_example(BINARY, env2)
        assert large.get("status") == 201, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        _, _, after2 = await db_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None

        assert small_delta is not None and large_delta is not None
        assert_declared_budget("POST", "/api/v2/reading-lists", small_delta, large_delta)
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
        _, _, before = await db_counters(engine)
        small, _, _, _ = await run_rust_example(BINARY, env)
        assert small.get("status") == 200, small
        small_body = small.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("name") == "Up-small"
        assert small_body.get("issue_count") == 5
        _, _, after = await db_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None

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
        _, _, before2 = await db_counters(engine)
        large, _, _, _ = await run_rust_example(BINARY, env2)
        assert large.get("status") == 200, large
        large_body = large.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue_count") == 200
        _, _, after2 = await db_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None

        assert small_delta is not None and large_delta is not None
        assert_declared_budget("PUT", "/api/v2/reading-lists/{list_id}", small_delta, large_delta)
    finally:
        await engine.dispose()
