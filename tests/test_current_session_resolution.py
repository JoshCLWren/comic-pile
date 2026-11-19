"""Regression coverage for authoritative current-session resolution."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadingSession
from app.models import User
from comic_pile.reading_session import is_active


@pytest.mark.asyncio
async def test_is_active_rejects_timestamp_shared_by_multiple_users(
    async_db: AsyncSession,
) -> None:
    """A non-unique start timestamp must never confer cross-user session authority."""
    started_at = datetime.now(UTC) - timedelta(minutes=30)
    users = [User(username="timestamp-owner-a"), User(username="timestamp-owner-b")]
    async_db.add_all(users)
    await async_db.flush()

    sessions = [
        ReadingSession(started_at=started_at, start_die=6, user_id=user.id)
        for user in users
    ]
    async_db.add_all(sessions)
    await async_db.commit()

    assert await is_active(started_at, None, async_db) is False
