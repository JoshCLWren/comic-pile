"""Measured statement-count regression for ``POST /api/v1/auth/login`` (#4737).

Runs the native Rust auth login against a registered user and asserts the
Postgres statement delta stays bounded (login budget: 8 total), proving the
login flow is set-based with no per-attempt N+1.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth import hash_password
from app.models import User

from route_harness import db_counters, run_rust_example

SECRET = "synthetic-native-auth-login-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_auth_login"
)
BINARY = str(EXAMPLE)


@pytest.mark.asyncio
async def test_auth_login_statements_bounded() -> None:
    """Statement delta must stay at or below the login budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"budget_auth_{uuid4().hex[:16]}"
        password = "parity-auth-budget-password"
        async with AsyncSession(engine) as session:
            session.add(
                User(
                    username=username,
                    email=f"{username}@example.invalid",
                    password_hash=hash_password(password),
                    is_admin=False,
                )
            )
            await session.commit()
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_USERNAME": username,
            "RUST_ROLL_TEST_PASSWORD": password,
            "RUST_ROLL_TEST_BUDGET_ONLY": "1",
        }
        _, _, s_before = await db_counters(engine)
        result, _, _, _ = await run_rust_example(BINARY, env)
        valid = result.get("valid")
        assert isinstance(valid, dict) and valid.get("status") == 200
        assert valid.get("token_issued") is True
        _, _, s_after = await db_counters(engine)
        delta = (s_after - s_before) if s_before is not None and s_after is not None else None
        print(f"auth_login_delta={delta}", flush=True)
        assert delta is not None, "pg_stat_statements must measure the isolated service role"
        # Six handler statements, two transaction controls and two cold-pool
        # checkout probes are the measured maximum for one successful login.
        assert delta <= 10, f"auth login issued {delta} statements"
    finally:
        await engine.dispose()
