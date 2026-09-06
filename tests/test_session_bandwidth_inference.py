"""Tests for session bandwidth inference acceptance regression (issue #1711).

These tests verify that the session bandwidth initialization correctly
infers bandwidth from user history according to the acceptance criteria.
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models import Event, Session as SessionModel, Thread, User
from app.schemas.session import SessionListItem
from comic_pile.bandwidth import (
    apply_bandwidth_state,
    BANDWIDTH_SOURCE_CHOICES,
    CURRENT_BANDWIDTH_MODE_VERSION,
)
from comic_pile.session import get_or_create, resolve_current_session


@pytest.mark.asyncio
async def test_seeded_light_history_sessions_infer_light_with_meaningful_confidence(
    async_db: AsyncSession,
) -> None:
    """Seeded light-history sessions infer `light` with meaningful confidence."""
    # Create a user
    user_result = await async_db.execute(select(User).where(User.username == "testuser"))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(id=1, username="testuser")
        async_db.add(user)
        await async_db.commit()

    # Create light-history events for the user
    # Create a thread
    thread = Thread(
        id=1,
        user_id=user.id,
        title="Test Thread",
        format="comic",
        issues_remaining=5,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    # Create light reading history: short roll-to-rating times (light effort)
    base_time = datetime.now(UTC) - timedelta(days=1)
    for i in range(5):  # Enough observations for meaningful confidence
        # Roll event
        roll_event = Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            timestamp=base_time + timedelta(hours=i),
            die=6,
            result=3,
        )
        async_db.add(roll_event)
        await async_db.flush()

        # Rate event after a short delay (light effort: 5 minutes)
        rate_event = Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            rating=4.0,
            issues_read=1,
            timestamp=base_time + timedelta(hours=i, minutes=5),  # 5 minutes later
            die_after=6,
        )
        async_db.add(rate_event)
        await async_db.flush()

    # Create a new session for this user (should trigger bandwidth initialization)
    new_session = await get_or_create(async_db, user_id=user.id)

    # Verify that the session inferred light bandwidth with meaningful confidence
    assert new_session.predicted_bandwidth == "light"
    assert new_session.active_bandwidth == "light"
    assert new_session.bandwidth_source == "inferred"
    # Confidence should be meaningful (not just the default 0.1)
    assert new_session.bandwidth_confidence > 0.2


@pytest.mark.asyncio
async def test_seeded_heavy_history_sessions_infer_deep_where_evidence_supports_it(
    async_db: AsyncSession,
) -> None:
    """Seeded heavy-history sessions infer `deep` where evidence supports it."""
    # Create a user
    user_result = await async_db.execute(select(User).where(User.username == "testuser2"))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(id=2, username="testuser2")
        async_db.add(user)
        await async_db.commit()

    # Create a thread
    thread = Thread(
        id=2,
        user_id=user.id,
        title="Test Thread 2",
        format="comic",
        issues_remaining=5,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    # Create heavy-history events for the user
    # Create heavy reading history: long roll-to-rating times (deep effort)
    base_time = datetime.now(UTC) - timedelta(days=1)
    for i in range(5):  # Enough observations for meaningful confidence
        # Roll event
        roll_event = Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            timestamp=base_time + timedelta(hours=i),
            die=6,
            result=3,
        )
        async_db.add(roll_event)
        await async_db.flush()

        # Rate event after a long delay (deep effort: 25 minutes)
        rate_event = Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            rating=4.0,
            issues_read=1,
            timestamp=base_time + timedelta(hours=i, minutes=25),  # 25 minutes later
            die_after=6,
        )
        async_db.add(rate_event)
        await async_db.flush()

    # Create a new session for this user (should trigger bandwidth initialization)
    new_session = await get_or_create(async_db, user_id=user.id)

    # Verify that the session inferred deep bandwidth
    assert new_session.predicted_bandwidth == "deep"
    assert new_session.active_bandwidth == "deep"
    assert new_session.bandwidth_source == "inferred"
    # Confidence should be meaningful
    assert new_session.bandwidth_confidence > 0.2


@pytest.mark.asyncio
async def test_sparse_contradictory_history_falls_back_to_balanced(
    async_db: AsyncSession,
) -> None:
    """Sparse/contradictory history falls back to `balanced`."""
    # Create a user
    user_result = await async_db.execute(select(User).where(User.username == "testuser3"))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(id=3, username="testuser3")
        async_db.add(user)
        await async_db.commit()

    # Create a thread
    thread = Thread(
        id=3,
        user_id=user.id,
        title="Test Thread 3",
        format="comic",
        issues_remaining=5,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    # Create sparse/contradictory history: very few observations
    base_time = datetime.now(UTC) - timedelta(days=1)
    # Only 2 observations (not enough for meaningful prediction)
    for i in range(2):
        # Roll event
        roll_event = Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            timestamp=base_time + timedelta(hours=i),
            die=6,
            result=3,
        )
        async_db.add(roll_event)
        await async_db.flush()

        # Rate event after medium delay
        rate_event = Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            rating=3.0,
            issues_read=1,
            timestamp=base_time + timedelta(hours=i, minutes=15),  # 15 minutes later
            die_after=6,
        )
        async_db.add(rate_event)
        await async_db.flush()

    # Create a new session for this user (should trigger bandwidth initialization)
    new_session = await get_or_create(async_db, user_id=user.id)

    # Verify that the session falls back to balanced due to sparse history
    assert new_session.predicted_bandwidth == "balanced"
    assert new_session.active_bandwidth == "balanced"
    assert new_session.bandwidth_source == "inferred"
    # Confidence should be low due to sparse history
    assert new_session.bandwidth_confidence <= 0.2


@pytest.mark.asyncio
async def test_session_initialization_does_not_continuously_rewrite_mode_on_refresh(
    async_db: AsyncSession,
) -> None:
    """Session initialization does not continuously rewrite mode on refresh."""
    # Create a user
    user_result = await async_db.execute(select(User).where(User.username == "testuser4"))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(id=4, username="testuser4")
        async_db.add(user)
        await async_db.commit()

    # Create a thread
    thread = Thread(
        id=4,
        user_id=user.id,
        title="Test Thread 4",
        format="comic",
        issues_remaining=5,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    # Manually set bandwidth state to simulate an explicit override
    await apply_bandwidth_state(
        async_db,
        session,
        predicted_bandwidth="deep",
        active_bandwidth="light",
        bandwidth_source="manual",
        bandwidth_confidence=0.9,
    )
    await async_db.commit()

    # Record the initial state
    predicted_before = session.predicted_bandwidth
    active_before = session.active_bandwidth
    source_before = session.bandwidth_source
    confidence_before = session.bandwidth_confidence
    updated_at_before = session.bandwidth_updated_at

    # Get the session multiple times (simulating refreshes)
    for _ in range(3):
        resolved_session = await get_or_create(async_db, user_id=user.id)
        assert resolved_session.id == session.id

        # Verify that the manually set state is preserved (not rewritten)
        assert resolved_session.predicted_bandwidth == predicted_before
        assert resolved_session.active_bandwidth == active_before
        assert resolved_session.bandwidth_source == source_before
        assert resolved_session.bandwidth_confidence == confidence_before
        # The update timestamp should also be preserved
        assert resolved_session.bandwidth_updated_at == updated_at_before

    # Also verify from direct database query
    await async_db.refresh(session)
    assert session.predicted_bandwidth == predicted_before
    assert session.active_bandwidth == active_before
    assert session.bandwidth_source == source_before
    assert session.bandwidth_confidence == confidence_before
    assert session.bandwidth_updated_at == updated_at_before


@pytest.mark.asyncio
async def test_bootstrap_exposes_the_same_canonical_state(
    async_db: AsyncSession,
) -> None:
    """Bootstrap exposes the same canonical state."""
    # Create a user
    user_result = await async_db.execute(select(User).where(User.username == "testuser5"))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(id=5, username="testuser5")
        async_db.add(user)
        await async_db.commit()

    # Create a thread
    thread = Thread(
        id=5,
        user_id=user.id,
        title="Test Thread 5",
        format="comic",
        issues_remaining=5,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    # Create some history to get a non-neutral prediction
    base_time = datetime.now(UTC) - timedelta(days=1)
    for i in range(330:         for i in range(3):
331:             # Roll event
332:             roll_event = Event(
333:                 type="roll",
334:                 session_id=session.id,
335:                 selected_thread_id=thread.id,
336:                 timestamp=base_time + timedelta(hours=i),
337:                 die=6,
338:                 result=3,
339:             )
340:             async_db.add(roll_event)
341:             await async_db.flush()
342: 
343:             # Rate event after a short delay (light effort)
344:             rate_event = Event(
345:                 type="rate",
346:                 session_id=session.id,
347:                 thread_id=thread.id,
348:                 rating=4.0,
349:                 issues_read=1,
350:                 timestamp=base_time + timedelta(hours=i, minutes=5),  # 5 minutes later
351:                 die_after=6,
352:             )
353:             async_db.add(rate_event)
354:             await async_db.flush()
355: 
356:     # Get the session via different methods and verify they expose the same state
357:     # Method 1: get_or_create
358:     session1 = await get_or_create(async_db, user_id=user.id)
359: 
360:     # Method 2: resolve_current_session
361:     session2 = await resolve_current_session(async_db, user_id=user.id)
362: 
363:     # Method 3: direct query
364:     session_result = await async_db.execute(
365:         select(SessionModel).where(SessionModel.id == session.id)
366:     )
367:     session3 = session_result.scalar_one()
368: 
369:     # All should expose the same canonical state
370:     assert session1.predicted_bandwidth == session2.predicted_bandwidth == session3.predicted_bandwidth
371:     assert session1.active_bandwidth == session2.active_bandwidth == session3.active_bandwidth
372:     assert session1.bandwidth_source == session2.bandwidth_source == session3.bandwidth_source
373:     assert session1.bandwidth_confidence == session2.bandwidth_confidence == session3.bandwidth_confidence


@pytest.mark.asyncio
async def test_roll_selection_remains_legacy_unweighted(
    async_db: AsyncSession,
) -> None:
    """Roll selection remains legacy/unweighted."""
    # This test verifies that bandwidth inference doesn't affect roll selection
    # The bandwidth selection logic is in app/services/bandwidth_selection.py
    # and should only affect selection when bandwidth is actually used for weighting
    # which happens in Phase 3, not Phase 2
    
    # For now, we can verify that the bandwidth state is properly separated
    # from the roll selection mechanism by checking that:
    # 1. Sessions have bandwidth state
    # 2. But roll selection still works based on the die pool
    
    # Create a user
    user_result = await db.execute(select(User).where(User.username == "testuser6"))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(id=6, username="testuser6")
        db.add(user)
        await db.commit()

    # Create a thread
    thread = Thread(
        id=6,
        user_id=user.id,
        title="Test Thread 6",
        format="comic",
        issues_remaining=5,
    )
    db.add(thread)
    await db.flush()

    # Create a session
    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    await db.flush()

    # Create some history
    base_time = datetime.now(UTC) - timedelta(days=1)
    for i in range(3):
        # Roll event
        roll_event = Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            timestamp=base_time + timedelta(hours=i),
            die=6,
            result=3,
        )
        db.add(roll_event)
        await db.flush()

        # Rate event
        rate_event = Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            rating=4.0,
            issues_read=1,
            timestamp=base_time + timedelta(hours=i, minutes=5),
            die_after=6,
        )
        db.add(rate_event)
        await db.flush()

    # Get the session (should initialize bandwidth)
    session_with_bandwidth = await get_or_create(async_db, user_id=user.id)

    # Verify bandwidth state is set
    assert session_with_bandwidth.predicted_bandwidth is not None
    assert session_with_bandwidth.active_bandwidth is not None
    assert session_with_bandwidth.bandwidth_source is not None

    # Verify that the session still functions for roll selection
    # (this is more of a smoke test - the actual roll selection logic
    # is tested elsewhere)
    assert session_with_bandwidth.start_die == 6
    assert session_with_bandwidth.user_id == user.id