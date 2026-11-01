"""Authenticated native reading-boundaries POST against the real app schema.

The synthetic schema is created from the canonical SQLAlchemy models, so the
handler runs against the same tables production migrations create. Nothing here
reads or writes the live library.
"""
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Issue, Thread, User

SECRET = "synthetic-native-reading-boundary-secret"


async def _run_example(env: dict[str, str]) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        "native/roll-service/target/debug/examples/http_reading_boundaries",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 25)
    assert proc.returncode == 0, err.decode()
    return json.loads(out)


@pytest.mark.asyncio
async def test_authenticated_reading_boundaries_v2_http_is_owner_scoped():
    """Exercise the mounted POST, its Option E SQL, and foreign-thread isolation."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    name = f"rust_boundary_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": name}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        now = datetime.now(UTC)
        username = f"rb_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            stranger = User(username=f"other_{uuid4().hex[:16]}")
            db.add_all([owner, stranger])
            await db.flush()
            owned = Thread(
                user_id=owner.id,
                title="Owned Series",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
            )
            foreign = Thread(
                user_id=stranger.id,
                title="Private Series",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
            )
            db.add_all([owned, foreign])
            await db.flush()
            owned_issue = Issue(
                thread_id=owned.id, issue_number="1", position=1, status="unread"
            )
            foreign_issue = Issue(
                thread_id=foreign.id, issue_number="1", position=1, status="unread"
            )
            db.add_all([owned_issue, foreign_issue])
            await db.flush()
            owned.next_unread_issue_id = owned_issue.id
            foreign.next_unread_issue_id = foreign_issue.id
            owned_id, foreign_id, owned_issue_id = owned.id, foreign.id, owned_issue.id
            await db.commit()

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-reading-boundary-fixture",
                "type": "access",
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            SECRET,
            "HS256",
        )
        query = f"options=-csearch_path%3D{name}"
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url + ("&" if "?" in url else "?") + query,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        env["RUST_ROLL_TEST_BODY"] = json.dumps({"thread_ids": [owned_id]})
        result = await _run_example(env)
        assert result["status"] == 200, result
        explanation = result["body"]["threads"][str(owned_id)]
        assert explanation["thread_id"] == owned_id
        assert explanation["state"] == "available"
        assert explanation["next"]["issue"]["issue_id"] == owned_issue_id
        assert str(foreign_id) not in result["body"]["threads"]

        # A foreign thread must not leak an explanation or its metadata.
        env["RUST_ROLL_TEST_BODY"] = json.dumps({"thread_ids": [foreign_id]})
        denied = await _run_example(env)
        assert denied["status"] == 404, denied
        assert denied["body"] == {"detail": "Thread not found"}
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        await admin.dispose()
