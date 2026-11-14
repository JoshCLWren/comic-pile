"""Shared canonical-schema fixtures for isolated HTTP SQL-budget parity (#4988).

Each route measurement seeds the smallest realistic reader state through the
DML-only ``roll_test_dml`` role, invokes the exact native HTTP method/path with
the generic ``http_route`` example, and snapshots ``pg_stat_statements`` before
and after. The fixtures never create schema objects; ``conftest.py`` owns the
canonical Alembic schema and per-test truncation.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import asyncpg
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncEngine

from route_harness import (
    cargo_example_path,
    db_counters,
    db_nested_statements,
    run_rust_example,
)

SECRET = "synthetic-native-route-parity-secret"
#: Password epoch stamped on every seeded reader; minted access tokens match it.
SEEDED_EPOCH = 1_767_225_600
BINARY = str(cargo_example_path("http_route"))


def parity_url() -> str:
    """Return the restricted DSN every parity fixture must use."""
    return os.environ["RUST_ROLL_PARITY_DATABASE_URL"]


def access_token(username: str, *, jti: str | None = None, epoch: int = SEEDED_EPOCH) -> str:
    """Mint an access token the native router accepts."""
    return jwt.encode(
        {
            "sub": username,
            "jti": jti or f"jti-{uuid4().hex}",
            "type": "access",
            "pc": epoch,
            "exp": 4_102_444_800,
        },
        SECRET,
        algorithm="HS256",
    )


def refresh_token(username: str, *, jti: str, epoch: int = SEEDED_EPOCH) -> str:
    """Mint a refresh token sharing the access-token claims shape."""
    return jwt.encode(
        {
            "sub": username,
            "jti": jti,
            "type": "refresh",
            "pc": epoch,
            "exp": 4_102_444_800,
        },
        SECRET,
        algorithm="HS256",
    )


def reset_digest(raw_token: str) -> str:
    """Return the SHA-256 hex digest the reset service stores."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Reader:
    """One seeded owner plus a bearer token for that owner."""

    id: int
    username: str
    token: str


def route_env(
    method: str,
    uri: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    cookie: str | None = None,
    csrf: str | None = None,
    repeat: int | None = None,
) -> dict[str, str]:
    """Build the environment consumed by the generic ``http_route`` example."""
    env = {
        **os.environ,
        "RUST_ROLL_TEST_METHOD": method,
        "RUST_ROLL_TEST_URI": uri,
        "RUST_ROLL_DATABASE_URL": parity_url(),
        "RUST_ROLL_JWT_SECRET": SECRET,
    }
    if token is not None:
        env["RUST_ROLL_TEST_TOKEN"] = token
    if body is not None:
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
    if cookie is not None:
        env["RUST_ROLL_TEST_COOKIE"] = cookie
    if csrf is not None:
        env["RUST_ROLL_TEST_CSRF"] = csrf
    if repeat is not None:
        env["RUST_ROLL_TEST_REPEAT"] = str(repeat)
    return env


@dataclass(frozen=True)
class MeasuredRoute:
    """One route invocation plus its measured statement deltas."""

    result: dict[str, Any]
    statements: int | None
    nested_statements: int | None


async def measure(
    engine: AsyncEngine,
    method: str,
    uri: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    repeat: int | None = None,
) -> MeasuredRoute:
    """Run one route and return its response plus measured statement delta."""
    env = route_env(method, uri, token=token, body=body, repeat=repeat)
    _, _, before = await db_counters(engine)
    nested_before = await db_nested_statements(engine)
    result, _, _, _ = await run_rust_example(BINARY, env)
    _, _, after = await db_counters(engine)
    nested_after = await db_nested_statements(engine)
    statements = (
        after - before if before is not None and after is not None else None
    )
    nested = (
        nested_after - nested_before
        if nested_before is not None and nested_after is not None
        else None
    )
    print(
        f"route={method} {uri} status={result.get('status')} "
        f"statements={statements} nested={nested}",
        flush=True,
    )
    return MeasuredRoute(result=result, statements=statements, nested_statements=nested)


async def seed_reader(
    connection: asyncpg.Connection,
    *,
    username: str | None = None,
    email: str | None = None,
    password_epoch: int = SEEDED_EPOCH,
) -> Reader:
    """Create one reader with a matching bearer token."""
    name = username or f"route_{uuid4().hex[:16]}"
    address = email or f"{name}@example.invalid"
    user_id = await connection.fetchval(
        "INSERT INTO users (username, email, password_hash, is_admin, "
        "password_changed_at, created_at) "
        "VALUES ($1, $2, NULL, false, to_timestamp($3), NOW()) RETURNING id",
        name,
        address,
        float(password_epoch),
    )
    return Reader(id=user_id, username=name, token=access_token(name))


@dataclass
class SeededSeries:
    """One owned thread with ordered unread issues."""

    thread_id: int
    issue_ids: list[int] = field(default_factory=list)


async def seed_series(
    connection: asyncpg.Connection,
    user_id: int,
    *,
    title: str = "Parity Series",
    queue_position: int = 1,
    issue_numbers: tuple[str, ...] = ("1", "2"),
    status: str = "active",
) -> SeededSeries:
    """Insert one thread and its ordered issues using the canonical schema."""
    thread_id = await connection.fetchval(
        "INSERT INTO threads (user_id, title, format, queue_position, "
        "issues_remaining, total_issues, status, created_at, "
        "queue_position_is_manual, is_blocked, is_test, manual_creator_credits) "
        "VALUES ($1, $2, 'Comic', $3, $4, $4, $5, NOW(), false, false, false, '[]'::json) "
        "RETURNING id",
        user_id,
        title,
        queue_position,
        len(issue_numbers),
        status,
    )
    issue_ids: list[int] = []
    for position, number in enumerate(issue_numbers, start=1):
        issue_id = await connection.fetchval(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) "
            "VALUES ($1, $2, $3, 'unread', NOW()) RETURNING id",
            thread_id,
            number,
            position,
        )
        issue_ids.append(issue_id)
    await connection.execute(
        "UPDATE threads SET next_unread_issue_id = $1 WHERE id = $2",
        issue_ids[0],
        thread_id,
    )
    return SeededSeries(thread_id=thread_id, issue_ids=issue_ids)


async def seed_list(
    connection: asyncpg.Connection,
    user_id: int,
    issue_ids: list[int],
    *,
    name: str = "Parity List",
    mode: str = "loose",
) -> int:
    """Insert one owned Reading List with ordered entries."""
    list_id = await connection.fetchval(
        "INSERT INTO custom_cbl_lists "
        "(user_id, name, description, mode, created_at, updated_at, "
        "overlap_decisions_updated_at) "
        "VALUES ($1, $2, NULL, $3, NOW(), NOW(), NOW()) RETURNING id",
        user_id,
        name,
        mode,
    )
    for position, issue_id in enumerate(issue_ids, start=1):
        await connection.execute(
            "INSERT INTO custom_cbl_entries "
            "(list_id, issue_id, position, created_at, is_checkpoint, "
            "checkpoint_target_issue_ids, gate, skipped) "
            "VALUES ($1, $2, $3, NOW(), false, '[]'::json, 'none', false)",
            list_id,
            issue_id,
            position,
        )
    return list_id


async def seed_plan(
    connection: asyncpg.Connection,
    user_id: int,
    *,
    name: str = "Parity Plan",
    list_id: int | None = None,
    issue_ids: list[int] | None = None,
) -> int:
    """Insert one continuity plan, optionally linked to a Reading List."""
    plan_id = await connection.fetchval(
        "INSERT INTO continuity_plans "
        "(user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at) "
        "VALUES ($1, $2, 'informational', '[]'::json, '[]'::json, NOW(), NOW()) RETURNING id",
        user_id,
        name,
    )
    for position, issue_id in enumerate(issue_ids or [], start=1):
        await connection.execute(
            "INSERT INTO reading_plan_issues "
            "(plan_id, occurrence_id, issue_id, lane_id, display_position, "
            "label, is_checkpoint) "
            "VALUES ($1, $2, $3, 'main', $4, NULL, false)",
            plan_id,
            f"parity-{position}",
            issue_id,
            position,
        )
    if list_id is not None:
        await connection.execute(
            "INSERT INTO reading_plan_sources "
            "(plan_id, raw_source_path, custom_cbl_list_id, adopted_at, recorded_at) "
            "VALUES ($1, $2, $3, NOW(), NOW())",
            plan_id,
            f"parity/{plan_id}.cbl",
            list_id,
        )
    return plan_id


async def seed_dependency(
    connection: asyncpg.Connection, source_issue_id: int, target_issue_id: int
) -> int:
    """Insert one reader-authored prerequisite edge."""
    return await connection.fetchval(
        "INSERT INTO dependencies "
        "(source_issue_id, target_issue_id, origin, classification, provenance, created_at) "
        "VALUES ($1, $2, 'reader', 'A', 'parity fixture', NOW()) RETURNING id",
        source_issue_id,
        target_issue_id,
    )


async def seed_reset_token(
    connection: asyncpg.Connection, user_id: int, raw_token: str
) -> None:
    """Store one unused, unexpired password reset digest for ``user_id``."""
    await connection.execute(
        "INSERT INTO password_reset_tokens "
        "(user_id, token_digest, expires_at, created_at) "
        "VALUES ($1, $2, NOW() + INTERVAL '30 minutes', NOW())",
        user_id,
        reset_digest(raw_token),
    )


def assert_status(result: dict[str, Any], *expected: int) -> dict[str, Any]:
    """Assert the route returned one of the expected statuses and a JSON body."""
    assert result.get("status") in expected, result
    body = result.get("body")
    assert isinstance(body, dict), result
    return body
