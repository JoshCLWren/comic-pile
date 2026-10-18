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


@pytest.mark.asyncio
async def test_repeat_create_returns_existing_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Two identical create submissions yield one thread with a shared id."""
    payload = {
        "title": "Double Click Victim",
        "format": "Comic",
        "issues_remaining": 3,
        "total_issues": 3,
    }

    first = await auth_client.post("/api/v1/threads/", json=payload)
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await auth_client.post("/api/v1/threads/", json=payload)
    assert second.status_code == 201
    second_id = second.json()["id"]

    assert second_id == first_id, "duplicate submit must merge into the first thread"

    owner_id = await _owner_id(async_db, first_id)
    assert await _thread_count(async_db, owner_id, payload["title"]) == 1


@pytest.mark.asyncio
async def test_distinct_creates_are_not_merged(auth_client: AsyncClient) -> None:
    """A differing fingerprint still creates a separate thread."""
    base = {"title": "Distinct Series", "format": "Comic", "issues_remaining": 2}

    first = await auth_client.post("/api/v1/threads/", json=base)
    assert first.status_code == 201

    second = await auth_client.post(
        "/api/v1/threads/", json={**base, "title": "Distinct Series Two"}
    )
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
