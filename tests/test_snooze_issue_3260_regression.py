"""Focused regression test for issue #3260 — snooze/unsnooze must record events."""

from datetime import datetime, timezone

import pytest

from app.models import Event, Thread, ReadingSession
from app.services.snooze_service import snooze_thread, unsnooze_thread


@pytest.mark.asyncio
async def test_snooze_records_event_and_clears_pending(db, user, session_factory):
    from app.repositories.reading_session_repository import fetch_active_reading_session

    # Create a session with a pending thread
    session = await session_factory(db, user_id=user.id, pending_thread_id=1)
    # Ensure thread exists
    thread = Thread(id=1, title="Test", user_id=user.id, format="omnibus",
                    issues_remaining=3, queue_position=1)
    db.add(thread)
    await db.flush()

    result = await snooze_thread(db, user.id)
    assert result is not None
    # Session should have no pending thread
    updated = await fetch_active_reading_session(db, user.id)
    assert updated is not None
    assert updated.pending_thread_id is None
    # A snooze event should exist
    events = await db.execute(
        __import__("sqlalchemy").select(Event).where(Event.type == "snooze")
    )
    rows = events.scalars().all()
    assert any(e.session_id == session.id for e in rows)


@pytest.mark.asyncio
async def test_unsnooze_removes_from_snoozed(db, user, session_factory):
    from app.repositories.reading_session_repository import fetch_active_reading_session

    session = await session_factory(db, user_id=user.id, snoozed_thread_ids=[42])
    result = await unsnooze_thread(db, user.id, thread_id=42)
    assert result is not None
    updated = await fetch_active_reading_session(db, user.id)
    assert updated is not None
    assert 42 not in (updated.snoozed_thread_ids or [])
    events = await db.execute(
        __import__("sqlalchemy").select(Event).where(Event.type == "unsnooze")
    )
    assert any(e.thread_id == 42 for e in events.scalars().all())
