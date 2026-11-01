"""Native read-only session bootstrap versus Python, using disposable schemas only."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Event, Issue, ReadingSession, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from comic_pile.reading_session import (
    get_current_die_for_session,
    resolve_current_session,
)

NOW = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
SECRET = "synthetic-session-parity"
ROOT = Path(__file__).resolve().parents[3]


class Clock(datetime):
    """Freeze application clock without modifying PostgreSQL or wall-clock time."""

    @classmethod
    def now(cls, tz=None):
        """Return the deterministic UTC fixture time."""
        return NOW if tz else NOW.replace(tzinfo=None)


def normalize(value):
    """Normalize only equivalent timestamp spellings, not semantic field differences."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and len(value) > 18 and value[4] == "-" and value[10] == "T":
        return datetime.fromisoformat(value).isoformat()
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", [
    "first", "pending", "recent-event", "expired", "manual", "initialized-mode",
    "invalid-zone", "preserve-zone", "inferred-history", "era-history", "boundary",
])
async def test_session_bootstrap_parity(scenario):
    """Compare the read-only projection, dice, owner gate and zero-write proof."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    schema = f"native_session_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as c:
        await c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            reader, foreign = User(username="session-reader"), User(username="foreign")
            db.add_all([reader, foreign])
            await db.flush()
            thread = Thread(user_id=reader.id, title="Tracked", format="Comic", queue_position=1, total_issues=2)
            legacy = Thread(user_id=reader.id, title="Counter", format="Comic", queue_position=2, issues_remaining=4)
            private = Thread(user_id=foreign.id, title="Private", format="Comic", queue_position=1)
            db.add_all([thread, legacy, private])
            await db.flush()
            issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="read", read_at=NOW)
            next_issue = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread")
            db.add_all([issue, next_issue])
            await db.flush()
            other = ReadingSession(user_id=foreign.id, started_at=NOW, start_die=20)
            db.add(other)
            current = None
            if scenario not in {"first", "inferred-history", "era-history"}:
                current = ReadingSession(user_id=reader.id, started_at=NOW-timedelta(hours=8), start_die=8)
                db.add(current)
                await db.flush()
                if scenario == "pending":
                    current.pending_thread_id = thread.id
                    current.pending_issue_id = issue.id
                    current.pending_thread_updated_at = NOW-timedelta(minutes=5)
                    # A newer session must not defeat the authoritative pending context.
                    db.add(ReadingSession(user_id=reader.id, started_at=NOW, start_die=20))
                elif scenario == "recent-event":
                    db.add(Event(session_id=current.id, type="cancel", timestamp=NOW))
                elif scenario == "boundary":
                    current.started_at = NOW-timedelta(hours=6)
                elif scenario != "expired":
                    current.started_at = NOW
                    current.snoozed_thread_ids = [thread.id]
                    current.skipped_thread_ids = [legacy.id]
                    if scenario == "manual":
                        current.manual_die = 20
                        db.add(Event(session_id=current.id, type="rate", timestamp=NOW,
                                     die_after=20, context={"automatic_die_after": 10}))
                    if scenario == "initialized-mode":
                        current.bandwidth_source = "manual"
                        current.active_bandwidth = "deep"
                        current.predicted_bandwidth = "light"
                        current.bandwidth_confidence = 0.83
                        current.active_intent = "familiar"
                        current.reading_mode_suggested = True
                    if scenario == "preserve-zone":
                        current.timezone = "UTC"
            if scenario in {"inferred-history", "era-history"}:
                history = ReadingSession(user_id=reader.id, started_at=NOW-timedelta(days=1), ended_at=NOW-timedelta(hours=12))
                db.add(history)
                await db.flush()
                for n in range(3):
                    roll = Event(session_id=history.id, type="roll", selected_thread_id=thread.id,
                                 timestamp=NOW-timedelta(hours=10, minutes=n*30))
                    db.add(roll)
                    await db.flush()
                    db.add(Event(session_id=history.id, type="rate", thread_id=thread.id,
                                 issue_id=issue.id, source_roll_event_id=roll.id,
                                 timestamp=roll.timestamp+timedelta(minutes=25 if scenario == "inferred-history" else 0)))
                if scenario == "era-history":
                    identity = ExternalIdentity(provider="comicvine", entity_type="issue", external_id="test",
                                                metadata_json={"cover_date": "1965-01-01"})
                    db.add(identity)
                    await db.flush()
                    db.add(IssueExternalIdentityMapping(issue_id=issue.id, external_identity_id=identity.id,
                                                       status="confirmed"))
            await db.commit()
            reader_id, other_id = reader.id, other.id
        separator = "&" if "?" in url else "?"
        env = {**os.environ,
               "RUST_ROLL_DATABASE_URL": f"{url}{separator}application_name={schema}&options=-csearch_path%3D{schema}",
               "RUST_ROLL_JWT_SECRET": SECRET,
               "RUST_ROLL_TEST_TOKEN": jwt.encode({"sub": "session-reader", "jti": "fixture", "type": "access"}, SECRET, "HS256"),
               "RUST_ROLL_TEST_NOW": str(NOW.timestamp()),
               "RUST_ROLL_TEST_TIMEZONE": "No/SuchZone" if scenario == "invalid-zone" else " America/Chicago ",
               }

        async def native(**extra):
            p = await asyncio.create_subprocess_exec(
                str(ROOT / "native/roll-service/target/debug/examples/session_bootstrap"),
                env={**env, **extra}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out, err = await asyncio.wait_for(p.communicate(), 20)
                return p.returncode, json.loads(out) if out else None, err
            finally:
                if p.returncode is None:
                    p.kill()
                    await p.wait()

        async def durable():
            async with engine.connect() as c:
                result = {}
                for table in ("sessions", "snapshots", "threads", "issues", "events"):
                    rows = await c.scalars(text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY id"))
                    result[table] = [json.loads(row) for row in rows]
                return normalize(result)

        initial = await durable()
        code, _, err = await native(RUST_ROLL_TEST_RESOLVE_ONLY="1")
        assert code == 0, err.decode()
        assert await durable() == initial  # read-only resolution never creates state

        # Read-only oracle: resolve the authoritative session without creating,
        # inferring bandwidth, or applying the browser timezone.
        async with AsyncSession(engine, expire_on_commit=False) as db:
            with patch("comic_pile.reading_session.datetime", Clock):
                resolved = await resolve_current_session(db, reader_id)
                if resolved is None:
                    start_die = int(os.environ.get("START_DIE", "6"))
                    expected = {
                        "id": 0,
                        "user_id": reader_id,
                        "started_at": NOW.isoformat(),
                        "ended_at": None,
                        "start_die": start_die,
                        "manual_die": None,
                        "pending_thread_id": None,
                        "pending_issue_id": None,
                        "pending_thread_updated_at": None,
                        "snoozed_thread_ids": None,
                        "skipped_thread_ids": None,
                        "timezone": None,
                        "predicted_bandwidth": None,
                        "active_bandwidth": None,
                        "bandwidth_confidence": None,
                        "bandwidth_source": None,
                        "bandwidth_version": None,
                        "bandwidth_updated_at": None,
                        "reading_bandwidth": None,
                        "reading_intent": None,
                        "reading_mode_source": None,
                        "reading_mode_suggested": False,
                        "active_intent": None,
                        "predicted_intent": None,
                        "intent_confidence": None,
                        "intent_source": None,
                        "intent_version": None,
                        "session_mode_correction_guidance": None,
                    }
                    current_die = automatic_die = start_die
                else:
                    await db.refresh(resolved)
                    expected = {
                        c.name: getattr(resolved, c.name)
                        for c in ReadingSession.__table__.columns
                    }
                    current_die = await get_current_die_for_session(resolved, db)
                    automatic_die = await get_current_die_for_session(
                        resolved, db, automatic=True
                    )

        code, actual, err = await native()
        assert code == 0, err.decode()
        assert normalize(actual["session"]) == normalize(expected)
        assert actual["current_die"] == current_die
        assert actual["automatic_die"] == automatic_die
        assert "created" not in actual
        # GET bootstrap is strictly read-only: no session, snapshot, event or
        # thread row may change, including on the first request.
        assert await durable() == initial

        code, again, err = await native()
        assert code == 0, err.decode()
        assert "created" not in again
        assert again["session"] == actual["session"]
        assert await durable() == initial
        # Missing and foreign reading-session IDs never resolve through the owner gate.
        for session_id in (other_id, max(x["id"] for x in initial["sessions"]) + 1):
            code, _, err = await native(RUST_ROLL_TEST_SESSION_ID=str(session_id))
            assert code != 0
            assert b"404 Not Found Session not found" in err
        assert await durable() == initial
        # Concurrent GETs return the same authoritative session without writing.
        results = await asyncio.gather(*(native() for _ in range(5)))
        assert all(
            code == 0 and result["session"] == actual["session"]
            for code, result, _ in results
        )
        assert await durable() == initial
    finally:
        await engine.dispose()
        async with admin.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
