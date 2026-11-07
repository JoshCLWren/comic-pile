"""Native v2 scoped Roll resources against the canonical Python oracle.

The synthetic schema comes from the canonical SQLAlchemy models, so both
mounted GETs run against the same tables production migrations create:

* ``GET /api/v2/roll/die-state`` reports the current logical die, the approved
  d2-d20 ladder, the reset default and the newest recorded roll, and
* ``GET /api/v2/roll/eligible-issue-ids`` reports the ordered issue identifiers
  the next ``POST /api/v2/roll/offer`` can select from for the same die and the
  same browser-owned snoozes.

Each reader's library is scoped by the folded authentication CTE, and each
request issues exactly one PostgreSQL statement including the token's
revocation and credential-epoch check.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Dependency, Event, Issue, RevokedToken, Thread, User

SECRET = "synthetic-roll-resource-secret"
# Whole seconds since the epoch of the owner's password_change credential.
STORED_EPOCH = 1_767_225_600
# CI builds into native/roll-service/target; the managed local wrapper keeps
# its own bounded target directory, so locate the built example without
# changing how this test builds or runs anything.
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_roll_resources"
)

ROLLED_AT = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


def _token(username: str, *, jti: str, password_epoch: int | None = None) -> str:
    payload: dict[str, object] = {
        "sub": username,
        "jti": jti,
        "type": "access",
        "exp": 4_102_444_800,
    }
    if password_epoch is not None:
        payload["pc"] = password_epoch
    return jwt.encode(payload, SECRET, algorithm="HS256")


async def _run_example(env: dict[str, str]) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        str(EXAMPLE),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 30)
    assert proc.returncode == 0, err.decode()
    if err:
        print(err.decode(), flush=True)
    return json.loads(out)


@pytest.mark.asyncio
async def test_scoped_roll_resources_match_the_canonical_schema() -> None:
    """Die state, eligible ids, snoozes, isolation and one-statement budget."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    schema = f"rust_roll_resources_{uuid4().hex}"
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

        owner_name = f"roll_{uuid4().hex[:12]}"
        stranger_name = f"stranger_{uuid4().hex[:12]}"
        owner_token = _token(owner_name, jti=f"jti-{uuid4().hex}", password_epoch=STORED_EPOCH)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(
                username=owner_name,
                password_changed_at=datetime.fromtimestamp(STORED_EPOCH, tz=UTC),
            )
            stranger = User(username=stranger_name)
            db.add_all([owner, stranger])
            await db.flush()

            # Six active threads for the owner, one completed thread that must
            # never enter the pool, and a d4 recorded by an explicit command.
            threads = [
                Thread(
                    user_id=owner.id,
                    title=f"Owned {position}",
                    format="Comic",
                    queue_position=position,
                    issues_remaining=2,
                    total_issues=4,
                )
                for position in range(1, 7)
            ]
            finished = Thread(
                user_id=owner.id,
                title="Finished",
                format="Comic",
                queue_position=7,
                issues_remaining=0,
                status="completed",
                total_issues=4,
            )
            foreign_threads = [
                Thread(
                    user_id=stranger.id,
                    title="Foreign Secret",
                    format="Comic",
                    queue_position=1,
                    issues_remaining=2,
                    total_issues=3,
                ),
                Thread(
                    user_id=stranger.id,
                    title="Foreign Blocked",
                    format="Comic",
                    queue_position=2,
                    issues_remaining=2,
                    total_issues=3,
                ),
            ]
            db.add_all([*threads, finished, *foreign_threads])
            await db.flush()

            owned_issues = [
                Issue(
                    thread_id=thread.id,
                    issue_number=str(position),
                    position=position,
                    status="unread",
                )
                for position, thread in enumerate(threads, start=1)
            ]
            finished_issue = Issue(
                thread_id=finished.id, issue_number="1", position=1, status="unread"
            )
            foreign_issues = [
                Issue(
                    thread_id=thread.id,
                    issue_number=str(position),
                    position=position,
                    status="unread",
                )
                for position, thread in enumerate(foreign_threads, start=1)
            ]
            db.add_all([*owned_issues, finished_issue, *foreign_issues])
            await db.flush()
            for thread, issue in zip(threads, owned_issues, strict=True):
                thread.next_unread_issue_id = issue.id
            finished.next_unread_issue_id = finished_issue.id
            for thread, issue in zip(foreign_threads, foreign_issues, strict=True):
                thread.next_unread_issue_id = issue.id

            # The owner's current die is an explicit d4; the newest roll picked
            # the third queue entry, and an older roll must stay superseded.
            owner_die = Event(
                user_id=owner.id,
                type="manual_die",
                die_after=4,
                timestamp=datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC),
            )
            older_roll = Event(
                user_id=owner.id,
                type="roll",
                selected_thread_id=threads[1].id,
                die=4,
                result=2,
                issue_id=owned_issues[1].id,
                issue_number="2",
                timestamp=datetime(2026, 10, 5, 9, 0, 0, tzinfo=UTC),
            )
            newest_roll = Event(
                user_id=owner.id,
                type="roll",
                selected_thread_id=threads[2].id,
                die=4,
                result=3,
                issue_id=owned_issues[2].id,
                issue_number="3",
                timestamp=ROLLED_AT,
            )
            # The stranger's newest die outcome is a legacy d50, and their
            # reader prerequisite holds the second thread behind the first.
            stranger_die = Event(
                user_id=stranger.id,
                type="rate",
                die_after=50,
                timestamp=datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC),
            )
            stranger_prerequisite = Dependency(
                source_issue_id=foreign_issues[0].id,
                target_issue_id=foreign_issues[1].id,
                origin="reader",
            )
            db.add_all(
                [
                    owner_die,
                    older_roll,
                    newest_roll,
                    stranger_die,
                    stranger_prerequisite,
                ]
            )
            await db.commit()

            owner_thread_ids = [thread.id for thread in threads]
            owner_issue_ids = [issue.id for issue in owned_issues]

        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url
            + ("&" if "?" in url else "?")
            + f"options=-csearch_path%3D{schema}",
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": owner_token,
            "RUST_ROLL_POOL_SIZE": "2",
        }

        die = await _run_example({**env, "RUST_ROLL_TEST_URI": "/api/v2/roll/die-state"})
        assert die["status"] == 200, die
        assert die["die_statements"] == 1, die
        assert die["body"] == {
            "die": 4,
            "ladder": [2, 4, 6, 8, 10, 12, 20],
            "default_die": 6,
            "last_roll": {
                "thread_id": owner_thread_ids[2],
                "issue_id": owner_issue_ids[2],
                "issue_number": "3",
                "result": 3,
                "die": 4,
                "rolled_at": "2026-11-01T10:00:00.000Z",
            },
        }

        eligible = await _run_example(env)
        assert eligible["status"] == 200, eligible
        assert eligible["eligible_statements"] == 1, eligible
        # d4 reports exactly the four highest-ranked eligible faces, in queue
        # order, and the die that bounded them.
        assert eligible["body"] == {
            "die": 4,
            "issue_ids": owner_issue_ids[:4],
            "thread_ids": owner_thread_ids[:4],
            "pool_reason": "ready",
        }

        snoozed = await _run_example(
            {
                **env,
                "RUST_ROLL_TEST_URI": "/api/v2/roll/eligible-issue-ids?"
                + urlencode({"snoozed": f"{owner_thread_ids[0]},{owner_thread_ids[1]}"}),
            }
        )
        assert snoozed["status"] == 200, snoozed
        assert snoozed["eligible_statements"] == 1, snoozed
        # Browser snoozes leave the queue before the die bound, exactly as the
        # offer does, so the pool backfills from beyond the snoozed window.
        assert snoozed["body"] == {
            "die": 4,
            "issue_ids": owner_issue_ids[2:6],
            "thread_ids": owner_thread_ids[2:6],
            "pool_reason": "ready",
        }

        malformed = await _run_example(
            {
                **env,
                "RUST_ROLL_TEST_URI": "/api/v2/roll/eligible-issue-ids?"
                + urlencode({"snoozed": "not-a-thread"}),
            }
        )
        assert malformed["status"] == 422, malformed
        assert malformed["eligible_statements"] == 0, malformed

        # A stranger never sees the owner's library, and their legacy d50
        # outcome projects to the approved d20.
        stranger_env = {
            **env,
            "RUST_ROLL_TEST_TOKEN": _token(
                stranger_name, jti=f"jti-{uuid4().hex}", password_epoch=STORED_EPOCH
            ),
        }
        stranger_die_state = await _run_example(
            {**stranger_env, "RUST_ROLL_TEST_URI": "/api/v2/roll/die-state"}
        )
        assert stranger_die_state["status"] == 200, stranger_die_state
        assert stranger_die_state["body"]["die"] == 20
        assert stranger_die_state["body"]["last_roll"] is None
        stranger_eligible = await _run_example(stranger_env)
        assert stranger_eligible["status"] == 200, stranger_eligible
        assert stranger_eligible["body"]["thread_ids"] == [foreign_threads[0].id]
        assert stranger_eligible["body"]["issue_ids"] == [foreign_issues[0].id]
        for thread_id in owner_thread_ids:
            assert thread_id not in stranger_eligible["body"]["thread_ids"]

        # A revoked credential and a superseded credential epoch are rejected
        # before any owner-scoped row is read.
        async with AsyncSession(engine, expire_on_commit=False) as db:
            revoked_jti = f"revoked-{uuid4().hex}"
            db.add(RevokedToken(user_id=owner.id, jti=revoked_jti, expires_at=ROLLED_AT))
            await db.commit()
        revoked = await _run_example(
            {
                **env,
                "RUST_ROLL_TEST_TOKEN": _token(
                    owner_name, jti=revoked_jti, password_epoch=STORED_EPOCH
                ),
            }
        )
        assert revoked["status"] == 401, revoked
        assert revoked["body"] == {"detail": "Token has been revoked"}

        stale = await _run_example(
            {
                **env,
                "RUST_ROLL_TEST_TOKEN": _token(
                    owner_name, jti=f"stale-{uuid4().hex}", password_epoch=0
                ),
            }
        )
        assert stale["status"] == 401, stale
        assert stale["body"] == {"detail": "Password changed; please sign in again."}
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
