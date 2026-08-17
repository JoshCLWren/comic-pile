"""Unit tests for the shared bulk thread-issue-stat loaders.

These tests cover both migrated and unmigrated threads to satisfy the
issue #1257 acceptance contract: bulk loads must preserve the legacy
``issues_remaining`` fallback for unmigrated threads while computing true
unread counts for migrated threads in a constant number of queries.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.models.user import User
from app.services.thread_issue_stats import load_next_issue_numbers, load_unread_counts


async def _make_thread(
    async_db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    migrated: bool,
    stored_remaining: int,
) -> Thread:
    """Create a thread, optionally with 5 issues (2 unread) and next-issue wiring."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=stored_remaining,
        queue_position=queue_position,
        user_id=user_id,
        total_issues=5 if migrated else None,
        reading_progress="in_progress" if migrated else None,
    )
    async_db.add(thread)
    await async_db.flush()
    if migrated:
        first_issue = None
        for i in range(1, 6):
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(i),
                position=i,
                status="unread" if i <= 2 else "read",
            )
            async_db.add(issue)
            if first_issue is None:
                first_issue = issue
        await async_db.flush()
        assert first_issue is not None
        thread.next_unread_issue_id = first_issue.id
        await async_db.flush()
    return thread


@pytest.mark.asyncio
async def test_load_unread_counts_migrated(async_db: AsyncSession, default_user: User) -> None:
    """Migrated threads get a computed unread count, not the stored counter."""
    thread = await _make_thread(
        async_db,
        user_id=default_user.id,
        title="Migrated",
        queue_position=1,
        migrated=True,
        stored_remaining=99,
    )
    await async_db.commit()

    counts = await load_unread_counts([thread], async_db)
    assert counts == {thread.id: 2}


@pytest.mark.asyncio
async def test_load_unread_counts_unmigrated_omitted(
    async_db: AsyncSession, default_user: User
) -> None:
    """Unmigrated threads are omitted so callers keep the stored counter."""
    thread = await _make_thread(
        async_db,
        user_id=default_user.id,
        title="Legacy",
        queue_position=1,
        migrated=False,
        stored_remaining=42,
    )
    await async_db.commit()

    counts = await load_unread_counts([thread], async_db)
    assert counts == {}


@pytest.mark.asyncio
async def test_load_unread_counts_mixed(async_db: AsyncSession, default_user: User) -> None:
    """Mixed lists only count migrated threads in the grouped query."""
    migrated = await _make_thread(
        async_db,
        user_id=default_user.id,
        title="Migrated",
        queue_position=1,
        migrated=True,
        stored_remaining=99,
    )
    unmigrated = await _make_thread(
        async_db,
        user_id=default_user.id,
        title="Legacy",
        queue_position=2,
        migrated=False,
        stored_remaining=42,
    )
    await async_db.commit()

    counts = await load_unread_counts([migrated, unmigrated], async_db)
    assert counts == {migrated.id: 2}
    assert unmigrated.id not in counts


@pytest.mark.asyncio
async def test_load_unread_counts_empty_list(async_db: AsyncSession) -> None:
    """Empty input returns an empty map without touching the database."""
    assert await load_unread_counts([], async_db) == {}


@pytest.mark.asyncio
async def test_load_next_issue_numbers_migrated(
    async_db: AsyncSession, default_user: User
) -> None:
    """Migrated threads resolve their next-unread issue number."""
    thread = await _make_thread(
        async_db,
        user_id=default_user.id,
        title="Migrated",
        queue_position=1,
        migrated=True,
        stored_remaining=99,
    )
    await async_db.commit()

    numbers = await load_next_issue_numbers([thread], async_db)
    assert numbers == {thread.next_unread_issue_id: "1"}


@pytest.mark.asyncio
async def test_load_next_issue_numbers_unmigrated_empty(
    async_db: AsyncSession, default_user: User
) -> None:
    """Unmigrated threads have no next-unread issue to resolve."""
    thread = await _make_thread(
        async_db,
        user_id=default_user.id,
        title="Legacy",
        queue_position=1,
        migrated=False,
        stored_remaining=42,
    )
    await async_db.commit()

    assert await load_next_issue_numbers([thread], async_db) == {}


@pytest.mark.asyncio
async def test_load_next_issue_numbers_empty_list(async_db: AsyncSession) -> None:
    """Empty input returns an empty map without touching the database."""
    assert await load_next_issue_numbers([], async_db) == {}
