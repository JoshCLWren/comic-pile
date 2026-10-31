"""Native session state AND durable writes versus Python, using disposable schemas only."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from jose import jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Event, Issue, ReadingSession, Snapshot, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from comic_pile.reading_session import get_current_die_for_session, get_or_create

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
    """Compare every persisted field, dice, checkpoints, retry effects and foreign access."""
    url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if url is None:
        pytest.skip(
            "disposable test Postgres (RUST_ROLL_TEST_DATABASE_URL) is not available"
        )
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
        # Run Python in a transaction externally rolled back to give Rust identical initial data.
        async with engine.connect() as connection:
            outer = await connection.begin()
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as db:
                with patch("comic_pile.reading_session.datetime", Clock), patch("comic_pile.bandwidth.datetime", Clock), patch("app.models.reading_session.datetime", Clock):
                    s = await get_or_create(db, reader_id)
                    await db.refresh(s)
                    if s.timezone is None:
                        try:
                            zone = env["RUST_ROLL_TEST_TIMEZONE"].strip()
                            ZoneInfo(zone)
                            s.timezone = zone
                            await db.commit()
                        except (ValueError, KeyError):
                            pass
                    current_die = await get_current_die_for_session(s, db)
                    automatic_die = await get_current_die_for_session(s, db, automatic=True)
                    expected = {c.name: getattr(s, c.name) for c in ReadingSession.__table__.columns}
                    checkpoints = (await db.scalars(select(Snapshot).where(Snapshot.session_id == s.id))).all()
                    expected_snapshots = [normalize({"thread_states": x.thread_states, "session_state": x.session_state,
                                                   "snapshot_kind": x.snapshot_kind, "schema_version": x.schema_version}) for x in checkpoints]
            await outer.rollback()
        # Sequence values are not transactional. Reset to the fixture's last identity.
        async with engine.begin() as c:
            await c.execute(text("SELECT setval(pg_get_serial_sequence('sessions','id'), (SELECT max(id) FROM sessions))"))
        code, actual, err = await native()
        assert code == 0, err.decode()
        assert normalize(actual["session"]) == normalize(expected)
        assert actual["current_die"] == current_die
        assert actual["automatic_die"] == automatic_die
        async with AsyncSession(engine) as db:
            checkpoints = (await db.scalars(select(Snapshot).where(Snapshot.session_id == actual["session"]["id"]))).all()
            actual_snapshots = [normalize({"thread_states": x.thread_states, "session_state": x.session_state,
                                          "snapshot_kind": x.snapshot_kind, "schema_version": x.schema_version}) for x in checkpoints]
        assert actual_snapshots == expected_snapshots
        after = await durable()
        for table in ("threads", "issues", "events"):
            assert after[table] == initial[table]
        code, again, err = await native()
        assert code == 0, err.decode()
        assert not again["created"]
        assert again["session"] == actual["session"]
        assert await durable() == after
        # Missing and foreign reading-session IDs never resolve through the owner gate.
        for session_id in (other_id, max(x["id"] for x in after["sessions"])+1):
            code, _, err = await native(RUST_ROLL_TEST_SESSION_ID=str(session_id))
            assert code != 0
            assert b"404 Not Found Session not found" in err
        assert await durable() == after
        # Concurrent GETs serialize and return the same authoritative session.
        results = await asyncio.gather(*(native() for _ in range(5)))
        assert all(code == 0 and result["session"] == actual["session"] for code, result, _ in results)
        assert await durable() == after
        if scenario == "first":
            # Fresh first-session concurrency, rather than only concurrent reuse.
            async with engine.begin() as c:
                await c.execute(text("DELETE FROM sessions WHERE user_id=:reader"), {"reader": reader_id})
            results = await asyncio.gather(*(native() for _ in range(5)))
            assert all(code == 0 for code, _, _ in results)
            assert len({result["session"]["id"] for _, result, _ in results}) == 1
            assert sum(result["created"] for _, result, _ in results) == 1
            async with engine.begin() as c:
                await c.execute(text("DELETE FROM sessions WHERE user_id=:reader"), {"reader": reader_id})
                # A checkpoint failure must roll back the newly inserted session too.
                await c.execute(text("""CREATE FUNCTION fail_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'synthetic checkpoint failure'; END $$"""))
                await c.execute(text("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON snapshots FOR EACH ROW EXECUTE FUNCTION fail_checkpoint()"))
            before_failure = await durable()
            code, _, err = await native()
            assert code != 0 and b"500 Internal Server Error" in err
            assert await durable() == before_failure
            async with engine.begin() as c:
                await c.execute(text("DROP TRIGGER fail_checkpoint ON snapshots"))
                await c.execute(text("""CREATE FUNCTION wait_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN PERFORM pg_advisory_xact_lock(-731707); RETURN NEW; END $$"""))
                await c.execute(text("CREATE TRIGGER wait_checkpoint BEFORE INSERT ON snapshots FOR EACH ROW EXECUTE FUNCTION wait_checkpoint()"))
            # Cancel bootstrap_at in Rust, not the child process: the future must
            # drop its in-flight transaction while the pool stays alive.
            # One connection forces the post-cancel checkout to encounter a busy
            # connection if Pending fails to discard it.
            async with engine.begin() as blocker:
                await blocker.execute(text("SELECT pg_advisory_xact_lock(-731707)"))
                p = await asyncio.create_subprocess_exec(
                    str(ROOT / "native/roll-service/target/debug/examples/session_bootstrap"),
                    env={**env, "RUST_ROLL_TEST_CANCEL_ON_STDIN": "1", "RUST_ROLL_POOL_SIZE": "1"},
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    for _ in range(200):
                        async with admin.connect() as c:
                            waiting = await c.scalar(text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE application_name=:name AND wait_event='advisory'"
                            ), {"name": schema})
                        if waiting:
                            break
                        await asyncio.sleep(0.01)
                    else:
                        pytest.fail("native checkpoint did not reach controlled lock")
                    assert p.stdin is not None
                    p.stdin.write(b"x")
                    await p.stdin.drain()
                    out, err = await asyncio.wait_for(p.communicate(), 10)
                    assert p.returncode == 0, err.decode()
                    assert json.loads(out) == {"cancelled": True, "checkout_usable": True}
                    # The process has exited without releasing the blocking lock.
                    # No uncommitted session or snapshot can later become visible.
                    assert await durable() == before_failure
                finally:
                    if p.returncode is None:
                        p.kill()
                        await p.wait()
            assert await durable() == before_failure
            async with engine.begin() as c:
                await c.execute(text("DROP TRIGGER wait_checkpoint ON snapshots"))
            # One synthetic deadlock rolls back; the next attempt creates one checkpoint.
            async with engine.begin() as c:
                await c.execute(text("CREATE SEQUENCE checkpoint_attempt"))
                await c.execute(text("""CREATE FUNCTION retry_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                      IF nextval('checkpoint_attempt') = 1 THEN
                        RAISE EXCEPTION 'synthetic deadlock' USING ERRCODE='40P01';
                      END IF;
                      RETURN NEW;
                    END $$"""))
                await c.execute(text("CREATE TRIGGER retry_checkpoint BEFORE INSERT ON snapshots FOR EACH ROW EXECUTE FUNCTION retry_checkpoint()"))
            code, recovered, err = await native()
            assert code == 0 and recovered["created"], err.decode()
            async with engine.connect() as c:
                assert await c.scalar(text("SELECT last_value FROM checkpoint_attempt")) == 2
                assert await c.scalar(text("SELECT count(*) FROM sessions WHERE user_id=:reader"), {"reader": reader_id}) == 1
                assert await c.scalar(text("SELECT count(*) FROM snapshots")) == 1
    finally:
        await engine.dispose()
        async with admin.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
