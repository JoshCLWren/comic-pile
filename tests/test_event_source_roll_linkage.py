"""Tests for the Event source-roll linkage contract (issue #1686)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session as SessionModel, User


async def _create_session_with_events(
    async_db: AsyncSession,
) -> tuple[SessionModel, Event]:
    """Create a session containing one roll event; return both."""
    user = User(username="test_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    reading_session = SessionModel(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(reading_session)
    await async_db.flush()

    roll_event = Event(
        type="roll",
        die=6,
        result=4,
        selection_method="random",
        session_id=reading_session.id,
        timestamp=datetime.now(UTC),
    )
    async_db.add(roll_event)
    await async_db.flush()

    return reading_session, roll_event


@pytest.mark.asyncio
async def test_outcome_event_stores_and_retrieves_source_roll(
    async_db: AsyncSession,
) -> None:
    """A linked outcome event round-trips the originating roll event ID."""
    _, roll_event = await _create_session_with_events(async_db)

    outcome_event = Event(
        type="rate",
        rating=4.5,
        issues_read=1,
        die_after=8,
        session_id=roll_event.session_id,
        timestamp=datetime.now(UTC),
        source_roll_event_id=roll_event.id,
    )
    async_db.add(outcome_event)
    await async_db.flush()

    result = await async_db.execute(select(Event).where(Event.id == outcome_event.id))
    loaded = result.scalar_one()

    assert loaded.source_roll_event_id == roll_event.id

    lookup = await async_db.execute(
        select(Event.id).where(Event.source_roll_event_id == roll_event.id)
    )
    assert lookup.scalar_one() == outcome_event.id


@pytest.mark.asyncio
async def test_unlinked_events_load_with_null_source_roll(
    async_db: AsyncSession,
) -> None:
    """Events created without linkage load normally with a NULL source-roll ID."""
    reading_session, roll_event = await _create_session_with_events(async_db)

    historical_rate = Event(
        type="rate",
        rating=3.0,
        issues_read=2,
        die_after=8,
        session_id=reading_session.id,
        timestamp=datetime.now(UTC),
    )
    async_db.add(historical_rate)
    await async_db.flush()

    result = await async_db.execute(
        select(Event).where(Event.id.in_([historical_rate.id, roll_event.id]))
    )
    events = {event.id: event for event in result.scalars().all()}

    assert events[historical_rate.id].source_roll_event_id is None
    assert events[roll_event.id].source_roll_event_id is None


@pytest.mark.asyncio
async def test_invalid_source_roll_reference_is_rejected(
    async_db: AsyncSession,
) -> None:
    """The database contract rejects source rolls that do not exist."""
    _, roll_event = await _create_session_with_events(async_db)

    orphan_outcome = Event(
        type="snooze",
        session_id=roll_event.session_id,
        timestamp=datetime.now(UTC),
        source_roll_event_id=roll_event.id + 10_000_000,
    )
    async_db.add(orphan_outcome)

    with pytest.raises(IntegrityError):
        await async_db.flush()

    await async_db.rollback()


@pytest.mark.asyncio
async def test_deleting_source_roll_preserves_outcome_event(
    async_db: AsyncSession,
) -> None:
    """Deleting the originating roll keeps the outcome event and clears its linkage.

    ON DELETE SET NULL prevents cascade deletes from fanning out from a roll
    into downstream rate/snooze history during event cleanup.
    """
    reading_session, roll_event = await _create_session_with_events(async_db)

    outcome_event = Event(
        type="rate",
        rating=5.0,
        issues_read=1,
        session_id=reading_session.id,
        timestamp=datetime.now(UTC),
        source_roll_event_id=roll_event.id,
    )
    async_db.add(outcome_event)
    await async_db.flush()
    outcome_event_id = outcome_event.id

    await async_db.execute(delete(Event).where(Event.id == roll_event.id))
    await async_db.flush()

    result = await async_db.execute(select(Event).where(Event.id == outcome_event_id))
    surviving_outcome = result.scalar_one()

    assert surviving_outcome.type == "rate"
    assert surviving_outcome.rating == 5.0
    assert surviving_outcome.source_roll_event_id is None


@pytest.mark.asyncio
async def test_source_roll_foreign_key_uses_set_null_delete_action(
    async_db: AsyncSession,
) -> None:
    """The self-referencing foreign key is defined with ON DELETE SET NULL."""
    result = await async_db.execute(
        text("""
            SELECT c.confdeltype
            FROM pg_constraint c
            JOIN pg_class cl ON cl.oid = c.conrelid
            WHERE cl.relname = 'events'
            AND c.conname = 'events_source_roll_event_id_fkey'
        """)
    )
    constraint = result.fetchone()

    assert constraint is not None, "events_source_roll_event_id_fkey should exist"
    assert constraint[0] == "n"  # n = set null


@pytest.mark.asyncio
async def test_source_roll_linkage_index_exists(
    async_db: AsyncSession,
) -> None:
    """Lookup by originating roll event ID is backed by an index."""

    def _get_indexes(sync_conn: Connection) -> list[str]:
        inspector = inspect(sync_conn)
        return [
            str(index["name"])
            for index in inspector.get_indexes("events")
            if index.get("name") is not None
        ]

    indexes = await async_db.connection().run_sync(_get_indexes)

    assert "ix_event_source_roll_event_id" in indexes
