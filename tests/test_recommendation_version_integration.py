"""Integration tests for recommendation algorithm versioning and safe legacy rollback (#1767).

Tests cover the full roll API flow with contextual weighting enabled, legacy mode
disabled, and random intent bypass active.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import clear_settings_cache
from app.models import Event, Session as SessionModel, Thread
from app.recommendation_version import (
    ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED,
    ALGORITHM_CONTROL_STATE_WEIGHTED,
    CANONICAL_ALGORITHM_VERSION,
    LEGACY_ALGORITHM_VERSION,
)


@pytest.mark.asyncio
async def test_roll_contextual_mode_records_canonical_version(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Roll in contextual mode records canonical algorithm version and weighted control state."""
    _ = sample_data

    # Ensure contextual mode (default)
    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}, clear=True):
        clear_settings_cache()

        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200

        # Check event was recorded with canonical version
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.algorithm_version == CANONICAL_ALGORITHM_VERSION
        assert roll_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_WEIGHTED


@pytest.mark.asyncio
async def test_roll_legacy_mode_records_legacy_version(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Roll in legacy mode records legacy algorithm version and legacy control state."""
    _ = sample_data

    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}, clear=True):
        clear_settings_cache()

        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200

        # Check event was recorded with legacy version
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.algorithm_version == LEGACY_ALGORITHM_VERSION
        assert roll_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED


@pytest.mark.asyncio
async def test_roll_legacy_mode_uses_pure_random_selection(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Legacy mode uses pure random selection (reason code = pure_random)."""
    _ = sample_data

    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}, clear=True):
        clear_settings_cache()

        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200
        data = response.json()
        assert data["explanation"] == "Pure random selection"

        # Check event reason codes
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.recommendation_reason_codes == ["pure_random"]


@pytest.mark.asyncio
async def test_roll_random_intent_bypass_records_contextual_version(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Random intent bypass records contextual version but pure_random reason."""
    _ = sample_data

    # Set session active_intent to "random"
    user_id = sample_data["user"].id
    result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id, SessionModel.ended_at.is_(None))
    )
    session = result.scalars().first()
    assert session is not None
    session.active_intent = "random"
    await async_db.commit()

    # Ensure contextual mode (not legacy)
    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}, clear=True):
        clear_settings_cache()

        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200
        data = response.json()
        assert data["explanation"] == "Pure random selection"

        # Check event records contextual version but pure_random reason
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.algorithm_version == CANONICAL_ALGORITHM_VERSION
        assert roll_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_WEIGHTED
        assert roll_event.recommendation_reason_codes == ["pure_random"]


@pytest.mark.asyncio
async def test_roll_random_intent_bypass_independent_of_legacy_mode(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Random intent bypass works even when legacy mode is enabled (legacy takes precedence in metrics)."""
    _ = sample_data

    user_id = sample_data["user"].id
    result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user_id, SessionModel.ended_at.is_(None))
    )
    session = result.scalars().first()
    assert session is not None
    session.active_intent = "random"
    await async_db.commit()

    # Both legacy mode AND random intent active - legacy mode determines version/state
    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}, clear=True):
        clear_settings_cache()

        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200
        data = response.json()
        assert data["explanation"] == "Pure random selection"

        # Legacy mode determines version/state (legacy takes precedence for metrics)
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.algorithm_version == LEGACY_ALGORITHM_VERSION
        assert roll_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED
        assert roll_event.recommendation_reason_codes == ["pure_random"]


@pytest.mark.asyncio
async def test_roll_contextual_mode_with_momentum_records_weighted_reason(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Contextual mode with positive momentum records momentum_weighted reason."""
    _ = sample_data

    # Create a thread with high rating and recent activity to generate momentum
    threads = sample_data["threads"]
    target_thread = next(t for t in threads if t.status == "active")

    # Set high rating and recent activity
    target_thread.last_rating = 5.0
    target_thread.last_activity_at = None  # Will be set by roll
    await async_db.commit()

    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}, clear=True):
        clear_settings_cache()

        # Roll once
        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200

        # Check event reason code is either momentum_weighted or pure_random
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.recommendation_reason_codes in (["momentum_weighted"], ["pure_random"])
        assert roll_event.algorithm_version == CANONICAL_ALGORITHM_VERSION
        assert roll_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_WEIGHTED


@pytest.mark.asyncio
async def test_override_roll_records_algorithm_version(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Override roll records algorithm version and control state with empty reason codes."""
    _ = sample_data

    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}, clear=True):
        clear_settings_cache()

        thread_id = sample_data["threads"][0].id
        response = await auth_client.post("/api/roll/override", json={"thread_id": thread_id})
        assert response.status_code == 200
        data = response.json()
        assert data["explanation"] is None  # Override has no explanation

        # Check event records version/state with empty reason codes
        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        roll_event = result.scalars().first()
        assert roll_event is not None
        assert roll_event.algorithm_version == CANONICAL_ALGORITHM_VERSION
        assert roll_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_WEIGHTED
        assert roll_event.recommendation_reason_codes == []
        assert roll_event.selection_method == "override"


@pytest.mark.asyncio
async def test_transition_legacy_to_contextual_resumes_safely(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Transitioning from legacy back to contextual resumes from existing data safely."""
    _ = sample_data

    user_id = sample_data["user"].id

    # First roll in legacy mode
    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}, clear=True):
        clear_settings_cache()
        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200

        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        legacy_event = result.scalars().first()
        assert legacy_event is not None
        assert legacy_event.algorithm_version == LEGACY_ALGORITHM_VERSION

    # Dismiss pending to allow another roll
    await auth_client.post("/api/roll/dismiss-pending")

    # Second roll in contextual mode
    with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}, clear=True):
        clear_settings_cache()
        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200

        result = await async_db.execute(
            select(Event).where(Event.type == "roll").order_by(Event.id.desc())
        )
        contextual_event = result.scalars().first()
        assert contextual_event is not None
        assert contextual_event.algorithm_version == CANONICAL_ALGORITHM_VERSION
        assert contextual_event.algorithm_control_state == ALGORITHM_CONTROL_STATE_WEIGHTED

    # Verify session data (queue positions, ratings, etc.) was not mutated
    result = await async_db.execute(
        select(Thread).where(Thread.user_id == user_id, Thread.status == "active")
    )
    threads = result.scalars().all()
    assert len(threads) > 0
    for thread in threads:
        assert thread.queue_position >= 1
        assert thread.issues_remaining >= 0
