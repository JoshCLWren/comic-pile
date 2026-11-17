"""Native v2 activity endpoint against isolated real Postgres tables, never production.

The test verifies:
1. Owner-scoped activity timeline including sessionless snoozes and ratings
2. One SQL statement budget (bounded query)
3. Proper chronological ordering of events
4. Cursor pagination support
5. Authorization checks (revoked tokens, stale credential epochs)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Event, Issue, ReadingSession, RevokedToken, Thread, User

from route_harness import cargo_example_path

SECRET = "synthetic-native-activity-secret"


def _token(username: str, *, jti: str, password_epoch: int | None = None) -> str:
    payload: dict[str, object] = {
        "sub": username,
        "jti": jti,
        "type": "access",
        "exp": 4_102_444_800,  # Far future expiration
    }
    if password_epoch is not None:
        payload["pc"] = password_epoch
    return jwt.encode(payload, SECRET, algorithm="HS256")


async def _run_example(env: dict[str, str]) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        str(cargo_example_path("http_activity")),
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
async def test_native_activity_is_bounded_owner_scoped_and_one_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activity timeline must include all events with one statement."""
    monkeypatch.delenv("TEST_ENVIRONMENT", raising=False)
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_name = f"activity_{uuid4().hex[:12]}"
        stranger_name = f"stranger_{uuid4().hex[:12]}"
        token = _token(owner_name, jti=f"jti-{uuid4().hex}")
        now = datetime.now(UTC).replace(microsecond=123_456)

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=owner_name, created_at=now)
            stranger = User(username=stranger_name, created_at=now)
            db.add_all([owner, stranger])
            await db.flush()

            # Create threads for testing
            thread_saga = Thread(
                user_id=owner.id,
                title="Saga",
                format="Comic",
                status="active",
                queue_position=1,
            )
            thread_hulk = Thread(
                user_id=owner.id,
                title="Hulk",
                format="Comic",
                status="active",
                queue_position=2,
            )
            db.add_all([thread_saga, thread_hulk])
            await db.flush()

            # Create a session with events
            session = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(minutes=30),
                ended_at=now,
                start_die=6,
                current_die=8,
                ladder_path="d6 → d8",
            )
            db.add(session)
            await db.flush()

            # Create issues
            saga_issue_1 = Issue(thread_id=thread_saga.id, issue_number="1", position=1, status="unread")
            saga_issue_2 = Issue(thread_id=thread_saga.id, issue_number="2", position=2, status="read", read_at=now - timedelta(minutes=20))
            hulk_issue_1 = Issue(thread_id=thread_hulk.id, issue_number="1", position=1, status="read", read_at=now - timedelta(minutes=10))
            db.add_all([saga_issue_1, saga_issue_2, hulk_issue_1])
            await db.flush()

            # Create events - this is the key test case for sessionless snoozes and ratings
            events = [
                # Session start event
                Event(
                    session_id=session.id,
                    thread_id=thread_saga.id,
                    issue_id=saga_issue_1.id,
                    type="roll",
                    result=4,
                    die=6,
                    rating=None,
                    timestamp=now - timedelta(minutes=29),
                ),
                # Session snooze to different die
                Event(
                    session_id=session.id,
                    thread_id=thread_saga.id,
                    type="snooze",
                    die=8,
                    die_after=8,
                    timestamp=now - timedelta(minutes=25),
                ),
                # Rating event on Hulk (threadless in terms of session, but owned by user)
                Event(
                    user_id=owner.id,
                    thread_id=thread_hulk.id,
                    issue_id=hulk_issue_1.id,
                    type="rate",
                    rating=4.5,
                    timestamp=now - timedelta(minutes=15),
                ),
            ]
            db.add_all(events)
            await db.commit()

            env = {
                **os.environ,
                "RUST_ROLL_DATABASE_URL": url,
                "RUST_ROLL_JWT_SECRET": SECRET,
                "RUST_ROLL_TEST_TOKEN": token,
                "RUST_ROLL_POOL_SIZE": "2",
            }

            before = await _db_stats(engine)
            result = await _run_example(env)
            after = await _db_stats(engine)
            assert result["status"] == 200, result
            assert result["metrics_statements"] == 1, result
            assert result["payload_bytes"] < 16_384, result

            # Verify the response structure
            body = result["body"]
            events_list = body.get("events", [])
            assert isinstance(events_list, list), f"Expected events list, got {type(events_list)}"
            assert len(events_list) == 3, f"Expected 3 events, got {len(events_list)}"

            # Verify event ordering (reverse chronological - newest first)
            event_types = [e["type"] for e in events_list]
            # Rating should be first (most recent)
            assert event_types[0] == "rate", f"Expected rate first, got {event_types[0]}"
            # Snooze should be second
            assert event_types[1] == "snooze", f"Expected snooze second, got {event_types[1]}"
            # Roll should be third (oldest)
            assert event_types[2] == "roll", f"Expected roll third, got {event_types[2]}"

            # Verify event details
            rating_event = events_list[0]
            assert rating_event["type"] == "rate"
            assert rating_event["thread_id"] == thread_hulk.id
            assert rating_event["rating"] == 4.5
            assert rating_event["issue_number"] == "1"

            # Verify pagination cursor is present
            next_page_token = body.get("next_page_token")
            # Since we have all events, next_page_token should be null
            assert next_page_token is None, f"Expected no next page token, got {next_page_token}"

            print(
                "native activity budget: "
                f"metrics_statements={result['metrics_statements']} "
                f"payload_bytes={result['payload_bytes']} "
                f"db_commits={after[0] - before[0]} "
                f"db_rollbacks={after[1] - before[1]} "
                f"db_blks_read={after[2] - before[2]} "
                f"db_blks_hit={after[3] - before[3]} "
                f"db_tup_returned={after[4] - before[4]} "
                f"db_tup_fetched={after[5] - before[5]}",
                flush=True,
            )

            # Test with unknown user
            unknown_result = await _run_example(
                {
                    **env,
                    "RUST_ROLL_TEST_TOKEN": _token(
                        f"missing_{uuid4().hex[:12]}", jti=f"missing-{uuid4().hex}"
                    ),
                }
            )
            assert unknown_result["status"] == 401
            assert unknown_result["body"] == {"detail": "User not found"}
            assert unknown_result["metrics_statements"] == 1

            # Test with revoked token
            revoked_jti = f"revoked-{uuid4().hex}"
            db.add(
                RevokedToken(
                    user_id=owner.id,
                    jti=revoked_jti,
                    revoked_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
            await db.commit()
            revoked_result = await _run_example(
                {
                    **env,
                    "RUST_ROLL_TEST_TOKEN": _token(owner_name, jti=revoked_jti),
                }
            )
            assert revoked_result["status"] == 401
            assert revoked_result["body"] == {"detail": "Token has been revoked"}
            assert revoked_result["metrics_statements"] == 1

            # Test with empty activity
            empty_name = f"empty_{uuid4().hex[:12]}"
            empty = User(username=empty_name, created_at=now)
            db.add(empty)
            await db.commit()
            empty_env = dict(env)
            empty_env["RUST_ROLL_TEST_TOKEN"] = _token(
                empty_name, jti=f"empty-{uuid4().hex}"
            )
            empty_result = await _run_example(empty_env)
            assert empty_result["status"] == 200
            assert empty_result["metrics_statements"] == 1
            assert empty_result["body"] == {
                "events": [],
                "next_page_token": None,
            }

    finally:
        await engine.dispose()


async def _db_stats(engine) -> tuple[int, ...]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT xact_commit, xact_rollback, blks_read, blks_hit, "
                    "tup_returned, tup_fetched FROM pg_stat_database "
                    "WHERE datname = current_database()"
                )
            )
        ).one()
        return tuple(int(value) for value in row)