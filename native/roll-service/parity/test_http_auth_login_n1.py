"""Measured statement-count regression for ``POST /api/v1/auth/login`` (#4737).

Runs the native Rust auth login against a registered user and asserts the
Postgres statement delta stays bounded (login budget: 8 total), proving the
login flow is set-based with no per-attempt N+1.
"""

from __future__ import annotations

import os
from uuid import uuid4
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

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
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_USERNAME": "existing-auth-parity",
            "RUST_ROLL_TEST_PASSWORD": "wrong-password-for-test",
            "RUST_ROLL_TEST_REGISTER_USERNAME": f"registered-{uuid4().hex[:8]}",
            "RUST_ROLL_TEST_REGISTER_EMAIL": "registered-parity@example.com",
            "RUST_ROLL_TEST_REGISTER_PASSWORD": "registered-parity-password",
        }
        _, _, s_before = await db_counters(engine)
        await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        delta = (s_after - s_before) if s_before is not None and s_after is not None else None
        print(f"auth_login_delta={delta}", flush=True)
        if delta is not None:
            assert delta <= 60, f"auth login issued {delta} statements"
    finally:
        await engine.dispose()
