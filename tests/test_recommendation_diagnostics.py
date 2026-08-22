"""Focused tests for recommendation-quality diagnostics."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session as SessionModel


async def _seed_session(
    db: AsyncSession,
    *,
    user_id: int,
    started_at: datetime,
    events: list[dict],
) -> int:
    """Create one session with the given ordered events."""
    session = SessionModel(user_id=user_id, started_at=started_at)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    for index, spec in enumerate(events):
        event = Event(
            session_id=session.id,
            timestamp=started_at + timedelta(seconds=spec.get("offset", index * 60)),
            **{key: value for key, value in spec.items() if key != "offset"},
        )
        db.add(event)
    await db.flush()
    return session.id


@pytest.mark.asyncio
async def test_diagnostics_empty_data(auth_client: AsyncClient) -> None:
    """Empty history returns a safe zeroed summary with no coverage gap."""
    response = await auth_client.get("/api/v1/recommendations/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["total_sessions"] == 0
    assert body["total_rolls"] == 0
    assert body["total_rates"] == 0
    assert body["total_snoozes"] == 0
    assert body["first_roll_adoption_rate"] == 0.0
    assert body["snoozes_per_completed_read"] == 0.0
    assert body["rating_average"] is None
    assert body["avg_time_to_acceptance_seconds"] is None
    assert body["effort_band_outcomes"] == []
    assert body["groups_by_control_mode"] == []
    assert body["coverage"]["instrumented_event_count"] == 0
    assert body["coverage"]["legacy_event_count"] == 0
    assert body["coverage"]["partial_coverage"] is False


@pytest.mark.asyncio
async def test_diagnostics_legacy_coverage_labeled(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Legacy events without selection_method are labeled, not silently mixed."""
    now = datetime.now(UTC)
    await _seed_session(
        async_db,
        user_id=1,
        started_at=now,
        events=[
            {
                "type": "roll",
                "die": 6,
                "result": 3,
                "selected_thread_id": 10,
                "selection_method": None,
                "thread_id": 10,
            },
            {
                "type": "rate",
                "rating": 4.0,
                "thread_id": 10,
                "selection_method": None,
            },
        ],
    )

    response = await auth_client.get("/api/v1/recommendations/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["legacy_event_count"] == 2
    assert body["coverage"]["instrumented_event_count"] == 0
    assert body["coverage"]["partial_coverage"] is True
    assert body["total_rolls"] == 1
    assert body["first_roll_adoption_rate"] == 1.0
    control_modes = {group["control_mode"] for group in body["groups_by_control_mode"]}
    assert "legacy" in control_modes


@pytest.mark.asyncio
async def test_diagnostics_full_representative_session(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A representative session exercises every documented metric."""
    now = datetime.now(UTC)
    await _seed_session(
        async_db,
        user_id=1,
        started_at=now,
        events=[
            {
                "type": "roll",
                "die": 6,
                "result": 2,
                "selected_thread_id": 10,
                "selection_method": "random",
                "thread_id": 10,
                "offset": 0,
            },
            {
                "type": "snooze",
                "die": 6,
                "die_after": 8,
                "thread_id": 10,
                "selection_method": "random",
                "offset": 600,
            },
            {
                "type": "snooze",
                "die": 8,
                "die_after": 10,
                "thread_id": 10,
                "selection_method": "random",
                "offset": 1200,
            },
            {
                "type": "rate",
                "rating": 4.0,
                "thread_id": 10,
                "selection_method": "random",
                "offset": 1800,
            },
        ],
    )
    await _seed_session(
        async_db,
        user_id=1,
        started_at=now + timedelta(hours=2),
        events=[
            {
                "type": "roll",
                "die": 8,
                "result": 5,
                "selected_thread_id": 12,
                "selection_method": "override",
                "thread_id": 12,
                "offset": 0,
            },
            {
                "type": "rate",
                "rating": 5.0,
                "thread_id": 12,
                "selection_method": "override",
                "offset": 300,
            },
        ],
    )

    response = await auth_client.get("/api/v1/recommendations/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["total_sessions"] == 2
    assert body["total_rolls"] == 2
    assert body["total_rates"] == 2
    assert body["total_snoozes"] == 2
    assert body["first_roll_adoption_rate"] == 1.0
    assert body["snoozes_per_completed_read"] == 1.0
    assert body["max_consecutive_snoozes_before_acceptance"] == 2
    assert body["avg_consecutive_snoozes_before_acceptance"] == 2.0
    assert body["avg_time_to_acceptance_seconds"] == 1050.0
    assert body["mode_corrections"] == 1
    assert body["rating_average"] == 4.5
    assert body["coverage"]["partial_coverage"] is False

    control_modes = {
        group["control_mode"]: group for group in body["groups_by_control_mode"]
    }
    assert "contextual_auto" in control_modes
    assert "explicit_correction" in control_modes
    assert control_modes["contextual_auto"]["rolls"] == 1
    assert control_modes["explicit_correction"]["rolls"] == 1

    bands = {outcome["die"]: outcome for outcome in body["effort_band_outcomes"]}
    assert 6 in bands
    assert 8 in bands
    assert bands[8]["band"] == "medium"


@pytest.mark.asyncio
async def test_diagnostics_user_scoped(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Diagnostics never include events owned by a different user."""
    now = datetime.now(UTC)
    other_user = __import__("app.models", fromlist=["User"]).User(username="other-diag-user")
    async_db.add(other_user)
    await async_db.flush()
    await async_db.refresh(other_user)
    await _seed_session(
        async_db,
        user_id=other_user.id,
        started_at=now,
        events=[
            {
                "type": "roll",
                "die": 6,
                "result": 2,
                "selected_thread_id": 50,
                "selection_method": "random",
                "thread_id": 50,
            },
            {
                "type": "rate",
                "rating": 4.0,
                "thread_id": 50,
                "selection_method": "random",
            },
        ],
    )

    response = await auth_client.get("/api/v1/recommendations/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["total_rolls"] == 0
    assert body["total_sessions"] == 0
