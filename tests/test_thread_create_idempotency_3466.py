"""Regression tests for #3466: duplicate Create Series submissions merge.

Double-clicking "Create Series" submits the same payload twice. The create
endpoint's idempotency window must return the thread created by the first
submit instead of inserting an identical duplicate.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread


async def _thread_count(async_db: AsyncSession, user_id: int, title: str) -> int:
    result = await async_db.execute(
        select(func.count())
        .select_from(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.title == title)
    )
    return int(result.scalar_one())


async def _owner_id(async_db: AsyncSession, thread_id: int) -> int:
    result = await async_db.execute(select(Thread.user_id).where(Thread.id == thread_id))
    return int(result.scalar_one())


