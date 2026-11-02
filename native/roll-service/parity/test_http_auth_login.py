"""Native rejected-login and successful-login HTTP parity on the canonical schema.

The original #4484 test manually created a simplified subset of PostgreSQL
tables and did not run rejected logins. Here the native HTTP router executes
against the same SQLAlchemy model schema used by the Python application.
"""
from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth import hash_password
from app.database import Base
from app.models import User
from app.models.failed_login_attempt import FailedLoginAttempt

SECRET = "synthetic-auth-canonical-schema-secret"
PASSWORD = "parity-auth-password-correct"


@pytest.mark.asyncio
async def test_rejected_and_valid_login_use_actual_app_schema() -> None:
    """Require real failed-attempt INSERTs and identical 401 rejection bodies."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    schema = f"rust_auth_parity_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, checkfirst=False
                )
            )

        username = f"auth_{uuid4().hex[:16]}"
        async with AsyncSession(engine) as session:
            session.add(
                User(
                    username=username,
                    email=f"{username}@example.invalid",
                    password_hash=hash_password(PASSWORD),
                    is_admin=False,
                )
            )
            await session.commit()

        env = os.environ.copy()
        env.update(
            {
                "RUST_ROLL_DATABASE_URL": f"{url}?options=-c%20search_path%3D{schema}",
                "RUST_ROLL_JWT_SECRET": SECRET,
                "RUST_ROLL_TEST_USERNAME": username,
                "RUST_ROLL_TEST_PASSWORD": PASSWORD,
                "RUST_ROLL_TEST_REGISTER_USERNAME": f"reg_{uuid4().hex[:16]}",
                "RUST_ROLL_TEST_REGISTER_EMAIL": f"reg_{uuid4().hex[:16]}@example.invalid",
                "RUST_ROLL_TEST_REGISTER_PASSWORD": "registered-parity-password",
            }
        )
        process = await asyncio.create_subprocess_exec(
            "native/roll-service/target/debug/examples/http_auth_login",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 35)
        assert process.returncode == 0, stderr.decode()
        result = json.loads(stdout)
        # Production users.created_at is NOT NULL with no server default; a
        # handcrafted DEFAULT NOW() table masked the register 500.
        assert result["register"]["status"] == 200, result
        assert result["register"]["token_issued"] is True
        assert result["registered_valid"]["status"] == 200, result
        assert result["registered_valid"]["token_issued"] is True
        assert result["valid"]["status"] == 200, result
        assert result["valid"]["token_issued"] is True
        for key in ("wrong_password", "unknown_user"):
            assert result[key]["status"] == 401, result
            assert result[key]["detail"] == "Incorrect username or password"
            assert result[key]["token_issued"] is False
        assert result["wrong_password"]["detail"] == result["unknown_user"]["detail"]

        async with AsyncSession(engine) as session:
            count = await session.scalar(
                select(func.count())
                .select_from(FailedLoginAttempt)
                .where(
                    FailedLoginAttempt.username.in_(
                        [username, "does-not-exist-auth-parity"]
                    )
                )
            )
        assert count == 2, "both rejected login branches must persist their failed attempt"
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
