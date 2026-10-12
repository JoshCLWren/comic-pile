"""Queryable latest-delta lookup regressions for issue #3218.

Covers the acceptance contract: mixed-stack parity with the supported undo
contract, bounded retrieval on a large stack, writer classification, the
additive migration backfill, and the bounded legacy fallback.
"""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy import event as sa_event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Snapshot, Thread, User
from app.models import ReadingSession
from app.repositories.undo_snapshot_repository import UndoSnapshotRepository
from app.services.snapshot_contract import (
    LEGACY_DELTA_FALLBACK_SCAN_LIMIT,
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


async def _legacy_contract_lookup(
    async_db: AsyncSession, session_id: int
) -> Snapshot | None:
    """Replicate the pre-#3218 full-stack Python scan for parity checks."""
    result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
    )
    for snapshot in result.scalars().all():
        thread_states = snapshot.thread_states
        if isinstance(thread_states, dict) and (
            thread_states.get(SNAPSHOT_VERSION_KEY) == SNAPSHOT_VERSION
        ):
            return snapshot
    return None


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


@pytest.mark.asyncio
async def test_latest_delta_parity_across_mixed_stack(
    async_db: AsyncSession, default_user: User
) -> None:
    """Mixed legacy/start/v2/unsupported/consumed/tied rows resolve identically."""
    session, thread = await _make_session_with_thread(async_db, default_user.id)
    other_session = ReadingSession(start_die=6, user_id=default_user.id)
    async_db.add(other_session)
    await async_db.flush()
    event = await _make_event(async_db, session.id)
    base = datetime.now(UTC)

    async def add_row(
        payload: dict,
        created_at: datetime,
        *,
        description: str | None = "After rating",
        event_id: int | None = None,
        no_event: bool = False,
        session_id: int | None = None,
    ) -> Snapshot:
        row = Snapshot(
            session_id=session_id or session.id,
            event_id=None if no_event else (event_id or event.id),
            thread_states=payload,
            created_at=created_at,
            description=description,
        )
        async_db.add(row)
        await async_db.flush()
        return row

    await add_row(
        _legacy_payload(thread.id),
        base,
        description="Session start",
        no_event=True,
    )
    await add_row(_legacy_payload(thread.id), base + timedelta(seconds=1))
    v2_older = await add_row(
        _delta_payload(thread.id), base + timedelta(seconds=2)
    )
    await add_row(
        _delta_payload(thread.id, version=3), base + timedelta(seconds=3)
    )
    await add_row(
        _delta_payload(thread.id, version="2"), base + timedelta(seconds=4)
    )
    v2_newest = await add_row(
        _delta_payload(thread.id), base + timedelta(seconds=5)
    )
    # Tied timestamps resolve deterministically by id; these are the newest.
    tie_low = await add_row(
        _delta_payload(thread.id), base + timedelta(seconds=6)
    )
    tie_high = await add_row(
        _delta_payload(thread.id), base + timedelta(seconds=6)
    )
    assert tie_high.id > tie_low.id
    # Malformed payloads (valid JSON, not an object) never match the contract.
    malformed_payload: dict = json.loads('"oops"')
    await add_row(malformed_payload, base + timedelta(seconds=7))
    # Another session's newer delta must not leak across session ownership.
    await add_row(
        _delta_payload(thread.id),
        base + timedelta(seconds=60),
        session_id=other_session.id,
    )
    # A consumed (deleted) snapshot behaves as if it never existed.
    consumed = await add_row(
        _delta_payload(thread.id), base + timedelta(seconds=90)
    )
    await async_db.execute(text("DELETE FROM snapshots WHERE id = :sid"), {"sid": consumed.id})

    repository = UndoSnapshotRepository(async_db)
    # Phase 1: unclassified rows exercise the bounded legacy fallback.
    fallback_result = await repository.get_latest_delta_snapshot(session.id)
    legacy_result = await _legacy_contract_lookup(async_db, session.id)
    assert fallback_result is not None and legacy_result is not None
    assert fallback_result.id == legacy_result.id == tie_high.id
    assert v2_newest.id != tie_high.id
    assert v2_older.id != tie_high.id

    # Phase 2: the same stack classified exercises the indexed SQL path.
    rows_result = await async_db.execute(
        select(Snapshot).where(Snapshot.session_id == session.id)
    )
    for row in rows_result.scalars().all():
        kind, version = classify_snapshot(
            row.thread_states, description=row.description, event_id=row.event_id
        )
        row.snapshot_kind = kind
        row.schema_version = version
    await async_db.flush()
    indexed_result = await repository.get_latest_delta_snapshot(session.id)
    assert indexed_result is not None
    assert indexed_result.id == tie_high.id


@pytest.mark.asyncio
async def test_latest_delta_lookup_is_bounded_on_large_stack(
    async_db: AsyncSession, db_engine: AsyncEngine, default_user: User
) -> None:
    """10k historical snapshots: at most one payload fetched via LIMIT 1."""
    _requires_postgres(db_engine)
    session, thread = await _make_session_with_thread(async_db, default_user.id)
    event = await _make_event(async_db, session.id)
    base = datetime.now(UTC)
    rows = [
        Snapshot(
            session_id=session.id,
            event_id=event.id,
            thread_states=_legacy_payload(thread.id),
            created_at=base + timedelta(milliseconds=index),
            description="After rating",
            snapshot_kind=SNAPSHOT_KIND_LEGACY_FULL,
            schema_version=None,
        )
        for index in range(10_000)
    ]
    target = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states=_delta_payload(thread.id),
        created_at=base + timedelta(seconds=60),
        description="After rating",
        snapshot_kind=SNAPSHOT_KIND_DELTA,
        schema_version=SNAPSHOT_VERSION,
    )
    async_db.add_all([*rows, target])
    await async_db.flush()
    await async_db.execute(text("ANALYZE snapshots"))

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(str(statement))

    repository = UndoSnapshotRepository(async_db)
    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        found = await repository.get_latest_delta_snapshot(session.id)
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert found is not None
    assert found.id == target.id

    snapshot_selects = [
        statement
        for statement in statements
        if "from snapshots" in statement.lower() and statement.strip().lower().startswith("select")
    ]
    # Indexed hit plus one empty unclassified probe: bounded either way.
    assert len(snapshot_selects) <= 2, f"Unbounded snapshot reads: {snapshot_selects}"
    assert snapshot_selects != []
    for statement in snapshot_selects:
        assert "limit" in statement.lower(), f"Unbounded select: {statement}"

    plan_result = await async_db.execute(
        text(
            "EXPLAIN SELECT id FROM snapshots WHERE session_id = :sid "
            "AND snapshot_kind = 'delta' AND schema_version = 2 "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ),
        {"sid": session.id},
    )
    plan = "\n".join(str(row[0]) for row in plan_result.all()).lower()
    assert "ix_snapshot_session_delta_lookup" in plan, f"Index not used: {plan}"

    def _read_indexes(sync_conn: object) -> list[str]:
        assert isinstance(sync_conn, Connection)
        return [
            str(index["name"]) for index in inspect(sync_conn).get_indexes("snapshots")
        ]

    async with db_engine.connect() as connection:
        index_names = await connection.run_sync(_read_indexes)
    assert "ix_snapshot_session_delta_lookup" in index_names


@pytest.mark.asyncio
async def test_snapshot_writers_keep_classification_correct(
    async_db: AsyncSession, default_user: User
) -> None:
    """Rating delta, legacy and session-start writers classify on creation."""
    from app.services.rate_service import snapshot_thread_states
    from comic_pile.reading_session import create_session_start_snapshot

    session, thread = await _make_session_with_thread(async_db, default_user.id)
    event = await _make_event(async_db, session.id)

    await snapshot_thread_states(
        async_db,
        session.id,
        event.id,
        default_user.id,
        commit=False,
        rated_thread_id=thread.id,
        rated_thread_pre_state={"title": thread.title},
        queue_position_changes={thread.id: 1},
        blocked_changes={thread.id: False},
        pre_session_state={"start_die": 6},
    )
    await snapshot_thread_states(
        async_db, session.id, event.id, default_user.id, commit=False
    )
    await async_db.flush()

    written = (
        await async_db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .order_by(Snapshot.id)
        )
    ).scalars().all()
    assert len(written) == 2
    assert (written[0].snapshot_kind, written[0].schema_version) == (
        SNAPSHOT_KIND_DELTA,
        SNAPSHOT_VERSION,
    )
    assert (written[1].snapshot_kind, written[1].schema_version) == (
        SNAPSHOT_KIND_LEGACY_FULL,
        None,
    )

    await create_session_start_snapshot(async_db, session)
    start_snapshot = (
        await async_db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .where(Snapshot.description == "Session start")
            .order_by(Snapshot.id.desc())
        )
    ).scalars().first()
    assert start_snapshot is not None
    assert (start_snapshot.snapshot_kind, start_snapshot.schema_version) == (
        SNAPSHOT_KIND_SESSION_START,
        None,
    )


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


@pytest.mark.asyncio
async def test_unclassified_fallback_is_bounded_and_session_scoped(
    async_db: AsyncSession, db_engine: AsyncEngine, default_user: User
) -> None:
    """NULL-kind deltas resolve with a LIMIT-bound probe; undo stays isolated."""
    session, thread = await _make_session_with_thread(async_db, default_user.id)
    other_session = ReadingSession(start_die=6, user_id=default_user.id)
    async_db.add(other_session)
    await async_db.flush()
    event = await _make_event(async_db, session.id)
    base = datetime.now(UTC)

    buried = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states=_delta_payload(thread.id),
        created_at=base,
        description="After rating",
    )
    newer_legacy = Snapshot(
        session_id=session.id,
        event_id=event.id,
        thread_states=_legacy_payload(thread.id),
        created_at=base + timedelta(seconds=5),
        description="After rating",
        snapshot_kind=SNAPSHOT_KIND_LEGACY_FULL,
    )
    other_delta = Snapshot(
        session_id=other_session.id,
        event_id=event.id,
        thread_states=_delta_payload(thread.id),
        created_at=base + timedelta(seconds=60),
        description="After rating",
    )
    async_db.add_all([buried, newer_legacy, other_delta])
    await async_db.flush()

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(str(statement))

    repository = UndoSnapshotRepository(async_db)
    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        found = await repository.get_latest_delta_snapshot(session.id)
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert found is not None
    assert found.id == buried.id

    fallback_selects = [
        statement
        for statement in statements
        if "from snapshots" in statement.lower()
        and "snapshot_kind" in statement.lower()
        and statement.strip().lower().startswith("select")
    ]
    assert fallback_selects != []
    for statement in fallback_selects:
        assert "limit" in statement.lower(), f"Unbounded fallback: {statement}"
    assert LEGACY_DELTA_FALLBACK_SCAN_LIMIT == 500

    other_found = await repository.get_latest_delta_snapshot(other_session.id)
    assert other_found is not None
    assert other_found.id == other_delta.id


@pytest.mark.asyncio
async def test_delta_undo_consumes_only_latest_classified_snapshot(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Stack-safe undo keeps LIFO semantics on classified delta rows."""
    session, thread = await _make_session_with_thread(async_db, default_user.id)
    first_event = await _make_event(async_db, session.id)
    second_event = await _make_event(async_db, session.id)
    base = datetime.now(UTC)

    for event, seconds in ((first_event, 0), (second_event, 1)):
        async_db.add(
            Snapshot(
                session_id=session.id,
                event_id=event.id,
                thread_states=_delta_payload(thread.id),
                session_state={"start_die": 6},
                created_at=base + timedelta(seconds=seconds),
                description="After rating",
                snapshot_kind=SNAPSHOT_KIND_DELTA,
                schema_version=SNAPSHOT_VERSION,
            )
        )
    await async_db.commit()
    await async_db.refresh(thread)

    snapshots = (
        await async_db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session.id)
            .order_by(Snapshot.id)
        )
    ).scalars().all()
    stale_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshots[0].id}"
    )
    assert stale_response.status_code == 409

    latest_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshots[1].id}"
    )
    assert latest_response.status_code == 200

    remaining = (
        await async_db.execute(
            select(Snapshot.id).where(Snapshot.session_id == session.id)
        )
    ).scalars().all()
    assert remaining == [snapshots[0].id]
