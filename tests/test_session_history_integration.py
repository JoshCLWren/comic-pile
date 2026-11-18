"""Integration tests for session and history operations."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models import ReadingSession




@pytest.mark.asyncio
async def test_session_restore_preserves_events(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test that session restore preserves session events."""
    from comic_pile.reading_session import create_session_start_snapshot

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    session = ReadingSession(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(roll_event)
    await async_db.commit()

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(rate_event)
    await async_db.commit()

    initial_events_result = await async_db.execute(
        select(Event).where(Event.session_id == session.id)
    )
    initial_events = initial_events_result.scalars().all()

    response = await auth_client.post(f"/api/v1/sessions/{session.id}/restore-session-start")
    assert response.status_code == 200

    final_events_result = await async_db.execute(
        select(Event).where(Event.session_id == session.id)
    )
    final_events = final_events_result.scalars().all()

    assert len(final_events) == len(initial_events)














@pytest.mark.asyncio
async def test_current_session_response_includes_ladder_path(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Test current session response includes dice ladder path."""
    session = ReadingSession(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=4,
        selection_method="random",
    )
    async_db.add(roll_event)

    rate_event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.5,
        issues_read=1,
        die_after=8,
    )
    async_db.add(rate_event)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "ladder_path" in data
    assert "6 → 8" in data["ladder_path"]




