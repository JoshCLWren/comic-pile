"""Tests for deadlock handling in concurrent operations."""

from datetime import UTC, datetime

import pytest
from app.models import Session as SessionModel, Snapshot
from comic_pile.session import get_or_create
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_or_create_sequential(async_db: AsyncSession) -> None:
    """Test that sequential get_or_create calls work correctly.

    This verifies that session creation logic works properly when called
    multiple times in sequence.
    """
    await async_db.execute(delete(Snapshot))
    await async_db.execute(delete(SessionModel))
    await async_db.commit()

    results = []
    exceptions = []

    for _ in range(10):
        try:
            session = await get_or_create(async_db, user_id=1)
            results.append((session.id, session.started_at))
        except Exception as e:
            exceptions.append(e)

    assert len(exceptions) == 0, f"Operations raised exceptions: {exceptions}"
    assert len(results) == 10, "All calls should complete"

    session_ids = [r[0] for r in results]
    assert len(set(session_ids)) == 1, "All calls should return the same session ID"


@pytest.mark.asyncio
async def test_get_or_create_after_end_session(async_db: AsyncSession) -> None:
    """Test that get_or_create creates new session after previous one ends.

    Regression test for BUG-158: Verifies proper session management.
    """
    await async_db.execute(delete(Snapshot))
    await async_db.execute(delete(SessionModel))
    await async_db.commit()

    session1 = await get_or_create(async_db, user_id=1)
    assert session1 is not None
    assert session1.ended_at is None

    session1.ended_at = datetime.now(UTC)
    await async_db.commit()
    await async_db.refresh(session1)

    session2 = await get_or_create(async_db, user_id=1)
    assert session2 is not None
    assert session2.ended_at is None
    assert session2.id != session1.id, "Should create a new session"
