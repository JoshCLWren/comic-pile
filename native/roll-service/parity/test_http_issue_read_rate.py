"""Authenticated native direct issue PATCH against the canonical app schema.

The native `PATCH /api/v2/issues/{issue_id}` command replaces the Python
read/unread writers, so it must maintain the same denormalized state. The
mounted Rust route runs on a disposable schema created from the canonical
SQLAlchemy models (including `threads.is_blocked NOT NULL` and
`dependencies`), which is exactly the schema the hand-written unit test was
missing when the stale blocked flag went unnoticed.

The regression proves the canonical prerequisite state machine:

* reading the prerequisite issue clears the dependent thread's persisted
  `is_blocked`, making it eligible for the native Skip pool;
* marking the prerequisite unread blocks it again and Skip excludes it;
* a historical `cbl-order:%` edge never blocks.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Dependency, Issue, Thread, User

SECRET = "synthetic-native-issue-command-secret"

RUNNER = Path(
    os.environ.get(
        "RUST_ROLL_ISSUE_READ_RATE_EXAMPLE",
        Path(__file__).resolve().parents[1] / "target/debug/examples/http_issue_read_rate",
    )
)


async def _run_command(env: dict[str, str]) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        RUNNER,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 25)
    assert proc.returncode == 0, err.decode()
    return json.loads(out)


async def _skip_pool_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Return the ids the native Skip pool would consider for one owner.

    Mirrors the eligibility gate in `native/roll-service/src/skip.rs`
    (`POOL_SQL`): active, reader-visible queue position, and the persisted
    derived `is_blocked` flag. Session snooze/skip exclusions are not involved
    because this fixture has no session history.
    """
    rows = await db.execute(
        text(
            "SELECT id FROM threads"
            " WHERE user_id = :user_id AND status = 'active'"
            "   AND queue_position >= 1 AND is_blocked = false"
        ),
        {"user_id": user_id},
    )
    return {row[0] for row in rows.all()}


@pytest.mark.asyncio
async def test_direct_issue_reads_refresh_canonical_blocked_state() -> None:
    """Read/unread a prerequisite and assert the dependent thread's Skip state."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    name = f"rust_issue_command_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": f"{name},public"}},
    )
    try:
        async with engine.begin() as connection:
            # The schema is new, so skip public-schema table collisions while
            # keeping public on the path for the pg_trgm operator class.
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, checkfirst=False
                )
            )

        now = datetime.now(UTC)
        username = f"commands_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()

            prerequisite = Thread(
                user_id=owner.id,
                title="Prerequisite Run",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
                status="active",
            )
            dependent = Thread(
                user_id=owner.id,
                title="Dependent Run",
                format="Comic",
                queue_position=2,
                issues_remaining=1,
                total_issues=1,
                status="active",
                # The dependent frontier is already blocked by the unread
                # prerequisite above, matching the persisted production flag.
                is_blocked=True,
            )
            control = Thread(
                user_id=owner.id,
                title="Cbl Control Run",
                format="Comic",
                queue_position=3,
                issues_remaining=1,
                total_issues=1,
                status="active",
                is_blocked=False,
            )
            db.add_all([prerequisite, dependent, control])
            await db.flush()

            source_issue = Issue(
                thread_id=prerequisite.id,
                issue_number="1",
                position=1,
                status="unread",
            )
            dependent_issue = Issue(
                thread_id=dependent.id,
                issue_number="1",
                position=1,
                status="unread",
            )
            control_issue = Issue(
                thread_id=control.id,
                issue_number="1",
                position=1,
                status="unread",
            )
            db.add_all([source_issue, dependent_issue, control_issue])
            await db.flush()
            prerequisite.next_unread_issue_id = source_issue.id
            dependent.next_unread_issue_id = dependent_issue.id
            control.next_unread_issue_id = control_issue.id
            db.add_all(
                [
                    Dependency(
                        source_issue_id=source_issue.id,
                        target_issue_id=dependent_issue.id,
                        note=None,
                    ),
                    # Historical CBL materialization edge: inert, never blocks.
                    Dependency(
                        source_issue_id=source_issue.id,
                        target_issue_id=control_issue.id,
                        note="cbl-order:legacy-materialization",
                    ),
                ]
            )
            await db.commit()
            dependent_id = dependent.id
            control_id = control.id
            source_id = source_issue.id

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-issue-command-fixture",
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
            "RUST_ROLL_TEST_ISSUE_ID": str(source_id),
            "RUST_ROLL_TEST_BODY": json.dumps(
                {
                    "status": "read",
                    "idempotency_key": "canonical-blocked-read-01",
                }
            ),
        }

        read = await _run_command(env)
        assert read["status"] == 200, read
        issue_body = read["body"]["issue"]
        assert issue_body["issue_id"] == source_id
        assert issue_body["status"] == "read"
        # A direct read defaults to the documented 3.5 rating.
        assert issue_body["rating"] == 3.5

        async with AsyncSession(engine, expire_on_commit=False) as db:
            flags = dict(
                (
                    await db.execute(
                        text("SELECT id, is_blocked FROM threads WHERE user_id = :user_id"),
                        {"user_id": owner.id},
                    )
                ).all()
            )
            assert flags[dependent_id] is False, "direct read must clear the derived flag"
            assert flags[control_id] is False, "cbl-order edges must never block"
            pool = await _skip_pool_ids(db, owner.id)
            assert dependent_id in pool, "unblocked dependent must be Skip-eligible"
            assert control_id in pool

        env["RUST_ROLL_TEST_BODY"] = json.dumps(
            {
                "status": "unread",
                "idempotency_key": "canonical-blocked-unread-01",
            }
        )
        unread = await _run_command(env)
        assert unread["status"] == 200, unread
        assert unread["body"]["issue"]["status"] == "unread"

        async with AsyncSession(engine, expire_on_commit=False) as db:
            flags = dict(
                (
                    await db.execute(
                        text("SELECT id, is_blocked FROM threads WHERE user_id = :user_id"),
                        {"user_id": owner.id},
                    )
                ).all()
            )
            assert flags[dependent_id] is True, "direct unread must set the derived flag"
            assert flags[control_id] is False
            pool = await _skip_pool_ids(db, owner.id)
            assert dependent_id not in pool, "re-blocked dependent must be Skip-excluded"
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))


@pytest.mark.asyncio
async def test_direct_unread_reactivates_completed_series_into_queue() -> None:
    """A completed/position-0 thread must regain real queue membership on unread.

    `active => queue_position >= 1` is an application-wide invariant
    (`count_active_threads`, `dense_positions`, reading eligibility, native
    Skip). `restore_thread` legitimately leaves a fully-read series
    `completed` at position 0, so a direct unread must append it behind the
    reader's existing queue instead of leaving an active thread outside it.
    """
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    name = f"rust_issue_reactivate_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": f"{name},public"}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, checkfirst=False
                )
            )

        now = datetime.now(UTC)
        username = f"reactivate_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()

            active = Thread(
                user_id=owner.id,
                title="Active Run",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
                status="active",
            )
            finished = Thread(
                user_id=owner.id,
                title="Finished Run",
                format="Comic",
                queue_position=0,
                issues_remaining=0,
                total_issues=1,
                status="completed",
                reading_progress="completed",
            )
            db.add_all([active, finished])
            await db.flush()

            active_issue = Issue(
                thread_id=active.id,
                issue_number="1",
                position=1,
                status="unread",
            )
            finished_issue = Issue(
                thread_id=finished.id,
                issue_number="1",
                position=1,
                status="read",
                read_at=now,
            )
            db.add_all([active_issue, finished_issue])
            await db.flush()
            active.next_unread_issue_id = active_issue.id
            await db.commit()
            active_id = active.id
            finished_id = finished.id
            finished_issue_id = finished_issue.id

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-issue-reactivate-fixture",
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
            "RUST_ROLL_TEST_ISSUE_ID": str(finished_issue_id),
            "RUST_ROLL_TEST_BODY": json.dumps(
                {
                    "status": "unread",
                    "idempotency_key": "canonical-reactivate-unread-01",
                }
            ),
        }

        response = await _run_command(env)
        assert response["status"] == 200, response
        assert response["body"]["issue"]["status"] == "unread"
        assert response["body"]["thread"]["status"] == "active"
        assert response["body"]["thread"]["issues_remaining"] == 1

        async with AsyncSession(engine, expire_on_commit=False) as db:
            row = (
                await db.execute(
                    text(
                        "SELECT status, queue_position FROM threads WHERE id = :thread_id"
                    ),
                    {"thread_id": finished_id},
                )
            ).one()
            assert row[0] == "active", "unread must reactivate the completed series"
            assert row[1] >= 1, "an active series must hold a real queue position"
            # The existing queue is not renumbered or reordered.
            active_row = (
                await db.execute(
                    text("SELECT queue_position FROM threads WHERE id = :thread_id"),
                    {"thread_id": active_id},
                )
            ).one()
            assert active_row[0] == 1
            assert row[1] == active_row[0] + 1, "reactivation appends behind the queue"

            canonical = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM threads"
                        " WHERE id = :thread_id AND status = 'active'"
                        "   AND queue_position >= 1"
                    ),
                    {"thread_id": finished_id},
                )
            ).scalar_one()
            assert canonical == 1, "must satisfy the canonical active-queue predicate"
            pool = await _skip_pool_ids(db, owner.id)
            assert finished_id in pool, "reactivated series must be Skip-eligible"
            assert active_id in pool
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
