"""Option E frontier regressions with an isolated scalar-storage query fixture."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User
from app.services.read_frontier_service import derive_read_frontiers


@pytest_asyncio.fixture
async def frontier_db() -> AsyncIterator[AsyncSession]:
    """Exercise the real SELECT on minimal local tables, with no production access."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(text(
            "CREATE TABLE threads (id INTEGER PRIMARY KEY, user_id INTEGER, "
            "status TEXT, next_unread_issue_id INTEGER)"
        ))
        await connection.execute(text(
            "CREATE TABLE issues (id INTEGER PRIMARY KEY, thread_id INTEGER, "
            "position INTEGER, status TEXT)"
        ))
    async with AsyncSession(engine) as db:
        yield db
    await engine.dispose()


async def seed_thread(
    db: AsyncSession, thread_id: int, pointer: int | None, *,
    user_id: int = 1, status: str = "active",
) -> None:
    """Insert scalar test inputs without relying on cached Thread fields."""
    await db.execute(text(
        "INSERT INTO threads VALUES (:id, :user, :status, :pointer)"
    ), {"id": thread_id, "user": user_id, "status": status, "pointer": pointer})


async def seed_issue(
    db: AsyncSession, issue_id: int, thread_id: int, position: int, status: str = "unread",
) -> None:
    """Insert an issue at its curated position."""
    await db.execute(text(
        "INSERT INTO issues VALUES (:id, :thread, :position, :status)"
    ), {"id": issue_id, "thread": thread_id, "position": position, "status": status})


@pytest.mark.parametrize(
    ("parent", "stored", "first", "shell"),
    [(18849, 117307, 117363, 18876), (18991, 117665, 117661, 18989)],
)
async def test_consolidated_parents_and_empty_shells(
    frontier_db: AsyncSession, parent: int, stored: int, first: int, shell: int,
) -> None:
    """Known parent drift and cross-Thread shell pointers stay diagnostic only."""
    await seed_thread(frontier_db, parent, stored)
    await seed_thread(frontier_db, shell, first)
    await seed_issue(frontier_db, stored, parent, 8)
    await seed_issue(frontier_db, first, parent, 1)
    before = (await frontier_db.execute(text("SELECT * FROM threads ORDER BY id"))).all()
    result = await derive_read_frontiers(frontier_db, 1)
    assert result[parent].next_issue_id == first
    assert result[parent].pointer_mismatch
    assert result[parent].stored_pointer_in_thread is True
    assert result[shell].next_issue_id is None
    assert result[shell].issue_count == 0
    assert result[shell].pointer_mismatch
    assert result[shell].stored_pointer_in_thread is False
    assert (await frontier_db.execute(text("SELECT * FROM threads ORDER BY id"))).all() == before
    assert not frontier_db.dirty


async def test_positions_read_states_exclusions_and_deterministic_ties(
    frontier_db: AsyncSession,
) -> None:
    """Gaps and embedded annual placement, rather than ID order, define the frontier."""
    await seed_thread(frontier_db, 1, 10)
    await seed_issue(frontier_db, 10, 1, 1, "read")
    await seed_issue(frontier_db, 90, 1, 4)  # Embedded annual, before the regular issue.
    await seed_issue(frontier_db, 20, 1, 9)
    await seed_issue(frontier_db, 15, 1, 9)  # Stable-ID tie during a deferred reorder.
    await seed_issue(frontier_db, 11, 1, 2, "read")
    await seed_issue(frontier_db, 12, 1, 3, "archived")
    result = (await derive_read_frontiers(frontier_db, 1))[1]
    assert result.next_issue_id == 90
    assert result.issue_count == 6
    assert result.unread_count == 3
    result = (await derive_read_frontiers(frontier_db, 1, excluded_issue_ids={90, 999}))[1]
    assert result.next_issue_id == 15
    assert result.excluded_unread_count == 1
    result = (await derive_read_frontiers(frontier_db, 1, excluded_issue_ids={90, 15, 20}))[1]
    assert result.next_issue_id is None
    assert result.unread_count == result.excluded_unread_count == 3


async def test_reader_scope_inactive_threads_and_foreign_pointer(
    frontier_db: AsyncSession,
) -> None:
    """Foreign and inactive Threads never leak candidates or pointer membership."""
    await seed_thread(frontier_db, 1, 200)
    await seed_thread(frontier_db, 2, 200, user_id=2)
    await seed_thread(frontier_db, 3, 300, status="completed")
    await seed_issue(frontier_db, 100, 1, 1)
    await seed_issue(frontier_db, 200, 2, 1)
    await seed_issue(frontier_db, 300, 3, 1)
    result = await derive_read_frontiers(frontier_db, 1)
    assert list(result) == [1]
    assert result[1].next_issue_id == 100
    assert result[1].stored_pointer_in_thread is False
    assert await derive_read_frontiers(frontier_db, 999) == {}


async def test_empty_fully_read_null_and_missing_pointers(frontier_db: AsyncSession) -> None:
    """No cached pointer or counter fallback invents an unread issue."""
    await seed_thread(frontier_db, 1, None)
    await seed_thread(frontier_db, 2, 22)
    await seed_thread(frontier_db, 3, 999)
    await seed_issue(frontier_db, 22, 2, 1, "read")
    result = await derive_read_frontiers(frontier_db, 1)
    assert all(frontier.next_issue_id is None for frontier in result.values())
    assert result[1].stored_pointer_in_thread is None
    assert not result[1].pointer_mismatch
    assert result[2].stored_pointer_in_thread is True
    assert result[2].pointer_mismatch
    assert result[3].stored_pointer_in_thread is False


async def test_read_only_query_does_not_autoflush(frontier_db: AsyncSession) -> None:
    """Pending ORM data must not be flushed as a side effect of census reads."""
    pending = User(username="must-not-be-persisted", password_hash="test")
    frontier_db.add(pending)
    with patch.object(frontier_db, "flush", new_callable=AsyncMock) as flush:
        assert await derive_read_frontiers(frontier_db, 1) == {}
        flush.assert_not_awaited()
    assert pending in frontier_db.new
