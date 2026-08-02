"""Regression tests for the set-based queue repositioning rewrite (#699).

Covers deterministic normalization, concurrency, bounded database work,
logging guards, cross-user isolation, safe-position behavior, and front/back
movement with gaps, duplicates, and completed targets.
"""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Thread, User
from comic_pile.queue import (
    move_to_back,
    move_to_front,
    move_to_position,
    move_to_safe_position,
    shuffle_queue,
)
from tests.conftest import get_or_create_user_async, get_test_database_url


@pytest.mark.asyncio
async def test_duplicate_starting_positions_deterministic(
    async_db: AsyncSession, default_user: User
) -> None:
    """Duplicate queue positions normalize deterministically using the ID tie-break."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Dup A",
            format="Comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Dup B",
            format="Comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Dup C",
            format="Comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    ids = [thread.id for thread in threads]
    assert ids == sorted(ids), f"Test assumes ascending IDs for the tie-break: {ids}"

    # Move Dup A from sequential position 1 to position 3.
    await move_to_position(threads[0].id, default_user.id, 3, async_db)

    for thread in threads:
        await async_db.refresh(thread)

    positions = {thread.id: thread.queue_position for thread in threads}
    assert sorted(positions.values()) == [1, 2, 3], f"Positions not sequential: {positions}"
    assert positions[threads[0].id] == 3
    assert positions[threads[1].id] == 1
    assert positions[threads[2].id] == 2


@pytest.mark.asyncio
async def test_gapped_positions_preserve_order_after_move(
    async_db: AsyncSession, default_user: User
) -> None:
    """Moving through a gap preserves the active queue's relative order."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title="A",
            format="Comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="B",
            format="Comic",
            issues_remaining=1,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Complete",
            format="Comic",
            issues_remaining=1,
            queue_position=3,
            status="completed",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="C",
            format="Comic",
            issues_remaining=1,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="D",
            format="Comic",
            issues_remaining=1,
            queue_position=5,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    thread_c = threads[3]
    await move_to_position(thread_c.id, default_user.id, 1, async_db)

    for thread in threads:
        await async_db.refresh(thread)

    assert thread_c.queue_position == 1
    assert threads[2].queue_position == 3

    result = await async_db.execute(
        select(Thread)
        .where(Thread.user_id == default_user.id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position, Thread.id)
    )
    active = result.scalars().all()
    assert [thread.title for thread in active] == ["C", "A", "B", "D"]
    assert [thread.queue_position for thread in active] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_move_to_position_noop_keeps_clean_queue_unchanged(
    async_db: AsyncSession, default_user: User
) -> None:
    """A no-op move leaves an already normalized queue untouched."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"T{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    original_positions = {thread.id: thread.queue_position for thread in threads}
    await move_to_position(threads[2].id, default_user.id, 3, async_db)

    for thread in threads:
        await async_db.refresh(thread)

    current_positions = {thread.id: thread.queue_position for thread in threads}
    assert current_positions == original_positions


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_position", [0, -1, 11])
async def test_move_to_position_rejects_out_of_range(
    async_db: AsyncSession,
    default_user: User,
    bad_position: int,
) -> None:
    """Positions outside the active 1..N range raise ValueError."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"V-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 11)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    with pytest.raises(ValueError):
        await move_to_position(
            threads[0].id,
            default_user.id,
            bad_position,
            async_db,
        )

    # The helper acquired a transaction-scoped advisory lock before validating.
    await async_db.rollback()


@pytest.mark.asyncio
async def test_concurrent_repositioning_no_duplicate_positions(
    async_db_committed: AsyncSession,
) -> None:
    """Concurrent moves serialize without producing duplicate active positions."""
    user = await get_or_create_user_async(async_db_committed)

    now = datetime.now(UTC)
    for i in range(1, 21):
        async_db_committed.add(
            Thread(
                title=f"Conc {i}",
                format="Comic",
                issues_remaining=1,
                queue_position=i,
                status="active",
                user_id=user.id,
                created_at=now,
            )
        )
    await async_db_committed.commit()

    result = await async_db_committed.execute(
        select(Thread.id)
        .where(Thread.user_id == user.id, Thread.status == "active")
        .order_by(Thread.queue_position, Thread.id)
    )
    thread_ids = [row[0] for row in result.fetchall()]

    database_url = get_test_database_url()
    engine = create_async_engine(database_url, echo=False, pool_size=20, max_overflow=0)
    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def move_in_new_session(thread_id: int, target_position: int) -> None:
        async with session_maker() as session:
            await move_to_position(
                thread_id,
                user.id,
                target_position,
                session,
                do_commit=True,
            )

    moves = [
        (thread_ids[0], 10),
        (thread_ids[1], 1),
        (thread_ids[2], 20),
        (thread_ids[3], 5),
        (thread_ids[4], 15),
        (thread_ids[5], 3),
        (thread_ids[6], 18),
        (thread_ids[7], 7),
        (thread_ids[8], 12),
        (thread_ids[9], 2),
    ]

    try:
        tasks = [move_in_new_session(thread_id, position) for thread_id, position in moves]
        await asyncio.gather(*tasks)
    finally:
        await engine.dispose()

    result = await async_db_committed.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user.id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    positions = [row[0] for row in result.fetchall()]
    assert len(positions) == len(set(positions)), f"Duplicate positions found: {positions}"
    assert positions == list(range(1, 21)), f"Positions not sequential: {positions}"


@pytest.mark.asyncio
async def test_cross_user_isolation(
    async_db: AsyncSession, default_user: User
) -> None:
    """Queue operations for one user do not affect another user's positions."""
    user2 = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(user2)
    await async_db.commit()
    await async_db.refresh(user2)

    now = datetime.now(UTC)
    user1_threads = [
        Thread(
            title=f"U1-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 4)
    ]
    user2_threads = [
        Thread(
            title=f"U2-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=user2.id,
            created_at=now,
        )
        for i in range(1, 4)
    ]
    async_db.add_all(user1_threads + user2_threads)
    await async_db.commit()
    for thread in user1_threads + user2_threads:
        await async_db.refresh(thread)

    original_u2_positions = {thread.id: thread.queue_position for thread in user2_threads}
    await move_to_position(user1_threads[0].id, default_user.id, 3, async_db)

    for thread in user2_threads:
        await async_db.refresh(thread)
    current_u2_positions = {thread.id: thread.queue_position for thread in user2_threads}
    assert current_u2_positions == original_u2_positions

    for thread in user1_threads:
        await async_db.refresh(thread)
    u1_positions = sorted(thread.queue_position for thread in user1_threads)
    assert u1_positions == [1, 2, 3]
    assert user1_threads[0].queue_position == 3


@pytest.mark.asyncio
async def test_shuffle_isolates_per_user(
    async_db: AsyncSession, default_user: User
) -> None:
    """Shuffle updates the target user's full permutation and no other user."""
    user2 = User(username="other_shuffle", created_at=datetime.now(UTC))
    async_db.add(user2)
    await async_db.commit()
    await async_db.refresh(user2)

    now = datetime.now(UTC)
    u1 = [
        Thread(
            title=f"SU1-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 6)
    ]
    u2 = [
        Thread(
            title=f"SU2-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=user2.id,
            created_at=now,
        )
        for i in range(1, 4)
    ]
    async_db.add_all(u1 + u2)
    await async_db.commit()
    for thread in u1 + u2:
        await async_db.refresh(thread)

    original_u2_positions = {thread.id: thread.queue_position for thread in u2}
    shuffled_count = await shuffle_queue(default_user.id, async_db)
    assert shuffled_count == 5

    for thread in u1 + u2:
        await async_db.refresh(thread)

    current_u2_positions = {thread.id: thread.queue_position for thread in u2}
    assert current_u2_positions == original_u2_positions
    assert sorted(thread.queue_position for thread in u1) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_move_to_position_debug_reload_is_level_guarded(
    async_db: AsyncSession,
    default_user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The final queue reload is absent at INFO and present at DEBUG."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"DL-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="comic_pile.queue"):
        await move_to_position(threads[0].id, default_user.id, 3, async_db)

    assert not [
        record for record in caplog.records if "Final queue state" in record.getMessage()
    ], "Final queue state was reloaded even though DEBUG is disabled"

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="comic_pile.queue"):
        await move_to_position(threads[0].id, default_user.id, 1, async_db)

    assert [
        record for record in caplog.records if "Final queue state" in record.getMessage()
    ], "Final queue state was not reloaded even though DEBUG is enabled"


@pytest.mark.asyncio
async def test_safe_position_has_bounded_database_round_trips(
    async_db: AsyncSession, default_user: User
) -> None:
    """Safe-position movement does not refresh every cached thread individually."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"Safe-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 51)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    sync_connection = async_db.sync_session.connection()
    event.listen(sync_connection, "before_cursor_execute", record_statement)
    try:
        await move_to_safe_position(
            threads[0].id,
            default_user.id,
            6,
            async_db,
        )
    finally:
        event.remove(sync_connection, "before_cursor_execute", record_statement)

    assert threads[0].queue_position == 7
    assert len(statements) <= 7, f"Expected bounded SQL work, got {len(statements)} statements"


@pytest.mark.asyncio
async def test_move_to_front_preserves_relative_order(
    async_db: AsyncSession, default_user: User
) -> None:
    """Move-to-front preserves the relative order of all other active threads."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"F-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    await move_to_front(threads[3].id, default_user.id, async_db)

    result = await async_db.execute(
        select(Thread.title, Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position, Thread.id)
    )
    rows = result.all()
    assert [row.title for row in rows] == ["F-4", "F-1", "F-2", "F-3", "F-5"]
    assert [row.queue_position for row in rows] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_move_to_front_normalizes_duplicate_positions(
    async_db: AsyncSession, default_user: User
) -> None:
    """Move-to-front uses deterministic ordering when starting positions duplicate."""
    now = datetime.now(UTC)
    positions = [1, 1, 3, 4]
    threads = [
        Thread(
            title=f"FD-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=position,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i, position in enumerate(positions, start=1)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    await move_to_front(threads[3].id, default_user.id, async_db)

    result = await async_db.execute(
        select(Thread.title, Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position, Thread.id)
    )
    rows = result.all()
    assert [row.title for row in rows] == ["FD-4", "FD-1", "FD-2", "FD-3"]
    assert [row.queue_position for row in rows] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_move_to_back_preserves_relative_order(
    async_db: AsyncSession, default_user: User
) -> None:
    """Move-to-back preserves the relative order of all other active threads."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"B-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    await move_to_back(threads[1].id, default_user.id, async_db)

    result = await async_db.execute(
        select(Thread.title, Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position, Thread.id)
    )
    rows = result.all()
    assert [row.title for row in rows] == ["B-1", "B-3", "B-4", "B-5", "B-2"]
    assert [row.queue_position for row in rows] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_move_to_back_normalizes_gapped_positions(
    async_db: AsyncSession, default_user: User
) -> None:
    """Move-to-back compacts gaps created by non-active queue rows."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title="BG-1",
            format="Comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="BG-2",
            format="Comic",
            issues_remaining=1,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="BG-complete",
            format="Comic",
            issues_remaining=0,
            queue_position=3,
            status="completed",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="BG-4",
            format="Comic",
            issues_remaining=1,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="BG-5",
            format="Comic",
            issues_remaining=1,
            queue_position=5,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    await move_to_back(threads[1].id, default_user.id, async_db)

    result = await async_db.execute(
        select(Thread.title, Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position, Thread.id)
    )
    rows = result.all()
    assert [row.title for row in rows] == ["BG-1", "BG-4", "BG-5", "BG-2"]
    assert [row.queue_position for row in rows] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_move_to_back_compacts_queue_for_completed_target(
    async_db: AsyncSession, default_user: User
) -> None:
    """A newly completed target moves behind a compact active queue."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"BC-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    completed = threads[1]
    completed.status = "completed"
    completed.issues_remaining = 0
    await async_db.flush()

    await move_to_back(completed.id, default_user.id, async_db, commit=False)

    result = await async_db.execute(
        select(Thread.title, Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position, Thread.id)
    )
    rows = result.all()
    assert [row.title for row in rows] == ["BC-1", "BC-3", "BC-4", "BC-5"]
    assert [row.queue_position for row in rows] == [1, 2, 3, 4]
    assert completed.queue_position == 5


@pytest.mark.asyncio
async def test_positions_remain_sequential_after_multiple_moves(
    async_db: AsyncSession, default_user: User
) -> None:
    """Multiple moves keep active positions sequential and unique."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"M-{i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(1, 11)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for thread in threads:
        await async_db.refresh(thread)

    moves = [
        (threads[0].id, 10),
        (threads[9].id, 1),
        (threads[4].id, 3),
        (threads[2].id, 8),
        (threads[7].id, 5),
    ]
    for thread_id, position in moves:
        await move_to_position(thread_id, default_user.id, position, async_db)

    result = await async_db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    positions = [row[0] for row in result.fetchall()]
    assert positions == list(range(1, 11)), f"Not sequential after multiple moves: {positions}"
    assert len(positions) == len(set(positions)), f"Duplicates after multiple moves: {positions}"
