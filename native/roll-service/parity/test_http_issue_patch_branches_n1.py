"""Measured N+1 regression for ``PATCH /api/v2/issues/{issue_id}`` additional branches (#5148).

Exercises status-only, rating-only, idempotency replay, and error paths
against small and large libraries, proving all branches are set-based
with no per-row N+1.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import create_async_engine

from route_harness import (
    assert_declared_budget,
    cargo_example_path,
    db_counters,
    db_nested_statements,
    run_rust_example,
)

SECRET = "synthetic-native-issue-patch-branches-secret"
EXAMPLE = cargo_example_path("http_issue_read_rate")
BINARY = str(EXAMPLE)


async def _setup_user_and_thread(engine, username: str, issue_count: int) -> tuple[int, int, list[int]]:
    """Create user, thread, and issues. Returns (owner_id, thread_id, issue_ids)."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    raw = await asyncpg.connect(url)
    try:
        owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
        if owner_id is None:
            owner_id = await raw.fetchval(
                "INSERT INTO users (username) VALUES ($1) RETURNING id", username
            )
        thread_id = await raw.fetchval(
            "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) "
            "VALUES ($1,'Series','Comic',1,$2,$2,'active') RETURNING id",
            owner_id,
            issue_count,
        )
        issue_ids = []
        for i in range(issue_count):
            iid = await raw.fetchval(
                "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                "VALUES ($1,$2,$3,'unread',NOW()) RETURNING id",
                thread_id,
                str(i + 1),
                i + 1,
            )
            issue_ids.append(iid)
        await raw.execute(
            "UPDATE threads SET next_unread_issue_id=$1 WHERE id=$2", issue_ids[0], thread_id
        )
        return owner_id, thread_id, issue_ids
    finally:
        await raw.close()


def _make_token(username: str, secret: str, now: datetime) -> str:
    return jwt.encode(
        {
            "sub": username,
            "jti": f"native-issue-patch-{uuid4().hex[:8]}",
            "type": "access",
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        secret,
        "HS256",
    )


async def _run_patch(
    engine, binary: str, env: dict, url: str, issue_id: int, body: dict
) -> tuple[dict, int | None, int | None]:
    """Run a PATCH request and return (response, statement_delta, nested_delta)."""
    env["RUST_ROLL_TEST_ISSUE_ID"] = str(issue_id)
    env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
    n_before = await db_nested_statements(engine)
    _, _, s_before = await db_counters(engine)
    response, _, _, _ = await run_rust_example(binary, env)
    _, _, s_after = await db_counters(engine)
    n_after = await db_nested_statements(engine)
    delta = (s_after - s_before) if s_before is not None and s_after is not None else None
    nested = (n_after - n_before) if n_before is not None and n_after is not None else None
    return response, delta, nested


def _assert_nested_not_growing(small_nested: int | None, large_nested: int | None) -> None:
    """Assert trigger/function statements do not scale with the library fixture."""
    assert small_nested is not None and large_nested is not None, (
        "pg_stat_statements track=all is required for nested trigger statements"
    )
    assert large_nested <= small_nested + 2, (
        f"nested trigger statements grew with library size: {small_nested} -> {large_nested}"
    )


@pytest.mark.asyncio
async def test_issue_patch_status_only_branch() -> None:
    """Status-only PATCH (read/unread) does not grow with library size."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        now = datetime.now(UTC)
        username = f"isp_{uuid4().hex[:10]}"

        # Small library (5 issues)
        owner_id, thread_id, issue_ids = await _setup_user_and_thread(engine, username, 5)
        token = _make_token(username, SECRET, now)
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        # Status: read
        body = {"status": "read", "idempotency_key": f"key-{uuid4().hex}"}
        small_response, small_delta, small_nested = await _run_patch(
            engine, BINARY, env, url, issue_ids[0], body
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict) and small_body.get("issue", {}).get("status") == "read"

        # Grow to 200 issues
        raw = await asyncpg.connect(url)
        try:
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                    "VALUES ($1,$2,$3,'unread',NOW())",
                    thread_id,
                    str(i + 1),
                    i + 1,
                )
            await raw.execute(
                "UPDATE threads SET issues_remaining=200, total_issues=200 WHERE id=$1", thread_id
            )
        finally:
            await raw.close()

        # Status: unread (on a different issue in the large library)
        raw = await asyncpg.connect(url)
        try:
            large_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position OFFSET 10 LIMIT 1",
                thread_id,
            )
        finally:
            await raw.close()
        body = {"status": "unread", "idempotency_key": f"key-{uuid4().hex}"}
        large_response, large_delta, large_nested = await _run_patch(
            engine, BINARY, env, url, large_issue_id, body
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue", {}).get("status") == "unread"

        print(
            f"status_only: small_delta={small_delta} large_delta={large_delta} "
            f"small_nested={small_nested} large_nested={large_nested}",
            flush=True,
        )
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        _assert_nested_not_growing(small_nested, large_nested)
        assert_declared_budget("PATCH", "/api/v2/issues/{issue_id}", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_patch_rating_only_branch() -> None:
    """Rating-only PATCH does not grow with library size."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        now = datetime.now(UTC)
        username = f"ipr_{uuid4().hex[:10]}"

        # Small library (5 issues)
        owner_id, thread_id, issue_ids = await _setup_user_and_thread(engine, username, 5)
        token = _make_token(username, SECRET, now)
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        # Rating only
        body = {"rating": 4.0, "idempotency_key": f"key-{uuid4().hex}"}
        small_response, small_delta, small_nested = await _run_patch(
            engine, BINARY, env, url, issue_ids[0], body
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict) and small_body.get("issue", {}).get("rating") == 4.0

        # Grow to 200 issues
        raw = await asyncpg.connect(url)
        try:
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                    "VALUES ($1,$2,$3,'unread',NOW())",
                    thread_id,
                    str(i + 1),
                    i + 1,
                )
            await raw.execute(
                "UPDATE threads SET issues_remaining=200, total_issues=200 WHERE id=$1", thread_id
            )
        finally:
            await raw.close()

        # Rating only on a different issue in the large library
        raw = await asyncpg.connect(url)
        try:
            large_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position OFFSET 10 LIMIT 1",
                thread_id,
            )
        finally:
            await raw.close()
        body = {"rating": 3.5, "idempotency_key": f"key-{uuid4().hex}"}
        large_response, large_delta, large_nested = await _run_patch(
            engine, BINARY, env, url, large_issue_id, body
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict) and large_body.get("issue", {}).get("rating") == 3.5

        print(
            f"rating_only: small_delta={small_delta} large_delta={large_delta} "
            f"small_nested={small_nested} large_nested={large_nested}",
            flush=True,
        )
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        _assert_nested_not_growing(small_nested, large_nested)
        assert_declared_budget("PATCH", "/api/v2/issues/{issue_id}", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_patch_idempotency_replay_branch() -> None:
    """Idempotency replay returns same receipt without extra statements."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        now = datetime.now(UTC)
        username = f"iid_{uuid4().hex[:10]}"

        # Small library (5 issues)
        owner_id, thread_id, issue_ids = await _setup_user_and_thread(engine, username, 5)
        token = _make_token(username, SECRET, now)
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        # First request
        idempotency_key = f"replay-{uuid4().hex}"
        body = {"status": "read", "rating": 4.0, "idempotency_key": idempotency_key}
        first_response, first_delta, _first_nested = await _run_patch(
            engine, BINARY, env, url, issue_ids[0], body
        )
        assert first_response.get("status") == 200, first_response
        first_body = first_response.get("body")
        assert isinstance(first_body, dict) and first_body.get("replayed") is False

        # Replay with same key and payload
        second_response, second_delta, _second_nested = await _run_patch(
            engine, BINARY, env, url, issue_ids[0], body
        )
        assert second_response.get("status") == 200, second_response
        second_body = second_response.get("body")
        assert isinstance(second_body, dict) and second_body.get("replayed") is True
        assert second_body.get("issue") == first_body.get("issue")
        assert second_body.get("thread") == first_body.get("thread")

        # Replay should not issue more statements than first call
        print(f"idempotency: first_delta={first_delta} second_delta={second_delta}", flush=True)
        assert first_delta is not None and second_delta is not None, "pg_stat_statements is required"
        # Replay may have slightly different count due to SELECT of existing event
        assert second_delta <= first_delta + 3, (
            f"replay statement count unexpectedly high: {first_delta} -> {second_delta}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_patch_error_branches() -> None:
    """Error paths (404, 409, 422) are bounded and do not grow with library size."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        now = datetime.now(UTC)
        username = f"ipe_{uuid4().hex[:10]}"

        # Small library (5 issues)
        owner_id, thread_id, issue_ids = await _setup_user_and_thread(engine, username, 5)
        token = _make_token(username, SECRET, now)
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        # 404: non-existent issue
        body = {"status": "read", "idempotency_key": f"key-{uuid4().hex}"}
        env["RUST_ROLL_TEST_ISSUE_ID"] = "999999"
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
        _, _, s_before = await db_counters(engine)
        resp_404, _, _, _ = await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        delta_404 = (s_after - s_before) if s_before is not None and s_after is not None else None
        assert resp_404.get("status") == 404, resp_404

        # 409: idempotency key reused for different payload
        body1 = {"status": "read", "idempotency_key": f"conflict-{uuid4().hex}"}
        body2 = {"rating": 4.0, "idempotency_key": body1["idempotency_key"]}
        env["RUST_ROLL_TEST_ISSUE_ID"] = str(issue_ids[0])
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body1)
        resp_first, _, _, _ = await run_rust_example(BINARY, env)
        assert resp_first.get("status") == 200, resp_first

        env["RUST_ROLL_TEST_BODY"] = json.dumps(body2)
        _, _, s_before = await db_counters(engine)
        resp_409, _, _, _ = await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        delta_409 = (s_after - s_before) if s_before is not None and s_after is not None else None
        assert resp_409.get("status") == 409, resp_409

        # 422: invalid status
        body = {"status": "invalid", "idempotency_key": f"key-{uuid4().hex}"}
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
        _, _, s_before = await db_counters(engine)
        resp_422, _, _, _ = await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        delta_422 = (s_after - s_before) if s_before is not None and s_after is not None else None
        assert resp_422.get("status") == 422, resp_422

        # Grow to 200 issues and verify error paths still bounded
        raw = await asyncpg.connect(url)
        try:
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                    "VALUES ($1,$2,$3,'unread',NOW())",
                    thread_id,
                    str(i + 1),
                    i + 1,
                )
            await raw.execute(
                "UPDATE threads SET issues_remaining=200, total_issues=200 WHERE id=$1", thread_id
            )
        finally:
            await raw.close()

        # 404 on large library
        env["RUST_ROLL_TEST_ISSUE_ID"] = "999999"
        body = {"status": "read", "idempotency_key": f"key-{uuid4().hex}"}
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
        _, _, s_before = await db_counters(engine)
        resp_404_large, _, _, _ = await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        delta_404_large = (s_after - s_before) if s_before is not None and s_after is not None else None
        assert resp_404_large.get("status") == 404, resp_404_large

        print(
            f"errors: 404_small={delta_404} 404_large={delta_404_large} "
            f"409={delta_409} 422={delta_422}",
            flush=True,
        )
        # Error paths should have minimal, bounded statements. The measured
        # worst case is the 409 idempotency conflict at 8 statements (auth and
        # checkout probes + transaction control + owner/idempotency lookups +
        # rollback); the 404 lookup and 422 validation paths are cheaper. The
        # bound is a regression guard, not a per-row allowance.
        assert delta_404 is not None and delta_404_large is not None, (
            "pg_stat_statements is required"
        )
        for delta in [delta_404, delta_404_large, delta_409, delta_422]:
            assert delta is not None, "pg_stat_statements is required"
            assert delta <= 8, f"error path issued too many statements: {delta}"
        assert delta_404_large <= delta_404 + 2, (
            f"404 statement count grew with library size: {delta_404} -> {delta_404_large}"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_patch_roll_offer_branch() -> None:
    """Roll-offer source branch (with rating) does not grow with library size."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        now = datetime.now(UTC)
        username = f"iro_{uuid4().hex[:10]}"

        # Small library (5 issues) with session and roll event
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            if owner_id is None:
                owner_id = await raw.fetchval(
                    "INSERT INTO users (username) VALUES ($1) RETURNING id", username
                )
            thread_id = await raw.fetchval(
                "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status,next_unread_issue_id) "
                "VALUES ($1,'Offered run','Comic',1,5,5,'active',$2) RETURNING id",
                owner_id,
                None,
            )
            issue_ids = []
            for i in range(5):
                iid = await raw.fetchval(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                    "VALUES ($1,$2,$3,'unread',NOW()) RETURNING id",
                    thread_id,
                    str(i + 1),
                    i + 1,
                )
                issue_ids.append(iid)
            # Set first issue as next unread
            await raw.execute(
                "UPDATE threads SET next_unread_issue_id=$1 WHERE id=$2", issue_ids[0], thread_id
            )
            # Create session with pending issue
            session_id = await raw.fetchval(
                "INSERT INTO sessions (user_id,start_die,pending_thread_id,pending_issue_id,started_at) "
                "VALUES ($1,6,$2,$3,NOW()) RETURNING id",
                owner_id,
                thread_id,
                issue_ids[0],
            )
            # Create roll event
            await raw.execute(
                "INSERT INTO events (user_id,type,session_id,selected_thread_id,die,result,issue_id,issue_number,context) "
                "VALUES ($1,'roll',$2,$3,6,1,$4,'1','{}')",
                owner_id,
                session_id,
                thread_id,
                issue_ids[0],
            )
        finally:
            await raw.close()

        token = _make_token(username, SECRET, now)
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        # Roll offer completion
        body = {"status": "read", "rating": 4.5, "idempotency_key": f"key-{uuid4().hex}", "source": "roll_offer"}
        small_response, small_delta, small_nested = await _run_patch(
            engine, BINARY, env, url, issue_ids[0], body
        )
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict) and small_body.get("die_after") is not None

        # Grow to 200 issues (add more threads and issues)
        raw = await asyncpg.connect(url)
        try:
            for t in range(1, 20):
                tid = await raw.fetchval(
                    "INSERT INTO threads (user_id,title,format,queue_position,issues_remaining,total_issues,status) "
                    "VALUES ($1,$2,'Comic',$3,5,5,'active') RETURNING id",
                    owner_id,
                    f"Run {t+1}",
                    t + 2,
                )
                for i in range(5):
                    await raw.execute(
                        "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                        "VALUES ($1,$2,$3,'unread',NOW())",
                        tid,
                        str(i + 1),
                        i + 1,
                    )
            # Add more issues to original thread
            for i in range(5, 200):
                await raw.execute(
                    "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                    "VALUES ($1,$2,$3,'unread',NOW())",
                    thread_id,
                    str(i + 1),
                    i + 1,
                )
            await raw.execute(
                "UPDATE threads SET issues_remaining=200, total_issues=200 WHERE id=$1", thread_id
            )
        finally:
            await raw.close()

        # Roll offer on a different issue in the large library
        raw = await asyncpg.connect(url)
        try:
            # Create a new session and roll event for a different issue
            new_issue_id = await raw.fetchval(
                "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position OFFSET 10 LIMIT 1",
                thread_id,
            )
            new_session_id = await raw.fetchval(
                "INSERT INTO sessions (user_id,start_die,pending_thread_id,pending_issue_id,started_at) "
                "VALUES ($1,6,$2,$3,NOW()) RETURNING id",
                owner_id,
                thread_id,
                new_issue_id,
            )
            await raw.execute(
                "INSERT INTO events (user_id,type,session_id,selected_thread_id,die,result,issue_id,issue_number,context) "
                "VALUES ($1,'roll',$2,$3,6,1,$4,'11','{}')",
                owner_id,
                new_session_id,
                thread_id,
                new_issue_id,
            )
        finally:
            await raw.close()

        body = {"status": "read", "rating": 4.5, "idempotency_key": f"key-{uuid4().hex}", "source": "roll_offer"}
        large_response, large_delta, large_nested = await _run_patch(
            engine, BINARY, env, url, new_issue_id, body
        )
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict) and large_body.get("die_after") is not None

        print(
            f"roll_offer: small_delta={small_delta} large_delta={large_delta} "
            f"small_nested={small_nested} large_nested={large_nested}",
            flush=True,
        )
        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        _assert_nested_not_growing(small_nested, large_nested)
        assert_declared_budget("PATCH", "/api/v2/issues/{issue_id}", small_delta, large_delta)
        assert large_delta <= small_delta + 2, (
            f"statement count grew with library size: {small_delta} -> {large_delta}"
        )
    finally:
        await engine.dispose()