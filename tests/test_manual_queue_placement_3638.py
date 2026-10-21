"""Regression coverage for #3638: manual queue placement survives rating.

The reader's explicit move-to-front/back/position is recorded in
``Thread.queue_position_is_manual`` so the automatic below-threshold rating
demotion cannot silently discard it. Completion, shuffle, exclusion, and
reactivation end the claim.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Snapshot, Thread, User
from app.services import thread_service
from comic_pile.queue import move_to_front, move_to_safe_position, shuffle_queue
from comic_pile.reading_session import create_session_start_snapshot
from tests.conftest import get_or_create_user_async


async def _add_active_threads(
    async_db: AsyncSession,
    user: User,
    *,
    count: int,
    issues_remaining: int = 5,
) -> list[Thread]:
    """Create ``count`` active legacy-tracking threads at positions 1..N."""
    threads = [
        Thread(
            title=f"Manual Queue Thread {position}",
            format="Comic",
            issues_remaining=issues_remaining,
            queue_position=position,
            status="active",
            user_id=user.id,
        )
        for position in range(1, count + 1)
    ]
    async_db.add_all(threads)
    await async_db.flush()
    return threads


async def _prepare_rating(
    async_db: AsyncSession,
    user: User,
    thread: Thread,
    *,
    start_die: int = 6,
) -> ReadingSession:
    """Create a pending rating session and matching roll event."""
    session = ReadingSession(start_die=start_die, user_id=user.id)
    async_db.add(session)
    await async_db.flush()
    session.pending_thread_id = thread.id
    async_db.add(
        Event(
            type="roll",
            die=start_die,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )
    await async_db.commit()
    await async_db.refresh(session)
    return session


async def _session_start_thread_states(
    async_db: AsyncSession, session_id: int
) -> dict[str, dict]:
    """Return the per-thread state stored in a session's start snapshot."""
    result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .where(Snapshot.description == "Session start")
    )
    snapshot = result.scalars().first()
    assert snapshot is not None
    return snapshot.thread_states


@pytest.mark.asyncio
async def test_explicit_move_to_front_marks_placement_manual(
    async_db: AsyncSession, default_user: User
) -> None:
    """An explicit move records that the reader chose the placement."""
    threads = await _add_active_threads(async_db, default_user, count=5)
    target = threads[4]

    await move_to_front(target.id, default_user.id, async_db, manual=True)
    await async_db.refresh(target)

    assert target.queue_position == 1
    assert target.queue_position_is_manual is True


@pytest.mark.asyncio
async def test_automatic_safe_position_does_not_mark_placement_manual(
    async_db: AsyncSession, default_user: User
) -> None:
    """Automatic placement is not misreported as an explicit reader choice."""
    threads = await _add_active_threads(async_db, default_user, count=5)
    target = threads[0]

    await move_to_safe_position(target.id, default_user.id, 6, async_db)
    await async_db.refresh(target)

    assert target.queue_position > 1
    assert target.queue_position_is_manual is False


@pytest.mark.asyncio
async def test_below_threshold_rating_keeps_manual_front_placement(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A low rating must not demote a series the reader moved to the front."""
    user = await get_or_create_user_async(async_db)
    threads = await _add_active_threads(async_db, user, count=12)
    target = threads[4]  # position 5 before the explicit move

    move_response = await auth_client.put(f"/api/v1/queue/threads/{target.id}/front/")
    assert move_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position == 1
    assert target.queue_position_is_manual is True

    await _prepare_rating(async_db, user, target)

    rate_response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 3.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position == 1
    assert target.queue_position_is_manual is True


@pytest.mark.asyncio
async def test_completing_series_clears_manual_placement(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Completion leaves the active queue, so the manual claim is cleared."""
    user = await get_or_create_user_async(async_db)
    threads = await _add_active_threads(async_db, user, count=3, issues_remaining=1)
    target = threads[2]

    await move_to_front(target.id, user.id, async_db, manual=True)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is True

    await _prepare_rating(async_db, user, target)

    rate_response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 5.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    await async_db.refresh(target)
    assert target.status == "completed"
    assert target.queue_position_is_manual is False


@pytest.mark.asyncio
async def test_shuffle_clears_manual_placements(
    async_db: AsyncSession, default_user: User
) -> None:
    """Shuffle is an explicit reorder, so every manual claim is cleared."""
    threads = await _add_active_threads(async_db, default_user, count=3)
    target = threads[2]

    await move_to_front(target.id, default_user.id, async_db, manual=True)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is True

    await shuffle_queue(default_user.id, async_db)

    for thread in threads:
        await async_db.refresh(thread)
        assert thread.queue_position_is_manual is False


@pytest.mark.asyncio
async def test_exclude_and_restore_clear_manual_placement(
    async_db: AsyncSession, default_user: User
) -> None:
    """Removing and restoring a series starts a fresh queue entry."""
    threads = await _add_active_threads(async_db, default_user, count=3)
    target = threads[2]

    await move_to_front(target.id, default_user.id, async_db, manual=True)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is True

    await thread_service.exclude_thread(async_db, default_user.id, target.id)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is False

    await thread_service.restore_thread(async_db, default_user.id, target.id)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is False


@pytest.mark.asyncio
async def test_undo_restores_manual_placement_cleared_by_completion(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Undoing a completion restores the pre-rating manual claim."""
    user = await get_or_create_user_async(async_db)
    threads = await _add_active_threads(async_db, user, count=3, issues_remaining=1)
    target = threads[2]

    await move_to_front(target.id, user.id, async_db, manual=True)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is True

    session = await _prepare_rating(async_db, user, target)
    rate_response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 5.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200
    await async_db.refresh(target)
    assert target.queue_position_is_manual is False

    snapshots_response = await auth_client.get(f"/api/v1/undo/{session.id}/snapshots")
    assert snapshots_response.status_code == 200
    snapshot_id = snapshots_response.json()["snapshots"][0]["id"]
    undo_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshot_id}"
    )
    assert undo_response.status_code == 200

    restored = await async_db.execute(select(Thread).where(Thread.id == target.id))
    restored_target = restored.scalar_one()
    await async_db.refresh(restored_target)
    assert restored_target.queue_position_is_manual is True


@pytest.mark.asyncio
async def test_session_start_snapshot_records_manual_placement(
    async_db: AsyncSession, default_user: User
) -> None:
    """The session-start checkpoint keeps the reader's placement claim."""
    threads = await _add_active_threads(async_db, default_user, count=3)
    target = threads[2]

    await move_to_front(target.id, default_user.id, async_db, manual=True)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is True

    session = ReadingSession(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    snapshot_states = await _session_start_thread_states(async_db, session.id)
    assert snapshot_states[str(target.id)]["queue_position_is_manual"] is True


@pytest.mark.asyncio
async def test_restore_session_start_restores_manual_placement(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Restoring a session start brings the manual placement claim back."""
    user = await get_or_create_user_async(async_db)
    threads = await _add_active_threads(async_db, user, count=3)
    target = threads[2]

    await move_to_front(target.id, user.id, async_db, manual=True)
    await async_db.refresh(target)
    assert target.queue_position_is_manual is True

    session = ReadingSession(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await create_session_start_snapshot(async_db, session)

    # A series that completed during the session no longer holds the claim.
    target.queue_position_is_manual = False
    await async_db.commit()

    restore_response = await auth_client.post(
        f"/api/v1/sessions/{session.id}/restore-session-start"
    )
    assert restore_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position_is_manual is True


@pytest.mark.asyncio
async def test_below_threshold_rating_keeps_manual_middle_position(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A low rating must not demote a series the reader placed mid-queue."""
    user = await get_or_create_user_async(async_db)
    threads = await _add_active_threads(async_db, user, count=12)
    target = threads[4]  # position 5 before the explicit move

    move_response = await auth_client.put(
        f"/api/v1/queue/threads/{target.id}/position/",
        json={"new_position": 3},
    )
    assert move_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position == 3
    assert target.queue_position_is_manual is True

    await _prepare_rating(async_db, user, target)

    rate_response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 3.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position == 3
    assert target.queue_position_is_manual is True


@pytest.mark.asyncio
async def test_same_position_move_keeps_manual_claim_after_low_rating(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Re-selecting the current position still records the manual claim."""
    user = await get_or_create_user_async(async_db)
    threads = await _add_active_threads(async_db, user, count=4)
    target = threads[0]

    move_response = await auth_client.put(
        f"/api/v1/queue/threads/{target.id}/position/",
        json={"new_position": 1},
    )
    assert move_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position == 1
    assert target.queue_position_is_manual is True

    await _prepare_rating(async_db, user, target)

    rate_response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 3.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    await async_db.refresh(target)
    assert target.queue_position == 1
    assert target.queue_position_is_manual is True
