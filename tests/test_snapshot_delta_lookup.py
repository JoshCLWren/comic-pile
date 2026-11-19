"""Queryable latest-delta lookup regressions for issue #3218.

Covers the acceptance contract: writer classification and the additive
migration backfill (the Python undo lookup and its routes are retired;
Rust owns undo).
"""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Snapshot, Thread, User
from app.models import ReadingSession
from app.services.snapshot_contract import (
    SNAPSHOT_KIND_DELTA,
    SNAPSHOT_KIND_LEGACY_FULL,
    SNAPSHOT_KIND_SESSION_START,
    SNAPSHOT_KIND_UNKNOWN,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
    classify_snapshot,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "f2a3b4c5d6e7_add_snapshot_kind_columns.py"
)


def _migration_backfill_sql() -> str:
    """Load the exact BACKFILL_SQL from the additive migration file."""
    spec = importlib.util.spec_from_file_location(
        "snapshot_kind_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backfill_sql: str = module.BACKFILL_SQL
    return backfill_sql


def _requires_postgres(db_engine: AsyncEngine) -> None:
    """Skip PostgreSQL-only coverage when the suite runs on SQLite."""
    if db_engine.dialect.name != "postgresql":
        # Requires PostgreSQL (PG-specific plan/index coverage).
        # Note: ty's pytest stub rejects the `reason` kwarg (stub bug), so the
        # message lives here instead of in the skip() call.
        pytest.skip()


def _delta_payload(thread_id: int, version: object = SNAPSHOT_VERSION) -> dict:
    """Build a minimal versioned delta payload for one thread."""
    return {
        SNAPSHOT_VERSION_KEY: version,
        str(thread_id): {"issues_remaining": 4, "queue_position": 1},
    }


def _legacy_payload(thread_id: int) -> dict:
    """Build an unversioned legacy full-library payload."""
    return {str(thread_id): {"issues_remaining": 4, "queue_position": 1}}




async def _make_session_with_thread(
    async_db: AsyncSession, user_id: int
) -> tuple[ReadingSession, Thread]:
    """Create one session plus one thread for snapshot tests."""
    session = ReadingSession(start_die=6, user_id=user_id)
    thread = Thread(
        title="Delta Lookup Thread",
        format="comic",
        issues_remaining=4,
        queue_position=1,
        status="active",
        user_id=user_id,
    )
    async_db.add_all([session, thread])
    await async_db.flush()
    return session, thread


async def _make_event(async_db: AsyncSession, session_id: int) -> Event:
    """Create a rate event to link snapshots to."""
    event = Event(type="rate", session_id=session_id, rating=5.0, die=6, die_after=8)
    async_db.add(event)
    await async_db.flush()
    return event






def test_classify_snapshot_contract_cases() -> None:
    """Unit parity for versioned, unsupported, legacy and malformed payloads."""
    assert classify_snapshot({SNAPSHOT_VERSION_KEY: 2}) == (
        SNAPSHOT_KIND_DELTA,
        SNAPSHOT_VERSION,
    )
    assert classify_snapshot({SNAPSHOT_VERSION_KEY: 2.0}) == (
        SNAPSHOT_KIND_DELTA,
        SNAPSHOT_VERSION,
    )
    assert classify_snapshot({SNAPSHOT_VERSION_KEY: 3}) == (SNAPSHOT_KIND_DELTA, 3)
    assert classify_snapshot({SNAPSHOT_VERSION_KEY: "2"}) == (
        SNAPSHOT_KIND_LEGACY_FULL,
        None,
    )
    assert classify_snapshot({SNAPSHOT_VERSION_KEY: True}) == (
        SNAPSHOT_KIND_LEGACY_FULL,
        None,
    )
    assert classify_snapshot(
        {"1": {}}, description="Session start", event_id=None
    ) == (SNAPSHOT_KIND_SESSION_START, None)
    assert classify_snapshot({"1": {}}, description="Session start", event_id=7) == (
        SNAPSHOT_KIND_LEGACY_FULL,
        None,
    )
    assert classify_snapshot({"1": {}}) == (SNAPSHOT_KIND_LEGACY_FULL, None)
    assert classify_snapshot("oops") == (SNAPSHOT_KIND_UNKNOWN, None)
    assert classify_snapshot(None) == (SNAPSHOT_KIND_UNKNOWN, None)


@pytest.mark.asyncio
async def test_snapshot_kind_backfill_handles_mixed_payloads(
    async_db: AsyncSession, db_engine: AsyncEngine, default_user: User
) -> None:
    """Migration backfill classifies without dropping NULL/malformed rows."""
    _requires_postgres(db_engine)
    session, thread = await _make_session_with_thread(async_db, default_user.id)
    event = await _make_event(async_db, session.id)

    malformed_payload: dict = json.loads('"oops"')
    payloads: list[tuple[dict, str | None, int | None]] = [
        (_legacy_payload(thread.id), "After rating", event.id),
        ({"1": {}}, "Session start", None),
        (_delta_payload(thread.id), "After rating", event.id),
        (_delta_payload(thread.id, version=3), "After rating", event.id),
        (_delta_payload(thread.id, version="2"), "After rating", event.id),
        (malformed_payload, "After rating", event.id),
        ({}, "After rating", event.id),
    ]
    for payload, description, event_id in payloads:
        async_db.add(
            Snapshot(
                session_id=session.id,
                event_id=event_id,
                thread_states=payload,
                description=description,
            )
        )
    await async_db.flush()
    before = await async_db.scalar(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
    )

    await async_db.execute(text(_migration_backfill_sql()))
    await async_db.flush()

    after_rows = (
        await async_db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .order_by(Snapshot.id)
        )
    ).scalars().all()
    assert before == len(payloads)
    assert [(row.snapshot_kind, row.schema_version) for row in after_rows] == [
        (SNAPSHOT_KIND_LEGACY_FULL, None),
        (SNAPSHOT_KIND_SESSION_START, None),
        (SNAPSHOT_KIND_DELTA, SNAPSHOT_VERSION),
        (SNAPSHOT_KIND_DELTA, 3),
        # String versions are not numbers: legacy, never delta targets.
        (SNAPSHOT_KIND_LEGACY_FULL, None),
        (SNAPSHOT_KIND_UNKNOWN, None),
        (SNAPSHOT_KIND_LEGACY_FULL, None),
    ]




