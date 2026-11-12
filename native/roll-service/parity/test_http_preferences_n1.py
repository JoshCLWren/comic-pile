"""Measured statement-count regression for ``GET /api/v1/users/me/preferences`` (#4737).

Runs the native Rust preferences read against a seeded user and asserts the
Postgres statement delta stays bounded (single statement), proving the read is
set-based with no per-row N+1.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User
from route_harness import db_counters, run_rust_example

SECRET = "synthetic-native-preferences-n1-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_preferences"
)
BINARY = str(EXAMPLE)

PREFERENCES_URI = "/api/v1/users/me/preferences"


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {"sub": username, "jti": jti, "type": "access", "exp": 4_102_444_800},
        SECRET,
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_preferences_statements_bounded() -> None:
    """Statement delta must stay at or below the single-statement budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"prefn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_POOL_SIZE": "2",
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": PREFERENCES_URI,
        }
        _, _, s_before = await db_counters(engine)
        await run_rust_example(BINARY, env)
        _, _, s_after = await db_counters(engine)
        delta = (s_after - s_before) if s_before is not None and s_after is not None else None
        print(f"preferences_delta={delta}", flush=True)
        assert delta is not None, "pg_stat_statements is required"
        assert delta <= 10, f"preferences read issued {delta} statements"
    finally:
        await engine.dispose()
