"""Regression tests for the set-based queue repositioning rewrite (#699).

Covers: duplicate-position determinism, concurrent-move integrity,
debug-log no-reload, cross-user isolation, gapped-position order
preservation, and no-op moves.
"""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Thread, User
from comic_pile.queue import move_to_position, move_to_front, move_to_back, shuffle_queue
from tests.conftest import get_or_create_user_async, get_test_database_url


# ── duplicate starting positions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_starting_positions_deterministic(
    async_db: AsyncSession, default_user: User
) -> None:
    """Duplicate queue_position values normalise deterministically (id tie-break)."""
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
    for t in threads:
        await async_db.refresh(t)

    # Move Dup A (seq=1 due to id tie-break) to position 3 (backward).
    # The combined normalisation + shift must produce sequential 1,2,3.
    await move_to_position(threads[0].id, default_user.id, 3, async_db)

    for t in threads:
        await async_db.refresh(t)

    positions = {t.id: t.queue_position for t in threads}
    assert sorted(positions.values()) == [1, 2, 3], f"Positions not sequential: {positions}"

    # Dup A moved to position 3; Dup B should be at 1 (shifted up), Dup C at 2
    assert positions[threads[0].id] == 3
    assert positions[threads[1].id] == 1
    assert positions[threads[2].id] == 2


# ── gapped starting positions (sample_data-like) ────────────────────────────────


@pytest.mark.asyncio
async def test_gapped_positions_preserve_order_after_move(
    async_db: AsyncSession, default_user: User
) -> None:
    """Moving through a gap preserves correct sequential order."""
    now = datetime.now(UTC)
    threads = [
        Thread(title="A", format="Comic", issues_remaining=1, queue_position=1,
               status="active", user_id=default_user.id, created_at=now),
        Thread(title="B", format="Comic", issues_remaining=1, queue_position=2,
               status="active", user_id=default_user.id, created_at=now),
        Thread(title="Complete", format="Comic", issues_remaining=1, queue_position=3,
               status="completed", user_id=default_user.id, created_at=now),
        Thread(title="C", format="Comic", issues_remaining=1, queue_position=4,
               status="active", user_id=default_user.id, created_at=now),
        Thread(title="D", format="Comic", issues_remaining=1, queue_position=5,
               status="active", user_id=default_user.id, created_at=now),
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    # Move C (at sequential pos 3 among actives: A=1, B=2, C=3, D=4) to position 1
    thread_c = threads[3]  # "C", queue_position=4
    await move_to_position(thread_c.id, default_user.id, 1, async_db)

    for t in threads:
        await async_db.refresh(t)

    # After move: C=1, A=2, B=3, D=4
    assert thread_c.queue_position == 1
    # Verify non-completed stays untouched
    assert threads[2].queue_position == 3  # completed, unchanged

    # Check active threads are in correct order
    result = await async_db.execute(
        select(Thread)
        .where(Thread.user_id == default_user.id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position)
    )
    active = result.scalars().all()
    active_titles = [t.title for t in active]
    assert active_titles == ["C", "A", "B", "D"]


# ── no-op moves ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_to_position_noop_does_nothing(
    async_db: AsyncSession, default_user: User
) -> None:
    """A no-op move leaves the queue untouched."""
    now = datetime.now(UTC)
    threads = [
        Thread(title=f"T{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    original_positions = {t.id: t.queue_position for t in threads}

    # Move thread at position 3 to position 3 (no-op)
    await move_to_position(threads[2].id, default_user.id, 3, async_db)

    for t in threads:
        await async_db.refresh(t)

    current_positions = {t.id: t.queue_position for t in threads}
    assert current_positions == original_positions


# ── concurrent-move integrity ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_repositioning_no_duplicate_positions(
    async_db_committed: AsyncSession,
) -> None:
    """Concurrent move_to_position calls must not produce duplicate active positions.

    This uses real commits across independent sessions, mirroring the pattern
    from test_concurrent_issue_creation.py.
    """
    user = await get_or_create_user_async(async_db_committed)

    now = datetime.now(UTC)
    for i in range(1, 21):
        t = Thread(
            title=f"Conc {i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i,
            status="active",
            user_id=user.id,
            created_at=now,
        )
        async_db_committed.add(t)
    await async_db_committed.commit()

    result = await async_db_committed.execute(
        select(Thread.id).where(Thread.user_id == user.id, Thread.status == "active")
    )
    thread_ids = [row[0] for row in result.fetchall()]

    database_url = get_test_database_url()
    engine = create_async_engine(database_url, echo=False, pool_size=20, max_overflow=0)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def move_in_new_session(tid: int, target_pos: int) -> None:
        async with session_maker() as s:
            await move_to_position(tid, user.id, target_pos, s, do_commit=True)

    # Launch 10 concurrent moves — different threads to different positions.
    # Each move acquires the advisory lock, so serialisation is guaranteed.
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
    tasks = [move_in_new_session(tid, pos) for tid, pos in moves]
    await asyncio.gather(*tasks)

    await engine.dispose()

    # Verify positions are sequential 1..20 with no duplicates
    result = await async_db_committed.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user.id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    positions = [row[0] for row in result.fetchall()]
    assert len(positions) == len(set(positions)), f"Duplicate positions found: {positions}"
    assert positions == list(range(1, 21)), f"Positions not sequential: {positions}"


# ── cross-user isolation ─────────────────────────────────────────────────────────


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
        Thread(title=f"U1-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 4)
    ]
    user2_threads = [
        Thread(title=f"U2-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=user2.id, created_at=now)
        for i in range(1, 4)
    ]
    async_db.add_all(user1_threads + user2_threads)
    await async_db.commit()
    for t in user1_threads + user2_threads:
        await async_db.refresh(t)

    original_u2_positions = {t.id: t.queue_position for t in user2_threads}

    # Move a thread for user 1 only
    await move_to_position(user1_threads[0].id, default_user.id, 3, async_db)

    # User 2 positions must be unchanged
    for t in user2_threads:
        await async_db.refresh(t)

    current_u2_positions = {t.id: t.queue_position for t in user2_threads}
    assert current_u2_positions == original_u2_positions, (
        f"User 2 positions changed: {original_u2_positions} → {current_u2_positions}"
    )

    # User 1's positions should be changed (our target moved)
    for t in user1_threads:
        await async_db.refresh(t)
    u1_ids = {t.id for t in user1_threads}
    result = await async_db.execute(
        select(Thread.queue_position)
        .where(Thread.id.in_(u1_ids))
        .order_by(Thread.queue_position)
    )
    u1_positions = [row[0] for row in result.fetchall()]
    assert u1_positions == [1, 2, 3], f"User 1 positions not sequential: {u1_positions}"


# ── shuffle isolation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shuffle_isolates_per_user(
    async_db: AsyncSession, default_user: User
) -> None:
    """shuffle_queue only affects the target user."""
    user2 = User(username="other_shuffle", created_at=datetime.now(UTC))
    async_db.add(user2)
    await async_db.commit()
    await async_db.refresh(user2)

    now = datetime.now(UTC)
    u1 = [
        Thread(title=f"SU1-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 6)
    ]
    u2 = [
        Thread(title=f"SU2-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=user2.id, created_at=now)
        for i in range(1, 4)
    ]
    async_db.add_all(u1 + u2)
    await async_db.commit()

    original_u2_positions = {t.id: t.queue_position for t in u2}

    await shuffle_queue(default_user.id, async_db)

    for t in u2:
        await async_db.refresh(t)

    current_u2_positions = {t.id: t.queue_position for t in u2}
    assert current_u2_positions == original_u2_positions


# ── debug-log no-reload ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_to_position_no_full_reload_when_debug_disabled(
    async_db: AsyncSession, default_user: User, caplog: pytest.LogCaptureFixture
) -> None:
    """When DEBUG logging is off, the final queue-state reload is NOT executed."""
    now = datetime.now(UTC)
    threads = [
        Thread(title=f"DL-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    queue_logger = logging.getLogger("comic_pile.queue")
    old_level = queue_logger.level
    queue_logger.setLevel(logging.INFO)

    try:
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="comic_pile.queue"):
            await move_to_position(threads[0].id, default_user.id, 3, async_db)
    finally:
        queue_logger.setLevel(old_level)

    final_state_records = [
        r for r in caplog.records
        if "Final queue state" in r.message
    ]
    assert len(final_state_records) == 0, (
        f"Final queue state was reloaded even though DEBUG is disabled: {final_state_records}"
    )


# ── move_to_front/back order preservation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_to_front_preserves_relative_order(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_front shifts all preceding threads back by 1, preserving their relative order."""
    now = datetime.now(UTC)
    threads = [
        Thread(title=f"F-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    # Move thread at position 4 to front
    await move_to_front(threads[3].id, default_user.id, async_db)

    for t in threads:
        await async_db.refresh(t)

    # Expected order: D(4→1), A(1→2), B(2→3), C(3→4), E(5→5)
    result = await async_db.execute(
        select(Thread.title)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    titles = [row[0] for row in result.fetchall()]
    assert titles == ["F-4", "F-1", "F-2", "F-3", "F-5"]


@pytest.mark.asyncio
async def test_move_to_back_preserves_relative_order(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_back shifts all following threads forward by 1, preserving their relative order."""
    now = datetime.now(UTC)
    threads = [
        Thread(title=f"B-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 6)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    # Move thread at position 2 to back
    await move_to_back(threads[1].id, default_user.id, async_db)

    for t in threads:
        await async_db.refresh(t)

    # Expected: A(1→1), C(3→2), D(4→3), E(5→4), B(2→5)
    result = await async_db.execute(
        select(Thread.title)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    titles = [row[0] for row in result.fetchall()]
    assert titles == ["B-1", "B-3", "B-4", "B-5", "B-2"]


# ── sequential positions after full cycle ───────────────────────────────────────


@pytest.mark.asyncio
async def test_positions_remain_sequential_after_multiple_moves(
    async_db: AsyncSession, default_user: User
) -> None:
    """After multiple move_to_position calls, active positions are sequential 1..N."""
    now = datetime.now(UTC)
    threads = [
        Thread(title=f"M-{i}", format="Comic", issues_remaining=1,
               queue_position=i, status="active",
               user_id=default_user.id, created_at=now)
        for i in range(1, 11)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    moves = [
        (threads[0].id, 10),  # first → last
        (threads[9].id, 1),   # last → first
        (threads[4].id, 3),   # middle forward
        (threads[2].id, 8),   # middle backward
        (threads[7].id, 5),   # middle forward
    ]
    for tid, pos in moves:
        await move_to_position(tid, default_user.id, pos, async_db)

    result = await async_db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == default_user.id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    positions = [row[0] for row in result.fetchall()]
    assert positions == list(range(1, 11)), f"Not sequential after multiple moves: {positions}"
    assert len(positions) == len(set(positions)), f"Duplicates after multiple moves: {positions}"
