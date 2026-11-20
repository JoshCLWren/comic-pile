"""Regression tests for #3449: consistent dense display positions.

Queue, Roll, thread detail, and restored sessions expose dense ordinals
independently of stored ordering keys. Mutation coverage also preserves the
current dense storage contract until sparse ordering lands.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Thread, User
from app.repositories import thread_repository
from app.schemas.thread import ThreadUpdate
from app.services import thread_service
from comic_pile.queue import ADVISORY_LOCK_NAMESPACE, acquire_queue_lock


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


@contextmanager
def _captured_statements(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Record every SQL statement executed while the context is active."""
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(str(statement))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


def _first_statement_index(statements: list[str], needle: str) -> int:
    """Return the index of the first statement containing ``needle``, or -1."""
    normalized_needle = needle.upper()
    for index, statement in enumerate(statements):
        if normalized_needle in " ".join(statement.upper().split()):
            return index
    return -1


def _assert_queue_lock_precedes_thread_writes(statements: list[str]) -> None:
    """The advisory queue lock must be acquired before any thread row write.

    Taking a thread row lock first inverts the global order used by
    move/shuffle and lets PostgreSQL abort one of two concurrent requests.
    """
    lock_index = _first_statement_index(statements, "pg_advisory_xact_lock")
    write_index = _first_statement_index(statements, "UPDATE threads")
    assert lock_index != -1, statements
    assert write_index != -1, statements
    assert lock_index < write_index, statements


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


@pytest.mark.asyncio
async def test_acquiring_queue_lock_does_not_flush_pending_rows_first(
    async_db: AsyncSession, default_user: User, db_engine: AsyncEngine
) -> None:
    """The queue lock is acquired before pending thread rows are flushed.

    A caller may reach the lock with dirty rows already pending. Flushing them
    first takes row locks before the advisory lock and inverts the ordering
    that a concurrent shuffle relies on.
    """
    thread = await _add_thread(async_db, default_user, title="A", position=1)
    await async_db.commit()
    thread.title = "pending title"

    with _captured_statements(db_engine) as statements:
        await acquire_queue_lock(default_user.id, async_db)
        await async_db.flush()

    _assert_queue_lock_precedes_thread_writes(statements)


@pytest.mark.asyncio
async def test_update_thread_takes_queue_lock_before_row_writes(
    async_db: AsyncSession, default_user: User, db_engine: AsyncEngine
) -> None:
    """Returning a finished legacy series to the queue locks before writing.

    Computing the append position issues a query, which used to autoflush the
    dirty thread row first and take the row lock before the queue lock.
    """
    await _add_thread(async_db, default_user, title="A", position=1)
    finished = Thread(
        title="B",
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

    with _captured_statements(db_engine) as statements:
        await thread_service.update_thread(
            async_db, default_user.id, finished.id, ThreadUpdate(issues_remaining=2)
        )

    _assert_queue_lock_precedes_thread_writes(statements)


