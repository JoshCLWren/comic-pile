"""Native v2 analytics metrics against representative PostgreSQL data.

The retired Python analytics handler is not the oracle here. This test seeds
the canonical application schema with an owner and a foreign owner, then checks
the bounded native response directly: counts, completion rate, average ended
session duration, the five-session seven-day window, event distribution,
top-rated ordering/threshold, format normalization, owner isolation, empty
accounts, revoked tokens and stale credential epochs.

Every DB-backed request must issue exactly one PostgreSQL statement, including
the authentication/revocation/credential-epoch check. The payload and database
counter deltas are printed as measurement evidence; only the statement count is
asserted because PostgreSQL statistics are updated asynchronously by other
sessions sharing the database.
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

from app.models import Event, ReadingSession, RevokedToken, Thread, User

SECRET = "synthetic-native-analytics-secret"
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_analytics_metrics"
)


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


@pytest.mark.asyncio
async def test_native_analytics_metrics_is_bounded_owner_scoped_and_one_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve every visible metric and the one-statement budget."""
    monkeypatch.delenv("TEST_ENVIRONMENT", raising=False)
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_name = f"analytics_{uuid4().hex[:12]}"
        stranger_name = f"stranger_{uuid4().hex[:12]}"
        token = _token(owner_name, jti=f"jti-{uuid4().hex}")
        now = datetime.now(UTC).replace(microsecond=123_456)

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=owner_name, created_at=now)
            stranger = User(username=stranger_name, created_at=now)
            db.add_all([owner, stranger])
            await db.flush()

            recent_two_hours = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(days=1),
                ended_at=now - timedelta(days=1) + timedelta(hours=2),
                start_die=8,
            )
            open_session = ReadingSession(
                user_id=owner.id,
                started_at=now,
                ended_at=None,
                start_die=6,
            )
            older_four_hours = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(days=2),
                ended_at=now - timedelta(days=2) + timedelta(hours=4),
                start_die=10,
            )
            older_six_hours = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(days=3),
                ended_at=now - timedelta(days=3) + timedelta(hours=6),
                start_die=12,
            )
            older_eight_hours = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(days=4),
                ended_at=now - timedelta(days=4) + timedelta(hours=8),
                start_die=20,
            )
            outside_window = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(days=8),
                ended_at=now - timedelta(days=8) + timedelta(hours=10),
                start_die=6,
            )
            historic_ended = ReadingSession(
                user_id=owner.id,
                started_at=now - timedelta(days=30),
                ended_at=now - timedelta(days=30) + timedelta(hours=10),
                start_die=6,
            )
            foreign_session = ReadingSession(
                user_id=stranger.id,
                started_at=now,
                ended_at=now + timedelta(hours=100),
                start_die=6,
            )
            db.add_all(
                [
                    recent_two_hours,
                    open_session,
                    older_four_hours,
                    older_six_hours,
                    older_eight_hours,
                    outside_window,
                    historic_ended,
                    foreign_session,
                ]
            )
            await db.flush()

            threads = {
                "digital": Thread(
                    user_id=owner.id,
                    title="Digital First",
                    format="digital",
                    status="active",
                    queue_position=1,
                    last_rating=4.9,
                ),
                "manga": Thread(
                    user_id=owner.id,
                    title="Manga Second",
                    format="Manga",
                    status="active",
                    queue_position=2,
                    last_rating=4.7,
                ),
                "comic": Thread(
                    user_id=owner.id,
                    title="Comic Third",
                    format=" Comic ",
                    status="completed",
                    queue_position=3,
                    last_rating=4.5,
                ),
                "comics": Thread(
                    user_id=owner.id,
                    title="Comics Fourth",
                    format="comics",
                    status="active",
                    queue_position=4,
                    last_rating=4.2,
                ),
                "threshold": Thread(
                    user_id=owner.id,
                    title="Threshold Fifth",
                    format="Comic",
                    status="active",
                    queue_position=5,
                    last_rating=4.0,
                ),
                "below": Thread(
                    user_id=owner.id,
                    title="Below Threshold",
                    format="Comic",
                    status="active",
                    queue_position=6,
                    last_rating=3.9,
                ),
                "foreign": Thread(
                    user_id=stranger.id,
                    title="Foreign Perfect",
                    format="Comic",
                    status="active",
                    queue_position=1,
                    last_rating=5.0,
                ),
            }
            db.add_all(threads.values())
            await db.flush()

            db.add_all(
                [
                    Event(
                        type="roll",
                        session_id=open_session.id,
                        user_id=owner.id,
                        timestamp=now,
                    ),
                    Event(
                        type="rate",
                        session_id=recent_two_hours.id,
                        user_id=owner.id,
                        timestamp=now,
                    ),
                    Event(
                        type="undo",
                        session_id=older_four_hours.id,
                        user_id=owner.id,
                        timestamp=now,
                    ),
                    Event(
                        type="snooze",
                        session_id=older_six_hours.id,
                        user_id=owner.id,
                        timestamp=now,
                    ),
                    Event(
                        type="foreign-only",
                        session_id=foreign_session.id,
                        user_id=stranger.id,
                        timestamp=now,
                    ),
                ]
            )
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
            expected = {
                "total_threads": 6,
                "active_threads": 5,
                "completed_threads": 1,
                "completion_rate": 16.7,
                "average_session_hours": 6.7,
                "recent_sessions": [
                    {
                        "id": open_session.id,
                        "started_at": open_session.started_at.isoformat(),
                        "ended_at": None,
                        "start_die": open_session.start_die,
                    },
                    {
                        "id": recent_two_hours.id,
                        "started_at": recent_two_hours.started_at.isoformat(),
                        "ended_at": recent_two_hours.ended_at.isoformat(),
                        "start_die": recent_two_hours.start_die,
                    },
                    {
                        "id": older_four_hours.id,
                        "started_at": older_four_hours.started_at.isoformat(),
                        "ended_at": older_four_hours.ended_at.isoformat(),
                        "start_die": older_four_hours.start_die,
                    },
                    {
                        "id": older_six_hours.id,
                        "started_at": older_six_hours.started_at.isoformat(),
                        "ended_at": older_six_hours.ended_at.isoformat(),
                        "start_die": older_six_hours.start_die,
                    },
                    {
                        "id": older_eight_hours.id,
                        "started_at": older_eight_hours.started_at.isoformat(),
                        "ended_at": older_eight_hours.ended_at.isoformat(),
                        "start_die": older_eight_hours.start_die,
                    },
                ],
                "event_stats": {"rate": 1, "roll": 1, "snooze": 1, "undo": 1},
                "top_rated_threads": [
                    {
                        "id": threads["digital"].id,
                        "title": "Digital First",
                        "rating": 4.9,
                        "format": "Digital",
                    },
                    {
                        "id": threads["manga"].id,
                        "title": "Manga Second",
                        "rating": 4.7,
                        "format": "Manga",
                    },
                    {
                        "id": threads["comic"].id,
                        "title": "Comic Third",
                        "rating": 4.5,
                        "format": "Comic",
                    },
                    {
                        "id": threads["comics"].id,
                        "title": "Comics Fourth",
                        "rating": 4.2,
                        "format": "Comic",
                    },
                    {
                        "id": threads["threshold"].id,
                        "title": "Threshold Fifth",
                        "rating": 4.0,
                        "format": "Comic",
                    },
                ],
            }
            assert result["body"] == expected
            print(
                "native analytics budget: "
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

            empty_name = f"empty_{uuid4().hex[:12]}"
            empty = User(username=empty_name, created_at=now)
            db.add(empty)
            await db.commit()
            empty_env = dict(env)
            empty_env["RUST_ROLL_TEST_TOKEN"] = _token(
                empty_name, jti=f"empty-{uuid4().hex}"
            )
            empty_result = await _run_example(empty_env)
            assert empty_result["status"] == 200, empty_result
            assert empty_result["metrics_statements"] == 1
            assert empty_result["body"] == {
                "total_threads": 0,
                "active_threads": 0,
                "completed_threads": 0,
                "completion_rate": 0.0,
                "average_session_hours": 0.0,
                "recent_sessions": [],
                "event_stats": {},
                "top_rated_threads": [],
            }

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

            await db.execute(
                text("UPDATE users SET password_changed_at = now() WHERE id = :id"),
                {"id": owner.id},
            )
            await db.commit()
            stale_result = await _run_example(
                {
                    **env,
                    "RUST_ROLL_TEST_TOKEN": _token(
                        owner_name, jti=f"stale-{uuid4().hex}", password_epoch=0
                    ),
                }
            )
            assert stale_result["status"] == 401
            assert stale_result["body"] == {
                "detail": "Password changed; please sign in again."
            }
            assert stale_result["metrics_statements"] == 1
    finally:
        await engine.dispose()
