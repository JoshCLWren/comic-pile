"""Server-side pages for the bounded blocked and inactive Roll sections (#3330).

The Roll bootstrap previews a bounded slice of each category while reporting the
true total. These tests drive the real endpoints against the async PostgreSQL
fixture to prove the page totals equal the bootstrap counts and that every
counted record is reachable by paging.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadingSession, Thread
from app.schemas import (
    RollBlockedThreadsPage,
    RollBootstrapResponse,
    RollInactiveThreadsPage,
)
from tests.conftest import get_or_create_user_async


async def _thread(
    db: AsyncSession,
    user_id: int,
    *,
    title: str,
    position: int,
    status: str = "active",
    is_blocked: bool = False,
) -> Thread:
    """Persist one owned series and return it."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=position,
        status=status,
        is_blocked=is_blocked,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _bootstrap(client: AsyncClient) -> RollBootstrapResponse:
    """Fetch the Roll bootstrap payload for the authenticated user."""
    response = await client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    return RollBootstrapResponse.model_validate(response.json())


async def _blocked_page(
    client: AsyncClient,
    *,
    offset: int = 0,
    limit: int = 20,
) -> RollBlockedThreadsPage:
    response = await client.get(
        "/api/v1/roll/blocked-threads",
        params={"offset": offset, "limit": limit},
    )
    assert response.status_code == 200
    return RollBlockedThreadsPage.model_validate(response.json())


async def _inactive_page(
    client: AsyncClient,
    *,
    offset: int = 0,
    limit: int = 20,
) -> RollInactiveThreadsPage:
    response = await client.get(
        "/api/v1/roll/inactive-threads",
        params={"offset": offset, "limit": limit},
    )
    assert response.status_code == 200
    return RollInactiveThreadsPage.model_validate(response.json())


@pytest.mark.asyncio
async def test_blocked_page_total_matches_bootstrap_and_pages_every_record(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A reader with 25 blocked series can reach all 25 across two pages."""
    user = await get_or_create_user_async(async_db)
    blocked_ids = set()
    for position in range(1, 26):
        thread = await _thread(
            async_db,
            user.id,
            title=f"Blocked {position}",
            position=position,
            is_blocked=True,
        )
        blocked_ids.add(thread.id)
    await async_db.commit()

    bootstrap = await _bootstrap(auth_client)
    assert bootstrap.blocked_count == 25
    assert len(bootstrap.blocked_threads) == 20

    first = await _blocked_page(auth_client, offset=0, limit=20)
    assert first.total == bootstrap.blocked_count
    assert first.offset == 0
    assert first.limit == 20
    assert len(first.items) == 20
    assert first.next_offset == 20

    second = await _blocked_page(auth_client, offset=first.next_offset or 0, limit=20)
    assert second.total == bootstrap.blocked_count
    assert len(second.items) == 5
    assert second.next_offset is None

    paged_ids = {item.id for item in first.items} | {item.id for item in second.items}
    assert paged_ids == blocked_ids


@pytest.mark.asyncio
async def test_blocked_page_offset_past_end_keeps_the_accurate_total(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An out-of-range offset returns no rows without lying about the total."""
    user = await get_or_create_user_async(async_db)
    for position in range(1, 4):
        await _thread(
            async_db,
            user.id,
            title=f"Blocked {position}",
            position=position,
            is_blocked=True,
        )
    await async_db.commit()

    page = await _blocked_page(auth_client, offset=50, limit=20)

    assert page.total == 3
    assert page.items == []
    assert page.next_offset is None


@pytest.mark.asyncio
async def test_blocked_page_excludes_other_users_and_unblocked_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The page stays owner-scoped and keeps the blocked predicate."""
    owner = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="foreign_blocked_owner")
    mine = await _thread(
        async_db, owner.id, title="Mine blocked", position=1, is_blocked=True
    )
    await _thread(
        async_db, owner.id, title="Mine rollable", position=2, is_blocked=False
    )
    await _thread(
        async_db, other.id, title="Theirs blocked", position=1, is_blocked=True
    )
    await async_db.commit()

    page = await _blocked_page(auth_client)

    assert page.total == 1
    assert [item.id for item in page.items] == [mine.id]


@pytest.mark.asyncio
async def test_inactive_page_total_matches_bootstrap_and_pages_every_record(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Completed plus vanished-from-queue series are all reachable by paging."""
    user = await get_or_create_user_async(async_db)
    inactive_ids: set[int] = set()
    for index in range(22):
        thread = await _thread(
            async_db,
            user.id,
            title=f"Completed {index}",
            position=50 + index,
            status="completed",
        )
        inactive_ids.add(thread.id)
    for index in range(3):
        thread = await _thread(
            async_db,
            user.id,
            title=f"Out of queue {index}",
            position=0,
        )
        inactive_ids.add(thread.id)
    # Neither of these belongs in the inactive category.
    await _thread(async_db, user.id, title="Rollable", position=1)
    await _thread(async_db, user.id, title="Blocked", position=2, is_blocked=True)
    await async_db.commit()

    bootstrap = await _bootstrap(auth_client)
    assert bootstrap.inactive_count == 25
    assert len(bootstrap.inactive_threads) == 20

    first = await _inactive_page(auth_client, offset=0, limit=20)
    assert first.total == bootstrap.inactive_count
    assert len(first.items) == 20
    assert first.next_offset == 20

    second = await _inactive_page(auth_client, offset=first.next_offset or 0, limit=20)
    assert second.total == bootstrap.inactive_count
    assert len(second.items) == 5
    assert second.next_offset is None

    paged_ids = {item.thread_id for item in first.items} | {
        item.thread_id for item in second.items
    }
    assert paged_ids == inactive_ids
    for item in [*first.items, *second.items]:
        if item.title.startswith("Completed"):
            assert item.reason == "completed"
            assert item.detail == "Read the full series"
        else:
            assert item.reason == "not_in_queue"
            assert item.detail == "Not in the active queue"


@pytest.mark.asyncio
async def test_inactive_page_respects_snooze_and_skip_scope(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozed and skipped series keep their own sections, not the inactive one."""
    user = await get_or_create_user_async(async_db)
    out_of_queue = await _thread(
        async_db, user.id, title="Out of queue", position=0
    )
    snoozed = await _thread(async_db, user.id, title="Snoozed", position=0)
    skipped = await _thread(async_db, user.id, title="Skipped", position=0)
    await async_db.commit()

    session = ReadingSession(
        start_die=6,
        user_id=user.id,
        snoozed_thread_ids=[snoozed.id],
        skipped_thread_ids=[skipped.id],
    )
    async_db.add(session)
    await async_db.commit()

    bootstrap = await _bootstrap(auth_client)
    page = await _inactive_page(auth_client)

    assert bootstrap.inactive_count == 1
    assert page.total == 1
    assert [item.thread_id for item in page.items] == [out_of_queue.id]
