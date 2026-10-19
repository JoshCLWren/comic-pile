"""Regression tests for #3449: consistent dense display positions.

Queue, Roll, thread detail, and restored sessions expose dense ordinals
independently of stored ordering keys. Mutation coverage also preserves the
current dense storage contract until sparse ordering lands.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.repositories import thread_repository
from app.schemas.thread import ThreadCreate, ThreadUpdate
from app.services import issue as issue_service
from app.services import thread_service
from comic_pile.queue import ADVISORY_LOCK_NAMESPACE


async def _active_positions(async_db: AsyncSession, user_id: int) -> list[int]:
    """Return the stored active-queue positions for one reader, lowest first."""
    result = await async_db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    return list(result.scalars().all())


async def _add_thread(
    async_db: AsyncSession,
    user: User,
    *,
    title: str,
    position: int,
    total_issues: int | None = None,
) -> Thread:
    """Insert one active thread at ``position`` and return it."""
    thread = Thread(
        title=title,
        format="comic",
        user_id=user.id,
        queue_position=position,
        status="active",
        issues_remaining=1 if total_issues is None else total_issues,
        total_issues=total_issues,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


def _assert_dense(positions: list[int]) -> None:
    """Assert ``positions`` is exactly ``1..N`` with no reusable gap."""
    assert positions == list(range(1, len(positions) + 1)), positions
    assert max(positions, default=0) <= len(positions)


@pytest.mark.asyncio
async def test_delete_thread_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Deleting a middle series closes the gap in the active queue."""
    await _add_thread(async_db, default_user, title="A", position=1)
    middle = await _add_thread(async_db, default_user, title="B", position=2)
    await _add_thread(async_db, default_user, title="C", position=3)
    await async_db.commit()

    await thread_service.delete_thread(async_db, default_user.id, middle.id)

    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_complete_thread_via_update_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Completing a counter-based series by editing issues closes the gap."""
    await _add_thread(async_db, default_user, title="A", position=1)
    middle = await _add_thread(async_db, default_user, title="B", position=2)
    await _add_thread(async_db, default_user, title="C", position=3)
    await async_db.commit()

    await thread_service.update_thread(
        async_db, default_user.id, middle.id, ThreadUpdate(issues_remaining=0)
    )

    await async_db.refresh(middle)
    assert middle.status == "completed"
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_complete_thread_via_mark_read_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Reading the last issue completes a series without leaving a queue gap."""
    await _add_thread(async_db, default_user, title="A", position=1)
    tracked = await _add_thread(
        async_db, default_user, title="B", position=2, total_issues=1
    )
    await _add_thread(async_db, default_user, title="C", position=3)

    last_issue = Issue(
        thread_id=tracked.id,
        issue_number="1",
        position=1,
        status="unread",
        read_at=None,
    )
    async_db.add(last_issue)
    await async_db.commit()

    await issue_service.mark_issue_read(async_db, last_issue.id, default_user.id)
    await async_db.commit()

    await async_db.refresh(tracked)
    assert tracked.status == "completed"
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_reactivate_thread_via_mark_unread_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Reactivating a completed series re-enters the dense active queue."""
    await _add_thread(async_db, default_user, title="A", position=1)
    await _add_thread(async_db, default_user, title="C", position=2)

    completed = Thread(
        title="B",
        format="comic",
        user_id=default_user.id,
        queue_position=0,
        status="completed",
        issues_remaining=0,
        total_issues=1,
        reading_progress="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(completed)
    await async_db.flush()

    read_issue = Issue(
        thread_id=completed.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(read_issue)
    await async_db.commit()

    await issue_service.mark_issue_unread(async_db, read_issue.id, default_user.id)
    await async_db.commit()

    await async_db.refresh(completed)
    assert completed.status == "active"
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_new_series_after_tail_completion_stays_within_the_queue(
    async_db: AsyncSession, default_user: User
) -> None:
    """A series created after the last one finishes still lands inside 1..N.

    Completing a series leaves the position it held on the finished shelf, so
    appending behind "the highest position this reader owns" pushed the new
    series past the end of the dense range and made Queue, the roll card, and
    the thread page display a position larger than the queue itself (#3449).
    """
    await _add_thread(async_db, default_user, title="A", position=1)
    await _add_thread(async_db, default_user, title="B", position=2)
    tail = await _add_thread(
        async_db, default_user, title="C", position=3, total_issues=1
    )
    tail_issue = Issue(
        thread_id=tail.id,
        issue_number="1",
        position=1,
        status="unread",
        read_at=None,
    )
    async_db.add(tail_issue)
    await async_db.commit()

    await issue_service.mark_issue_read(async_db, tail_issue.id, default_user.id)
    await async_db.commit()

    # The finished series keeps its old position; the queue is now 1..2.
    _assert_dense(await _active_positions(async_db, default_user.id))

    await thread_service.create_thread_with_retry(
        async_db,
        default_user.id,
        ThreadCreate(title="D", format="comic", issues_remaining=1),
    )
    await async_db.commit()

    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_max_queue_position_ignores_finished_and_excluded_series(
    async_db: AsyncSession, default_user: User
) -> None:
    """Queue appends read the active queue, not every row the reader owns."""
    await _add_thread(async_db, default_user, title="A", position=1)
    await _add_thread(async_db, default_user, title="B", position=2)
    tail = await _add_thread(async_db, default_user, title="C", position=3)
    await async_db.commit()

    assert await thread_repository.max_queue_position(async_db, default_user.id) == 3

    await thread_service.delete_thread(async_db, default_user.id, tail.id)

    assert await thread_repository.max_queue_position(async_db, default_user.id) == 2


@pytest.mark.asyncio
async def test_edit_finished_series_back_into_queue_assigns_a_position(
    async_db: AsyncSession, default_user: User
) -> None:
    """A legacy series edited back to "issues left" rejoins the active queue.

    The queue page lists every ``active`` row, so returning the series to the
    active queue without a queue position rendered it as "#0" and left it out of
    every roll pool, which selects on ``queue_position >= 1`` (#3449).
    """
    await _add_thread(async_db, default_user, title="A", position=1)
    await _add_thread(async_db, default_user, title="B", position=2)

    finished = Thread(
        title="C",
        format="comic",
        user_id=default_user.id,
        queue_position=0,
        status="completed",
        issues_remaining=0,
        total_issues=None,
        reading_progress="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(finished)
    await async_db.commit()

    await thread_service.update_thread(
        async_db, default_user.id, finished.id, ThreadUpdate(issues_remaining=4)
    )

    await async_db.refresh(finished)
    assert finished.status == "active"
    assert finished.queue_position >= 1
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_exclude_and_restore_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Removing a series from the queue and restoring it keeps 1..N dense."""
    first = await _add_thread(async_db, default_user, title="A", position=1)
    await _add_thread(async_db, default_user, title="B", position=2)
    await _add_thread(async_db, default_user, title="C", position=3)
    await async_db.commit()

    await thread_service.exclude_thread(async_db, default_user.id, first.id)
    _assert_dense(await _active_positions(async_db, default_user.id))

    await thread_service.restore_thread(async_db, default_user.id, first.id)
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_sparse_existing_positions_agree_across_api_surfaces(
    async_db: AsyncSession, default_user: User, auth_client: AsyncClient
) -> None:
    """Normal reads fix existing gaps without requiring a mutation or rewriting keys."""
    first = await _add_thread(async_db, default_user, title="A", position=4)
    last = await _add_thread(async_db, default_user, title="B", position=621)
    await async_db.commit()
    expected = {first.id: 1, last.id: 2}

    queue = await auth_client.get("/api/v1/threads/", params={"page_size": 1})
    assert queue.status_code == 200, queue.text
    page = queue.json()
    assert page["threads"][0]["queue_position"] == 1
    second_page = await auth_client.get(
        "/api/v1/threads/", params={"page_size": 1, "page_token": page["next_page_token"]}
    )
    assert second_page.status_code == 200, second_page.text
    assert second_page.json()["threads"][0]["queue_position"] == 2

    for thread_id, position in expected.items():
        detail = await auth_client.get(f"/api/v1/threads/{thread_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["queue_position"] == position

    roll = await auth_client.post("/api/v1/roll/")
    assert roll.status_code == 200, roll.text
    assert roll.json()["queue_position"] == expected[roll.json()["thread_id"]]
    restored = await auth_client.get("/api/v1/sessions/current/")
    assert restored.status_code == 200, restored.text
    active = restored.json()["active_thread"]
    assert active["queue_position"] == expected[active["id"]]
    assert await _active_positions(async_db, default_user.id) == [4, 621]


@pytest.mark.asyncio
async def test_dense_display_follows_blocked_last_order_and_is_reader_scoped(
    async_db: AsyncSession, default_user: User
) -> None:
    """Display order matches Queue grouping and never ranks another reader's rows."""
    from app.services.queue_display import display_positions
    from tests.conftest import get_or_create_user_async

    blocked = await _add_thread(async_db, default_user, title="Blocked", position=4)
    blocked.is_blocked = True
    available = await _add_thread(async_db, default_user, title="Available", position=621)
    other_user = await get_or_create_user_async(async_db, username="other_queue_owner")
    await _add_thread(async_db, other_user, title="Other reader", position=1)
    await async_db.flush()
    assert await display_positions(async_db, default_user.id) == {available.id: 1, blocked.id: 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("remove", ["delete", "complete"])
async def test_display_positions_agree_after_queue_removal(
    async_db: AsyncSession, default_user: User, auth_client: AsyncClient, remove: str
) -> None:
    """Completion and deletion update every surviving public ordinal."""
    first = await _add_thread(async_db, default_user, title="First", position=4)
    last = await _add_thread(async_db, default_user, title="Last", position=621)
    await async_db.commit()
    if remove == "delete":
        await thread_service.delete_thread(async_db, default_user.id, first.id)
    else:
        await thread_service.update_thread(
            async_db, default_user.id, first.id, ThreadUpdate(issues_remaining=0)
        )
    queue = await auth_client.get("/api/v1/threads/")
    assert queue.status_code == 200, queue.text
    assert [(row["id"], row["queue_position"]) for row in queue.json()["threads"]] == [
        (last.id, 1)
    ]
    detail = await auth_client.get(f"/api/v1/threads/{last.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["queue_position"] == 1
    roll = await auth_client.post("/api/v1/roll/")
    assert roll.status_code == 200, roll.text
    assert roll.json()["thread_id"] == last.id
    assert roll.json()["queue_position"] == 1


@pytest.mark.asyncio
async def test_renormalize_holds_the_shared_queue_lock(
    async_db: AsyncSession, default_user: User
) -> None:
    """Renumbering takes the same per-reader lock as a move or shuffle.

    Without it, a reorder that commits between the renumbering read and flush
    would be overwritten and silently undone (#3449 review finding).
    """
    await _add_thread(async_db, default_user, title="A", position=7)
    await _add_thread(async_db, default_user, title="B", position=621)
    await async_db.commit()

    await thread_repository.renormalize_queue_positions(async_db, default_user.id)

    held = await async_db.execute(
        text(
            "SELECT count(*) FROM pg_locks "
            "WHERE locktype = 'advisory' AND classid = :namespace "
            "AND objid = :user_id AND pid = pg_backend_pid() AND granted"
        ),
        {"namespace": ADVISORY_LOCK_NAMESPACE, "user_id": default_user.id},
    )
    assert held.scalar_one() == 1
    _assert_dense(await _active_positions(async_db, default_user.id))
