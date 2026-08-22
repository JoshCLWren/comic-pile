"""API tests for GET /api/roll/events/{event_id}/recommendation-explanation.

Requires aPhase 8 (or simulated) recommendation_context on the roll event record.
Because the Event model does not yet carry a ``recommendation_context`` column
at this phase boundary, these tests use ``setattr`` on the event instance after
reading it from the database — a well-established SQLAlchemy test pattern that
keeps the migration with Phase 8 while making Phase 9 contract verifiable here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.models import Event, Session as SessionModel, Thread, User
from app.services.recommendation_explanation import RecommendationExplanationProjection


def _make_roll_event_row(
    event: Event,
    *,
    selection_method: str = "random",
    recommendation_context: dict | None = None,
) -> Event:
    """Attach simulated Phase 8 fields to an Event row fetched from the DB.

    Uses ``setattr`` because the columns have not been added to the model yet.
    """
    event.selection_method = selection_method
    if recommendation_context is not None:
        event.recommendation_context = recommendation_context
    return event


@pytest.mark.asyncio
async def test_explanation_with_full_context(
    auth_client: AsyncClient,
    async_db,
) -> None:
    """GET returns all factors when recommendation context is fully populated."""
    result = await async_db.execute(select(User).where(User.id == auth_client.headers["X-User-Id"]))
    user = result.scalar_one_or_none()
    assert user is not None

    thread = Thread(
        title="Recommendation Thread",
        format="Series",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(
        user_id=user.id,
        start_die=8,
        manual_die=None,
        ladder_path="8",
        current_die=8,
        has_restore_point=False,
        snapshot_count=0,
        snoozed_thread_ids=[],
        pending_thread_id=None,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    raw_context = {
        "bandwidth": "band_light",
        "intent": "intent_momentum",
        "taste_bank_factors": [
            {"code": "taste_high_affinity"},
            {"code": "taste_confirmed_creator"},
        ],
        "primary_score": {"code": "score_recency_boost"},
        "affinity_notes": ["taste_series_momentum"],
        "selection_method": "random",
    }

    event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=8,
        result=3,
        selection_method="random",
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    _make_roll_event_row(event, selection_method="random", recommendation_context=raw_context)

    response = await auth_client.get(f"/api/roll/events/{event.id}/recommendation-explanation")
    assert response.status_code == 200

    body = response.json()
    assert body["event_id"] == event.id
    assert len(body["factors"]) >= 1

    labels = {f["label"] for f in body["factors"]}
    assert "Quick read" in labels
    assert "Recent series momentum" in labels
    assert "Strong affinity" in labels
    assert "Creator you confirmed you like" in labels
    assert "Recently updated" in labels
    assert "Pure random" in labels

    for factor in body["factors"]:
        assert "factor" in factor or "code" in factor
        assert not any(ch.isdigit() for ch in factor["label"])


@pytest.mark.asyncio
async def test_explanation_empty_context_returns_empty_factors(
    auth_client: AsyncClient,
    async_db,
) -> None:
    """GET returns empty factors when context is absent and selection_method alone is provided."""
    result = await async_db.execute(select(User).where(User.id == auth_client.headers["X-User-Id"]))
    user = result.scalar_one_or_none()
    assert user is not None

    session = SessionModel(
        user_id=user.id,
        start_die=8,
        manual_die=None,
        ladder_path="8",
        current_die=8,
        has_restore_point=False,
        snapshot_count=0,
        snoozed_thread_ids=[],
        pending_thread_id=None,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        session_id=session.id,
        die=8,
        result=5,
        selection_method="random",
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    _make_roll_event_row(event, selection_method="random")

    response = await auth_client.get(f"/api/roll/events/{event.id}/recommendation-explanation")
    assert response.status_code == 200

    body = response.json()
    assert body["event_id"] == event.id
    assert body["factors"] == []


@pytest.mark.asyncio
async def test_explanation_unknown_legacy_context_falls_back(
    auth_client: AsyncClient,
    async_db,
) -> None:
    """GET succeeds even when context contains only unrecognized future codes."""
    result = await async_db.execute(select(User).where(User.id == auth_client.headers["X-User-Id"]))
    user = result.scalar_one_or_none()
    assert user is not None

    session = SessionModel(
        user_id=user.id,
        start_die=8,
        manual_die=None,
        ladder_path="8",
        current_die=8,
        has_restore_point=False,
        snapshot_count=0,
        snoozed_thread_ids=[],
        pending_thread_id=None,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    future_context = {
        "bandwidth": "band_future_v2",
        "intent": "intent_unknown",
        "taste_bank_factors": [{"code": "taste_future_metric"}],
        "primary_score": {"code": "score_future_v3", "value": 0.91},
        "affinity_notes": ["taste_ghost_reason"],
        "selection_method": "unknown_method",
    }

    event = Event(
        type="roll",
        session_id=session.id,
        die=8,
        result=1,
        selection_method="unknown_method",
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    _make_roll_event_row(event, selection_method="unknown_method", recommendation_context=future_context)

    response = await auth_client.get(f"/api/roll/events/{event.id}/recommendation-explanation")
    assert response.status_code == 200

    body = response.json()
    assert body["event_id"] == event.id
    assert body["factors"] == []


@pytest.mark.asyncio
async def test_explanation_404_for_nonexistent_event(
    auth_client: AsyncClient,
) -> None:
    """GET returns 404 when the event does not exist."""
    response = await auth_client.get("/api/roll/events/999999/recommendation-explanation")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_explanation_404_for_non_roll_event(
    auth_client: AsyncClient,
    async_db,
) -> None:
    """GET returns 422 when the event type is not 'roll'."""
    result = await async_db.execute(select(User).where(User.id == auth_client.headers["X-User-Id"]))
    user = result.scalar_one_or_none()
    assert user is not None

    session = SessionModel(
        user_id=user.id,
        start_die=8,
        manual_die=None,
        ladder_path="8",
        current_die=8,
        has_restore_point=False,
        snapshot_count=0,
        snoozed_thread_ids=[],
        pending_thread_id=None,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=1,
        rating=4.5,
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    _make_roll_event_row(event, selection_method="rate")

    response = await auth_client.get(f"/api/roll/events/{event.id}/recommendation-explanation")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_explanation_random_selection_mentions_bypass(
    auth_client: AsyncClient,
    async_db,
) -> None:
    """The random-selection explanation explicitly notes that weighting was bypassed."""
    result = await async_db.execute(select(User).where(User.id == auth_client.headers["X-User-Id"]))
    user = result.scalar_one_or_none()
    assert user is not None

    session = SessionModel(
        user_id=user.id,
        start_die=8,
        manual_die=None,
        ladder_path="8",
        current_die=8,
        has_restore_point=False,
        snapshot_count=0,
        snoozed_thread_ids=[],
        pending_thread_id=None,
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(
        type="roll",
        session_id=session.id,
        die=8,
        result=2,
        selection_method="random",
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    _make_roll_event_row(event, selection_method="random")

    response = await auth_client.get(f"/api/roll/events/{event.id}/recommendation-explanation")
    assert response.status_code == 200

    body = response.json()
    labels = {f["label"] for f in body["factors"]}
    assert "No weighting applied" in labels or "Pure random" in labels


@pytest.mark.asyncio
async def test_explainable_factor_frozen_dataclass(
    auth_client: AsyncClient,
) -> None:
    """ExplainableFactor instances raised by the projection are frozen (immutable)."""
    projection = RecommendationExplanationProjection
    factor = projection.translate_bandwidth("band_light")
    assert factor is not None

    with pytest.raises(Exception):
        factor.code = "mutated"  # type: ignore[misc]

    factor2 = projection.translate_intent("intent_momentum")
    assert factor2 is not None
    with pytest.raises(Exception):
        factor2.label = "mutated"  # type: ignore[misc]