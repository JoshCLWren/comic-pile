"""Concurrency regression coverage for current-session creation."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Session
from comic_pile.session import get_or_create
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_concurrent_get_or_create_reuses_one_authoritative_session(
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Concurrent bootstrap-style calls must not manufacture duplicate sessions."""
    user = await get_or_create_user_async(async_db_committed, username="session_race_user")
    user_id = user.id

    session_maker = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def resolve_session_id() -> int:
        async with session_maker() as db:
            session = await get_or_create(db, user_id=user_id)
            return session.id

    session_ids = await asyncio.gather(*(resolve_session_id() for _ in range(8)))

    assert len(set(session_ids)) == 1

    count_result = await async_db_committed.execute(
        select(func.count())
        .select_from(Session)
        .where(Session.user_id == user_id)
        .where(Session.ended_at.is_(None))
    )
    assert count_result.scalar_one() == 1
