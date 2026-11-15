"""Measured statement-count regression for ``GET /api/v2/auth/me`` (#5147).

Seeds a small (5) and a large (200) account table for one reader, runs the
native Rust current-user profile against each, and asserts the Postgres
statement delta stays bounded and constant, proving the folded authentication
lookup plus profile read are set-based with no per-account N+1 and no growth
with the number of accounts. A deliberately added extra query and a per-row
N+1 burst must fail this route's budget.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User

from auth_budget_controls import (
    auth_token,
    extra_query_fails_budget,
    grow_accounts,
    per_row_queries_fail_budget,
)
from route_harness import assert_declared_budget, cargo_example_path, measure_route

SECRET = "synthetic-native-auth-me-n1-secret"
METHOD = "GET"
ROUTE = "/api/v2/auth/me"
EXAMPLE = cargo_example_path("http_auth_request")
BINARY = str(EXAMPLE)
SMALL_ACCOUNTS = 5
LARGE_ACCOUNTS = 200


@pytest.mark.asyncio
async def test_auth_me_statements_do_not_grow_with_account_count() -> None:
    """Statement delta must stay constant from 5 to 200 accounts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        prefix = f"amen1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=prefix, email=f"{prefix}@example.invalid")
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
            token = auth_token(
                prefix, jti=f"jti-{uuid4().hex}", secret=SECRET, token_type="access"
            )

        env = {
            **os.environ,
            "RUST_ROLL_TEST_METHOD": METHOD,
            "RUST_ROLL_TEST_URI": ROUTE,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        small = await measure_route(BINARY, env, engine, ROUTE, "small")
        assert small.status == 200, small.body
        assert small.body.get("id") == owner_id, small.body
        assert small.body.get("username") == prefix, small.body
        assert small.body.get("email") == f"{prefix}@example.invalid", small.body
        assert small.body.get("is_admin") is False, small.body

        await grow_accounts(url, prefix, SMALL_ACCOUNTS, LARGE_ACCOUNTS)
        large = await measure_route(BINARY, env, engine, ROUTE, "large")
        assert large.status == 200, large.body
        assert large.body.get("id") == owner_id, large.body
        assert large.body.get("username") == prefix, large.body

        assert small.db_statements is not None and large.db_statements is not None, (
            "pg_stat_statements is required"
        )
        assert small.db_nested_statements is not None and (
            large.db_nested_statements is not None
        ), "nested trigger statements must be measured separately"
        assert small.db_nested_statements == 0 and large.db_nested_statements == 0, (
            "the profile read must not trigger per-row nested work"
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