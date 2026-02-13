"""Edge case tests for queue reordering operations."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User
from httpx import AsyncClient
from comic_pile.queue import move_to_back, move_to_front, move_to_position


@pytest.mark.asyncio
async def test_move_to_position_clamps_to_max(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Moving to position > max_position clamps to max."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.get("/api/v1/threads/")
    threads = response.json()
    active_threads = [t for t in threads if t["status"] == "active"]
    max_position = len(active_threads)

    response = await auth_client.put(
        f"/api/v1/queue/threads/{thread_id}/position/", json={"new_position": max_position + 10}
    )
    assert response.status_code == 200

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    assert thread.queue_position == max_position


@pytest.mark.asyncio
async def test_move_to_position_when_no_threads(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Moving to position when no threads handles gracefully."""
    from app.models import Thread as ThreadModel

    thread = ThreadModel(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.put(
        f"/api/v1/queue/threads/{thread.id}/position/", json={"new_position": 1}
    )
    assert response.status_code == 200

    thread = await async_db.get(ThreadModel, thread.id)
    assert thread is not None
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_to_front_nonexistent_thread(
    async_db: AsyncSession, default_user: User, sample_data: dict
) -> None:
    """move_to_front with non-existent thread_id returns early without error."""
    nonexistent_thread_id = 99999

    original_positions = {t.id: t.queue_position for t in sample_data["threads"]}

    await move_to_front(nonexistent_thread_id, default_user.id, async_db)

    current_positions = {t.id: t.queue_position for t in sample_data["threads"]}

    assert original_positions == current_positions


@pytest.mark.asyncio
async def test_move_to_back_nonexistent_thread(
    async_db: AsyncSession, default_user: User, sample_data: dict
) -> None:
    """move_to_back with non-existent thread_id returns early without error."""
    nonexistent_thread_id = 99999

    original_positions = {t.id: t.queue_position for t in sample_data["threads"]}

    await move_to_back(nonexistent_thread_id, default_user.id, async_db)

    current_positions = {t.id: t.queue_position for t in sample_data["threads"]}

    assert original_positions == current_positions


@pytest.mark.asyncio
async def test_move_to_back_no_active_threads(async_db: AsyncSession, default_user: User) -> None:
    """move_to_back when max_position is None (no active threads) returns early without error."""
    from datetime import UTC, datetime

    thread = Thread(
        title="Isolated Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=0,
        status="paused",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    original_position = thread.queue_position

    await move_to_back(thread.id, default_user.id, async_db)

    await async_db.refresh(thread)
    assert thread.queue_position == original_position


@pytest.mark.asyncio
async def test_move_to_position_nonexistent_thread(
    async_db: AsyncSession, default_user: User, sample_data: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """move_to_position with non-existent thread_id logs error and returns early."""
    nonexistent_thread_id = 99999

    original_positions = {t.id: t.queue_position for t in sample_data["threads"]}

    with caplog.at_level("ERROR"):
        await move_to_position(nonexistent_thread_id, default_user.id, 1, async_db)

    current_positions = {t.id: t.queue_position for t in sample_data["threads"]}

    assert original_positions == current_positions
    assert any(
        f"Thread {nonexistent_thread_id} not found for user {default_user.id}" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_move_to_position_thread_not_in_active_list(
    async_db: AsyncSession, default_user: User, caplog: pytest.LogCaptureFixture
) -> None:
    """move_to_position with thread having queue_position < 1 logs error and returns early."""
    from datetime import UTC, datetime

    thread = Thread(
        title="Paused Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=0,
        status="paused",
        user_id=default_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    original_position = thread.queue_position

    with caplog.at_level("ERROR"):
        await move_to_position(thread.id, default_user.id, 1, async_db)

    await async_db.refresh(thread)
    assert thread.queue_position == original_position
    assert any(
        f"Target thread {thread.id} not found in active threads list" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_move_to_position_clamps_negative_position(
    async_db: AsyncSession, default_user: User, sample_data: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """move_to_position with new_position < 1 clamps to 1."""
    thread_id = sample_data["threads"][0].id

    with caplog.at_level("WARNING"):
        await move_to_position(thread_id, default_user.id, 0, async_db)

    thread = await async_db.get(Thread, thread_id)
    assert thread is not None
    assert thread.queue_position == 1
    assert any("new_position 0 < 1, setting to 1" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_get_roll_pool(async_db: AsyncSession, default_user: User, sample_data: dict) -> None:
    """get_roll_pool returns all active threads ordered by position."""
    from comic_pile.queue import get_roll_pool

    pool = await get_roll_pool(default_user.id, async_db)

    active_threads = [t for t in sample_data["threads"] if t.status == "active"]
    assert len(pool) == len(active_threads)

    positions = [t.queue_position for t in pool]
    assert positions == sorted(positions)


@pytest.mark.asyncio
async def test_get_stale_threads(async_db: AsyncSession, default_user: User) -> None:
    """get_stale_threads returns threads not read in specified days."""
    from datetime import UTC, datetime, timedelta
    from comic_pile.queue import get_stale_threads

    now = datetime.now(UTC)
    stale_date = now - timedelta(days=10)
    recent_date = now - timedelta(days=2)

    stale_thread = Thread(
        title="Stale Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        last_activity_at=stale_date,
        created_at=now,
    )
    recent_thread = Thread(
        title="Recent Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        last_activity_at=recent_date,
        created_at=now,
    )
    no_activity_thread = Thread(
        title="No Activity Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=3,
        status="active",
        user_id=default_user.id,
        last_activity_at=None,
        created_at=now,
    )

    async_db.add_all([stale_thread, recent_thread, no_activity_thread])
    await async_db.commit()

    stale_threads = await get_stale_threads(default_user.id, async_db, days=7)

    assert len(stale_threads) == 2
    stale_thread_ids = {t.id for t in stale_threads}
    assert stale_thread.id in stale_thread_ids
    assert no_activity_thread.id in stale_thread_ids
    assert recent_thread.id not in stale_thread_ids


@pytest.mark.asyncio
async def test_move_to_front_already_at_position_1(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_front when thread is already at position 1 returns early without changes."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_front

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]

    async_db.add_all(threads)
    await async_db.commit()

    for thread in threads:
        await async_db.refresh(thread)

    thread_a = threads[0]
    thread_a_id = thread_a.id
    original_position = thread_a.queue_position

    assert original_position == 1

    await move_to_front(thread_a_id, default_user.id, async_db)

    await async_db.refresh(thread_a)
    assert thread_a.queue_position == 1

    thread_b = await async_db.get(Thread, threads[1].id)
    assert thread_b is not None
    assert thread_b.queue_position == 2


@pytest.mark.asyncio
async def test_move_to_front_from_middle_position(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_front: Moving thread from position > 1 to front shifts all preceding threads back."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_front

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread C",
            format="Comic",
            issues_remaining=8,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread D",
            format="Comic",
            issues_remaining=3,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread E",
            format="Comic",
            issues_remaining=6,
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

    thread_c = threads[2]
    thread_c_id = thread_c.id

    assert thread_c.queue_position == 3

    await move_to_front(thread_c_id, default_user.id, async_db)

    await async_db.refresh(thread_c)
    assert thread_c.queue_position == 1

    for thread in threads:
        await async_db.refresh(thread)

    thread_a = await async_db.get(Thread, threads[0].id)
    thread_b = await async_db.get(Thread, threads[1].id)
    thread_d = await async_db.get(Thread, threads[3].id)
    thread_e = await async_db.get(Thread, threads[4].id)

    assert thread_a is not None
    assert thread_b is not None
    assert thread_d is not None
    assert thread_e is not None
    assert thread_a.queue_position == 2
    assert thread_b.queue_position == 3
    assert thread_d.queue_position == 4
    assert thread_e.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_back_already_at_max_position(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_back when thread is already at max_position returns early without changes."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_back

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
    ]

    async_db.add_all(threads)
    await async_db.commit()

    for thread in threads:
        await async_db.refresh(thread)

    thread_b = threads[1]
    thread_b_id = thread_b.id
    original_position = thread_b.queue_position

    assert original_position == 2

    await move_to_back(thread_b_id, default_user.id, async_db)

    await async_db.refresh(thread_b)
    assert thread_b.queue_position == 2

    thread_a = await async_db.get(Thread, threads[0].id)
    assert thread_a is not None
    assert thread_a.queue_position == 1


@pytest.mark.asyncio
async def test_move_to_back_from_front_position(async_db: AsyncSession, default_user: User) -> None:
    """move_to_back: Moving thread from position < max to back shifts all following threads forward."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_back

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread C",
            format="Comic",
            issues_remaining=8,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread D",
            format="Comic",
            issues_remaining=3,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread E",
            format="Comic",
            issues_remaining=6,
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

    thread_a = threads[0]
    thread_a_id = thread_a.id

    assert thread_a.queue_position == 1

    await move_to_back(thread_a_id, default_user.id, async_db)

    await async_db.refresh(thread_a)
    assert thread_a.queue_position == 5

    for thread in threads:
        await async_db.refresh(thread)

    thread_b = await async_db.get(Thread, threads[1].id)
    thread_c = await async_db.get(Thread, threads[2].id)
    thread_d = await async_db.get(Thread, threads[3].id)
    thread_e = await async_db.get(Thread, threads[4].id)

    assert thread_b is not None
    assert thread_c is not None
    assert thread_d is not None
    assert thread_e is not None
    assert thread_b.queue_position == 1
    assert thread_c.queue_position == 2
    assert thread_d.queue_position == 3
    assert thread_e.queue_position == 4


@pytest.mark.asyncio
async def test_move_to_position_normalizes_non_sequential_positions(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_position normalizes non-sequential queue positions before moving."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_position

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread C",
            format="Comic",
            issues_remaining=8,
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

    thread_b = threads[1]
    thread_b_id = thread_b.id

    assert thread_b.queue_position == 3

    await move_to_position(thread_b_id, default_user.id, 1, async_db)

    await async_db.refresh(thread_b)
    assert thread_b.queue_position == 1

    thread_a = await async_db.get(Thread, threads[0].id)
    thread_c = await async_db.get(Thread, threads[2].id)

    assert thread_a is not None
    assert thread_c is not None
    assert thread_a.queue_position == 2
    assert thread_c.queue_position == 3


@pytest.mark.asyncio
async def test_move_to_position_backward_movement(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_position: Moving thread backward (current < new) shifts threads in between forward."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_position

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread C",
            format="Comic",
            issues_remaining=8,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread D",
            format="Comic",
            issues_remaining=3,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread E",
            format="Comic",
            issues_remaining=6,
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

    thread_b = threads[1]
    thread_b_id = thread_b.id

    assert thread_b.queue_position == 2

    await move_to_position(thread_b_id, default_user.id, 4, async_db)

    await async_db.refresh(thread_b)
    assert thread_b.queue_position == 4

    for thread in threads:
        await async_db.refresh(thread)

    thread_a = await async_db.get(Thread, threads[0].id)
    thread_c = await async_db.get(Thread, threads[2].id)
    thread_d = await async_db.get(Thread, threads[3].id)
    thread_e = await async_db.get(Thread, threads[4].id)

    assert thread_a is not None
    assert thread_c is not None
    assert thread_d is not None
    assert thread_e is not None
    assert thread_a.queue_position == 1
    assert thread_c.queue_position == 2
    assert thread_d.queue_position == 3
    assert thread_e.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_position_forward_movement(
    async_db: AsyncSession, default_user: User
) -> None:
    """move_to_position: Moving thread forward (current > new) shifts threads in between backward."""
    from datetime import UTC, datetime
    from comic_pile.queue import move_to_position

    now = datetime.now(UTC)
    threads = [
        Thread(
            title="Thread A",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread B",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread C",
            format="Comic",
            issues_remaining=8,
            queue_position=3,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread D",
            format="Comic",
            issues_remaining=3,
            queue_position=4,
            status="active",
            user_id=default_user.id,
            created_at=now,
        ),
        Thread(
            title="Thread E",
            format="Comic",
            issues_remaining=6,
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

    thread_d = threads[3]
    thread_d_id = thread_d.id

    assert thread_d.queue_position == 4

    await move_to_position(thread_d_id, default_user.id, 2, async_db)

    await async_db.refresh(thread_d)
    assert thread_d.queue_position == 2

    for thread in threads:
        await async_db.refresh(thread)

    thread_a = await async_db.get(Thread, threads[0].id)
    thread_b = await async_db.get(Thread, threads[1].id)
    thread_c = await async_db.get(Thread, threads[2].id)
    thread_e = await async_db.get(Thread, threads[4].id)

    assert thread_a is not None
    assert thread_b is not None
    assert thread_c is not None
    assert thread_e is not None
    assert thread_a.queue_position == 1
    assert thread_b.queue_position == 3
    assert thread_c.queue_position == 4
    assert thread_e.queue_position == 5
