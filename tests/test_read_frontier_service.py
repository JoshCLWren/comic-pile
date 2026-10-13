"""Option E frontier regressions with an isolated scalar-storage query fixture."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import MetaData, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Issue, Thread, User
from app.services.read_frontier_service import derive_read_frontiers


@pytest_asyncio.fixture
async def frontier_db() -> AsyncIterator[AsyncSession]:
    """Exercise the real SELECT with copied model metadata and local storage only."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        copied = table.to_metadata(metadata)
        for constraint in copied.constraints:
            if isinstance(constraint, UniqueConstraint):
                # SQLite enforces uniqueness immediately, without PostgreSQL's
                # deferred-constraint syntax. Keep the same unique columns.
                constraint.deferrable = None
                constraint.initially = None
    async with engine.begin() as connection:
        for name in ("users", "threads", "issues"):
            await connection.run_sync(metadata.tables[name].create)
    async with AsyncSession(engine) as db:
        yield db
    await engine.dispose()


async def seed_thread(
    db: AsyncSession, thread_id: int, pointer: int | None, *,
    user_id: int = 1, status: str = "active",
) -> None:
    """Insert model-backed test inputs without relying on cached Thread fields."""
    db.add(Thread(
        id=thread_id, user_id=user_id, status=status, next_unread_issue_id=pointer,
        title=f"Thread {thread_id}", format="Comic", queue_position=thread_id,
    ))
    await db.flush()


async def seed_issue(
    db: AsyncSession, issue_id: int, thread_id: int, position: int, status: str = "unread",
) -> None:
    """Insert an issue at its curated position."""
    db.add(Issue(
        id=issue_id, thread_id=thread_id, issue_number=str(issue_id),
        position=position, status=status,
    ))
    await db.flush()


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


async def test_positions_read_states_and_exclusions(
    frontier_db: AsyncSession,
) -> None:
    """Gaps and embedded annual placement, rather than ID order, define the frontier."""
    await seed_thread(frontier_db, 1, 10)
    await seed_issue(frontier_db, 10, 1, 1, "read")
    await seed_issue(frontier_db, 90, 1, 4)  # Embedded annual, before the regular issue.
    await seed_issue(frontier_db, 20, 1, 9)
    await seed_issue(frontier_db, 15, 1, 7)
    await seed_issue(frontier_db, 11, 1, 2, "read")
    result = (await derive_read_frontiers(frontier_db, 1))[1]
    assert result.next_issue_id == 90
    assert result.issue_count == 5
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


@pytest.mark.parametrize("status", ["unread", "unexpected"])
async def test_only_read_state_completes_an_issue(
    frontier_db: AsyncSession, status: str,
) -> None:
    """Future or corrupt states cannot silently hide an issue from the frontier."""
    await seed_thread(frontier_db, 1, None)
    await seed_issue(frontier_db, 10, 1, 1, status)
    await seed_issue(frontier_db, 20, 1, 2, "read")
    frontier = (await derive_read_frontiers(frontier_db, 1))[1]
    assert frontier.next_issue_id == 10
    assert frontier.unread_count == 1


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
    assert await derive_read_frontiers(frontier_db, 1) == {}
    # Autoflush uses the sync session. With a real users table, an accidental
    # flush would assign an ID and remove this User from the pending set.
    assert pending.id is None
    assert pending in frontier_db.new
    connection = await frontier_db.connection()
    assert (await connection.execute(text("SELECT count(*) FROM users"))).scalar_one() == 0
