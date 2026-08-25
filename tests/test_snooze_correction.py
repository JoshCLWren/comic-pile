"""Tests for structured Snooze correction guidance in the API response.

Issue: #1726 — return structured correction result so the frontend can
later decide whether to show a clarification sheet.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_snooze_returns_correction_guidance(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POST /snooze/ returns a correction object in the response."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Heavy Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    data = response.json()

    # Verify correction guidance is present
    assert "correction" in data
    correction = data["correction"]
    assert correction is not None
    assert isinstance(correction, dict)

    # Verify correction fields
    assert "bandwidth_changed" in correction
    assert "active_bandwidth" in correction
    assert "active_confidence" in correction
    assert "predicted_bandwidth" in correction
    assert "reason_code" in correction
    assert "suggest_clarification" in correction

    # bandwidth_changed should be a bool
    assert isinstance(correction["bandwidth_changed"], bool)

    # active_bandwidth should be a valid level or None
    if correction["active_bandwidth"] is not None:
        assert correction["active_bandwidth"] in ("light", "balanced", "deep")

    # active_confidence should be a valid float or None
    if correction["active_confidence"] is not None:
        assert 0.0 <= correction["active_confidence"] <= 1.0

    # suggest_clarification should be a bool
    assert isinstance(correction["suggest_clarification"], bool)


@pytest.mark.asyncio
async def test_snooze_returns_bandwidth_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POST /snooze/ returns session bandwidth fields."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    data = response.json()

    # Verify bandwidth state is present in session response
    assert "bandwidth" in data
    bandwidth = data["bandwidth"]
    assert bandwidth is not None
    assert isinstance(bandwidth, dict)

    # Verify bandwidth fields
    assert "active_bandwidth" in bandwidth
    assert "confidence" in bandwidth
    assert "source" in bandwidth
    assert "predicted_bandwidth" in bandwidth

    # After a snooze, bandwidth should be set
    assert bandwidth["active_bandwidth"] is not None
    assert bandwidth["active_bandwidth"] in ("light", "balanced", "deep")
    assert bandwidth["source"] == "snooze"
    assert bandwidth["confidence"] is not None
    assert 0.0 <= bandwidth["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_snooze_does_not_demote_queue_position(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozing does not change the thread's durable queue position (issue #1721)."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Position Test",
        format="Comic",
        issues_remaining=5,
        queue_position=3,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    original_position = thread.queue_position

    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    # Verify the thread's queue position is unchanged
    await async_db.refresh(thread)
    assert thread.queue_position == original_position


@pytest.mark.asyncio
async def test_snooze_correction_has_reason_code(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snooze correction includes a valid compact reason code."""
    from tests.conftest import get_or_create_user_async
    from comic_pile.bandwidth_correction import CorrectionReason

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Reason Code Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200

    data = response.json()
    correction = data["correction"]
    assert correction is not None

    valid_codes = [r.value for r in CorrectionReason]
    assert correction["reason_code"] in valid_codes


@pytest.mark.asyncio
async def test_multiple_snoozes_track_consecutive(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Consecutive snoozes are tracked and affect correction behavior."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create multiple threads
    threads = []
    for i in range(3):
        thread = Thread(
            title=f"Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
        threads.append(thread)
    await async_db.commit()
    for t in threads:
        await async_db.refresh(t)

    # Snooze first thread
    event1 = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=threads[0].id,
        selection_method="random",
        session_id=session.id,
        thread_id=threads[0].id,
    )
    async_db.add(event1)
    session.pending_thread_id = threads[0].id
    await async_db.commit()

    response1 = await auth_client.post("/api/snooze/")
    assert response1.status_code == 200
    data1 = response1.json()

    # First snooze: consecutive_snoozes=1, so no clarification
    assert data1["correction"]["suggest_clarification"] is False

    # Set up second thread as pending and snooze
    event2 = Event(
        type="roll",
        die=8,
        result=1,
        selected_thread_id=threads[1].id,
        selection_method="random",
        session_id=session.id,
        thread_id=threads[1].id,
    )
    async_db.add(event2)
    session.pending_thread_id = threads[1].id
    await async_db.commit()

    response2 = await auth_client.post("/api/snooze/")
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["correction"] is not None
