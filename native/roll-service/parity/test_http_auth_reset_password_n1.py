"""Measured statement-count regression for ``POST /api/v2/auth/reset-password`` (#5147).

Seeds a small (5) and a large (200) account table around password completion
and asserts the Postgres statement delta stays bounded and constant, proving
the single-use token consume plus the owner password update are set-based with
no per-account N+1 and no growth with the number of accounts. Consumption must
be single-use (replay rejected), the stored hash must verify the new password
and the credential epoch must advance, and a deliberately added extra query and
a per-row N+1 burst must fail this route's budget.
"""

from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth import hash_password, verify_password
from app.models import User

from auth_budget_controls import (
    extra_query_fails_budget,
    grow_accounts,
    per_row_queries_fail_budget,
)
from route_harness import assert_declared_budget, cargo_example_path, measure_route

METHOD = "POST"
ROUTE = "/api/v2/auth/reset-password"
EXAMPLE = cargo_example_path("http_auth_request")
BINARY = str(EXAMPLE)
SECRET = "synthetic-native-auth-reset-n1-secret"
SMALL_ACCOUNTS = 5
LARGE_ACCOUNTS = 200
MESSAGE = "Password reset successfully."
OLD_PASSWORD = "native-reset-budget-old-password"
NEW_PASSWORD = "native-reset-budget-new-password"


def _digest(raw_token: str) -> str:
    """Return the sha256 hex digest the native reset service stores."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def _seed_reset_token(url: str, user_id: int, raw_token: str) -> None:
    """Store one live single-use digest for the owner."""
    raw = await asyncpg.connect(url)
    try:
        await raw.execute(
            "INSERT INTO password_reset_tokens "
            "(user_id, token_digest, expires_at, created_at) "
            "VALUES ($1, $2, NOW() + INTERVAL '30 minutes', NOW())",
            user_id,
            _digest(raw_token),
        )
    finally:
        await raw.close()


async def _reset_state(url: str, user_id: int, raw_token: str) -> tuple[str, bool, bool]:
    """Return (stored hash, digest used, credential epoch advanced)."""
    raw = await asyncpg.connect(url)
    try:
        user = await raw.fetchrow(
            "SELECT password_hash, password_changed_at FROM users WHERE id = $1",
            user_id,
        )
        used_at = await raw.fetchval(
            "SELECT used_at FROM password_reset_tokens "
            "WHERE user_id = $1 AND token_digest = $2",
            user_id,
            _digest(raw_token),
        )
    finally:
        await raw.close()
    assert user is not None, "the reset target must still exist"
    return str(user["password_hash"]), used_at is not None, (
        user["password_changed_at"] is not None
    )


def _body(raw_token: str) -> str:
    """Return the canonical reset request body."""
    return f'{{"token":"{raw_token}","new_password":"{NEW_PASSWORD}"}}'


@pytest.mark.asyncio
async def test_reset_password_statements_do_not_grow_with_account_count() -> None:
    """Statement delta must stay constant from 5 to 200 accounts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        prefix = f"arspn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(
                username=prefix,
                email=f"{prefix}@example.invalid",
                password_hash=hash_password(OLD_PASSWORD),
            )
            db.add(owner)
            await db.flush()
            for index in range(SMALL_ACCOUNTS):
                db.add(
                    User(
                        username=f"{prefix}_peer{index}",
                        email=f"{prefix}_peer{index}@example.invalid",
                    )
                )
            await db.commit()
            owner_id = owner.id

        env = {
            **os.environ,
            "RUST_ROLL_TEST_METHOD": METHOD,
            "RUST_ROLL_TEST_URI": ROUTE,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }

        small_token = f"reset-{uuid4().hex}"
        await _seed_reset_token(url, owner_id, small_token)
        small = await measure_route(
            BINARY, {**env, "RUST_ROLL_TEST_BODY": _body(small_token)}, engine, ROUTE, "small"
        )
        assert small.status == 200, small.body
        assert small.body.get("message") == MESSAGE, small.body

        small_hash, small_used, small_epoch = await _reset_state(url, owner_id, small_token)
        assert small_used, "the presented reset token must be consumed exactly once"
        assert small_epoch, "completing a reset must advance the credential epoch"
        assert verify_password(NEW_PASSWORD, small_hash), (
            "the stored hash must verify the new password"
        )
        assert not verify_password(OLD_PASSWORD, small_hash), (
            "the previous password must no longer verify"
        )

        replay = await measure_route(
            BINARY, {**env, "RUST_ROLL_TEST_BODY": _body(small_token)}, engine, ROUTE, "replay"
        )
        assert replay.status == 400, replay.body
        assert replay.body.get("detail") == "Invalid or expired reset request.", replay.body

        await grow_accounts(url, prefix, SMALL_ACCOUNTS, LARGE_ACCOUNTS)
        large_token = f"reset-{uuid4().hex}"
        await _seed_reset_token(url, owner_id, large_token)
        large = await measure_route(
            BINARY, {**env, "RUST_ROLL_TEST_BODY": _body(large_token)}, engine, ROUTE, "large"
        )
        assert large.status == 200, large.body
        assert large.body.get("message") == MESSAGE, large.body

        large_hash, large_used, large_epoch = await _reset_state(url, owner_id, large_token)
        assert large_used and large_epoch, large.body
        assert verify_password(NEW_PASSWORD, large_hash), large.body

        assert small.db_statements is not None and large.db_statements is not None, (
            "pg_stat_statements is required"
        )
        assert small.db_nested_statements is not None and (
            large.db_nested_statements is not None
        ), "nested trigger statements must be measured separately"
        assert small.db_nested_statements == 0 and large.db_nested_statements == 0, (
            "the password update must not trigger per-row nested work"
        )
        assert_declared_budget(METHOD, ROUTE, small.db_statements, large.db_statements)
        assert large.db_statements == small.db_statements, (
            f"statement count grew with account count: {small.db_statements} -> "
            f"{large.db_statements}"
        )

        await extra_query_fails_budget(
            engine, url, method=METHOD, path=ROUTE, measured=small.db_statements
        )
        await per_row_queries_fail_budget(
            engine,
            url,
            method=METHOD,
            path=ROUTE,
            measured=small.db_statements,
            rows=LARGE_ACCOUNTS,
        )
    finally:
        await engine.dispose()
