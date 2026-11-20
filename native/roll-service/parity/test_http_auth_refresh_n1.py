"""Measured statement-count regression for ``POST /api/v2/auth/refresh`` (#5147).

Seeds a small (5) and a large (200) account table for one reader, rotates that
reader's refresh credential against each fixture, and asserts the Postgres
statement delta stays bounded and constant, proving the revoked-jti lookup plus
the predecessor revocation insert are set-based with no per-account N+1 and no
growth with the number of accounts. The rotated predecessor must be replay
rejected, and a deliberately added extra query and a per-row N+1 burst must
fail this route's budget.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User

from auth_budget_controls import (
    auth_token,
    extra_query_fails_budget,
    grow_accounts,
    per_row_queries_fail_budget,
)
from route_harness import assert_declared_budget, cargo_example_path, measure_route

SECRET = "synthetic-native-auth-refresh-n1-secret"
METHOD = "POST"
ROUTE = "/api/v2/auth/refresh"
EXAMPLE = cargo_example_path("http_auth_request")
BINARY = str(EXAMPLE)
SMALL_ACCOUNTS = 5
LARGE_ACCOUNTS = 200


def _rotated_pair(body: dict[str, object], presented: str) -> None:
    """Require a fresh bearer pair whose refresh credential replaced ``presented``."""
    access = body.get("access_token")
    refresh = body.get("refresh_token")
    assert isinstance(access, str) and access, body
    assert isinstance(refresh, str) and refresh, body
    assert body.get("token_type") == "bearer", body
    assert refresh != presented, "refresh must rotate the presented credential"
    claims = jwt.decode(refresh, SECRET, algorithms=["HS256"])
    assert claims["type"] == "refresh", claims


@pytest.mark.asyncio
async def test_auth_refresh_statements_do_not_grow_with_account_count() -> None:
    """Statement delta must stay constant from 5 to 200 accounts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        prefix = f"arfnn1_{uuid4().hex[:12]}"
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

        def env_for(refresh_token: str) -> dict[str, str]:
            return {
                **os.environ,
                "RUST_ROLL_TEST_METHOD": METHOD,
                "RUST_ROLL_TEST_URI": ROUTE,
                "RUST_ROLL_TEST_BODY": f'{{"refresh_token":"{refresh_token}"}}',
                "RUST_ROLL_DATABASE_URL": url,
                "RUST_ROLL_JWT_SECRET": SECRET,
            }

        small_jti = f"jti-{uuid4().hex}"
        small_token = auth_token(
            prefix, jti=small_jti, secret=SECRET, token_type="refresh"
        )
        small = await measure_route(
            BINARY, env_for(small_token), engine, ROUTE, "small"
        )
        assert small.status == 200, small.body
        _rotated_pair(small.body, small_token)

        raw = await asyncpg.connect(url)
        try:
            revoked = await raw.fetchval(
                "SELECT count(*) FROM revoked_tokens WHERE user_id = $1 AND jti = $2",
                owner_id,
                small_jti,
            )
        finally:
            await raw.close()
        assert revoked == 1, "refresh must revoke the exact presented token"

        replay = await measure_route(
            BINARY, env_for(small_token), engine, ROUTE, "replay"
        )
        assert replay.status == 401, replay.body

        await grow_accounts(url, prefix, SMALL_ACCOUNTS, LARGE_ACCOUNTS)
        large_token = auth_token(
            prefix, jti=f"jti-{uuid4().hex}", secret=SECRET, token_type="refresh"
        )
        large = await measure_route(
            BINARY, env_for(large_token), engine, ROUTE, "large"
        )
        assert large.status == 200, large.body
        _rotated_pair(large.body, large_token)

        assert small.db_statements is not None and large.db_statements is not None, (
            "pg_stat_statements is required"
        )
        assert small.db_nested_statements is not None and (
            large.db_nested_statements is not None
        ), "nested trigger statements must be measured separately"
        assert small.db_nested_statements == 0 and large.db_nested_statements == 0, (
            "the revocation insert must not trigger per-row nested work"
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
