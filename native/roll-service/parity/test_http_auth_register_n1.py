"""Measured statement-count regression for ``POST /api/v2/auth/register`` (#5147).

Seeds a small (5) and a large (200) account table around the registration
request and asserts the Postgres statement delta stays bounded and constant,
proving registration is set-based with no per-account N+1 and no growth with
the number of existing accounts. A deliberately added extra query and a
per-row N+1 burst must fail this route's budget.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth import verify_password
from app.models import User

from auth_budget_controls import (
    extra_query_fails_budget,
    grow_accounts,
    per_row_queries_fail_budget,
)
from route_harness import (
    assert_declared_budget,
    cargo_example_path,
    measure_route,
)

SECRET = "synthetic-native-auth-register-n1-secret"
METHOD = "POST"
ROUTE = "/api/v2/auth/register"
EXAMPLE = cargo_example_path("http_auth_request")
BINARY = str(EXAMPLE)
SMALL_ACCOUNTS = 5
LARGE_ACCOUNTS = 200


def _token_pair_is_real(body: dict[str, object], expected_subject: str) -> str:
    """Require the canonical bearer pair shape; return the access token."""
    access = body.get("access_token")
    refresh = body.get("refresh_token")
    assert isinstance(access, str) and access, body
    assert isinstance(refresh, str) and refresh, body
    assert access != refresh, "access and refresh credentials must differ"
    assert body.get("token_type") == "bearer", body
    claims = jwt.decode(access, SECRET, algorithms=["HS256"])
    assert claims["sub"] == expected_subject, claims
    assert claims["type"] == "access", claims
    return access


@pytest.mark.asyncio
async def test_register_statements_do_not_grow_with_account_count() -> None:
    """Statement delta must stay constant from 5 to 200 existing accounts."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        prefix = f"areg_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=prefix)
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

        # Small fixture: register one more account next to the five peers.
        small_username = f"{prefix}-registered"
        env = {
            **os.environ,
            "RUST_ROLL_TEST_METHOD": METHOD,
            "RUST_ROLL_TEST_URI": ROUTE,
            "RUST_ROLL_TEST_BODY": (
                f'{{"username":"{small_username}",'
                f'"email":"{small_username}@example.invalid",'
                '"password":"native-register-budget-password"}'
            ),
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        small = await measure_route(BINARY, env, engine, ROUTE, "small")
        assert small.status == 200, small.body
        small_access = _token_pair_is_real(small.body, small_username)

        raw = await asyncpg.connect(url)
        try:
            row = await raw.fetchrow(
                "SELECT password_hash, is_admin FROM users WHERE username = $1",
                small_username,
            )
        finally:
            await raw.close()
        assert row is not None, "registration must persist the account"
        stored_hash = row["password_hash"]
        assert stored_hash.startswith("$2"), "the password must be stored as a bcrypt hash"
        assert stored_hash != "native-register-budget-password"
        assert verify_password("native-register-budget-password", stored_hash)
        assert row["is_admin"] is False
        claims = jwt.decode(small_access, SECRET, algorithms=["HS256"])
        assert claims["sub"] == small_username, claims

        # Large fixture: 200 existing accounts, then a second registration.
        await grow_accounts(url, prefix, SMALL_ACCOUNTS, LARGE_ACCOUNTS)
        large_username = f"{prefix}-registered-large"
        env["RUST_ROLL_TEST_BODY"] = (
            f'{{"username":"{large_username}",'
            f'"email":"{large_username}@example.invalid",'
            '"password":"native-register-budget-password"}'
        )
        large = await measure_route(BINARY, env, engine, ROUTE, "large")
        assert large.status == 200, large.body
        _token_pair_is_real(large.body, large_username)

        assert small.db_statements is not None and large.db_statements is not None, (
            "pg_stat_statements is required"
        )
        assert small.db_nested_statements is not None and (
            large.db_nested_statements is not None
        ), "nested trigger statements must be measured separately"
        assert small.db_nested_statements == 0 and large.db_nested_statements == 0, (
            "registration must not trigger per-row nested work"
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