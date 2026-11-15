"""Measured statement-count regression for ``POST /api/v2/auth/forgot-password`` (#5147).

Seeds a small (5) and a large (200) account table around an enumeration-safe
recovery request and asserts the Postgres statement delta stays bounded and
constant, proving the address lookup plus the single-use digest replacement are
set-based with no per-account N+1 and no growth with the number of accounts.
Each request must leave exactly one live digest for the owner (the previous
digest is replaced, not accumulated), and a deliberately added extra query and
a per-row N+1 burst must fail this route's budget.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User

from auth_budget_controls import (
    extra_query_fails_budget,
    grow_accounts,
    per_row_queries_fail_budget,
)
from route_harness import assert_declared_budget, cargo_example_path, measure_route

METHOD = "POST"
ROUTE = "/api/v2/auth/forgot-password"
EXAMPLE = cargo_example_path("http_auth_request")
BINARY = str(EXAMPLE)
SECRET = "synthetic-native-auth-forgot-n1-secret"
SMALL_ACCOUNTS = 5
LARGE_ACCOUNTS = 200
MESSAGE = "If an account exists, a reset link has been sent."


async def _live_digests(url: str, user_id: int) -> list[str]:
    """Return the owner's unused reset digests, oldest first."""
    raw = await asyncpg.connect(url)
    try:
        rows = await raw.fetch(
            "SELECT token_digest FROM password_reset_tokens "
            "WHERE user_id = $1 AND used_at IS NULL AND expires_at > NOW() "
            "ORDER BY id",
            user_id,
        )
    finally:
        await raw.close()
    return [str(row["token_digest"]) for row in rows]


@pytest.mark.asyncio
async def test_forgot_password_statements_do_not_grow_with_account_count() -> None:
    """Statement delta must stay constant from 5 to 200 accounts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        prefix = f"afpn1_{uuid4().hex[:12]}"
        email = f"{prefix}@example.invalid"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=prefix, email=email)
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
            "RUST_ROLL_TEST_BODY": f'{{"email":"{email}"}}',
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        small = await measure_route(BINARY, env, engine, ROUTE, "small")
        assert small.status == 200, small.body
        assert small.body.get("message") == MESSAGE, small.body

        small_digests = await _live_digests(url, owner_id)
        assert len(small_digests) == 1, "recovery must leave exactly one live digest"
        assert len(small_digests[0]) == 64, "the stored digest must be sha256 hex"
        int(small_digests[0], 16)

        await grow_accounts(url, prefix, SMALL_ACCOUNTS, LARGE_ACCOUNTS)
        large = await measure_route(BINARY, env, engine, ROUTE, "large")
        assert large.status == 200, large.body
        assert large.body.get("message") == MESSAGE, large.body

        large_digests = await _live_digests(url, owner_id)
        assert len(large_digests) == 1, "a second request must replace the first digest"
        assert large_digests[0] != small_digests[0], (
            "each recovery request must mint a fresh single-use digest"
        )

        assert small.db_statements is not None and large.db_statements is not None, (
            "pg_stat_statements is required"
        )
        assert small.db_nested_statements is not None and (
            large.db_nested_statements is not None
        ), "nested trigger statements must be measured separately"
        assert small.db_nested_statements == 0 and large.db_nested_statements == 0, (
            "the digest replacement must not trigger per-row nested work"
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
