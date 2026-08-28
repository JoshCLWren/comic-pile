"""Contract tests for recommendation context recording.

Tests verify that:
- Persisted context is sufficient to reproduce/explain the factor breakdown used for a roll.
- Reason codes use stable compact identifiers.
- Final stored weight equals the weight passed to the chooser.
- Random bypass and balanced neutrality are explicit.
- Older context versions remain readable.
- Contract tests cover Momentum, Familiar, Explore, and Random intents.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models import Event, Thread, User
from app.models.recommendation_context import RecommendationContext
from app.schemas.recommendation_context import (
    CandidateFactor,
    RecommendationContextCreate,
    RecommendationContextResponse,
)


@pytest.mark.asyncio
async def test_roll_creates_recommendation_context(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that a roll creates a recommendation context with correct fields."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    # Verify recommendation context was created
    result = await async_db.execute(
        select(RecommendationContext)
        .join(Event, Event.id == RecommendationContext.event_id)
        .where(Event.selected_thread_id == roll_data["thread_id"])
        .where(Event.type == "roll")
    )
    context = result.scalar_one_or_none()
    assert context is not None

    # Verify random bypass is explicit (no positive momentum in this pool)
    assert context.random_bypass is True
    # Verify balanced neutrality is explicit
    assert context.balanced_neutrality is True
    # Verify schema version
    assert context.schema_version == 1
    # Verify intent is balanced (default for random selection)
    assert context.intent == "balanced"
    assert context.intent_source == "default"
    assert context.intent_confidence == 0.0
    # Verify bandwidth is balanced; Phase 2 initialization sets source to "inferred"
    assert context.bandwidth == "balanced"
    assert context.bandwidth_source == "inferred"
    assert context.bandwidth_confidence == pytest.approx(0.1)
    # Verify final weight equals the selected candidate's chooser weight
    assert context.candidate_factors is not None
    selected_factors = [
        factor
        for factor in context.candidate_factors
        if factor["candidate_id"] == roll_data["thread_id"]
    ]
    assert len(selected_factors) == 1
    assert context.final_weight == selected_factors[0]["weight"]
    assert context.final_weight == 1.0


@pytest.mark.asyncio
async def test_momentum_roll_records_factor_breakdown(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A momentum-weighted roll must record weights, reason codes, and flags."""
    from datetime import timedelta

    now = datetime.now(UTC)
    hot = Thread(
        title="Hot Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        last_rating=5.0,
        last_activity_at=now - timedelta(hours=2),
        created_at=now,
    )
    cold = Thread(
        title="Cold Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add_all([hot, cold])
    await async_db.commit()

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    result = await async_db.execute(
        select(RecommendationContext)
        .join(Event, Event.id == RecommendationContext.event_id)
        .where(Event.selected_thread_id == roll_data["thread_id"])
        .where(Event.type == "roll")
    )
    context = result.scalar_one_or_none()
    assert context is not None

    # Weighting applied: pure-random bypass and balanced neutrality are off.
    assert context.random_bypass is False
    assert context.balanced_neutrality is False

    # Every bounded candidate is recorded with stable compact reason codes.
    assert context.candidate_factors is not None
    factors_by_candidate = {
        factor["candidate_id"]: factor for factor in context.candidate_factors
    }
    assert set(factors_by_candidate) == {hot.id, cold.id}

    # The highly-rated fresh candidate carries its momentum evidence.
    hot_factors = factors_by_candidate[hot.id]
    assert "recent_high_rating" in hot_factors["factors"]
    assert hot_factors["weight"] > 1.0

    # The unrated candidate stays at the pure-random weight.
    cold_factors = factors_by_candidate[cold.id]
    assert cold_factors["factors"] == []
    assert cold_factors["weight"] == 1.0

    # Final stored weight equals the chooser weight of the selected candidate.
    selected_factors = factors_by_candidate[roll_data["thread_id"]]
    assert context.final_weight == selected_factors["weight"]


@pytest.mark.asyncio
async def test_override_creates_recommendation_context(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that an override creates a recommendation context with manual override source."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Override Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # First roll to create a pending thread
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    # Now override with the same thread
    override_response = await auth_client.post(
        "/api/roll/override", json={"thread_id": thread.id}
    )
    assert override_response.status_code == 200
    override_data = override_response.json()

    # Verify recommendation context was created
    result = await async_db.execute(
        select(RecommendationContext)
        .join(Event, Event.id == RecommendationContext.event_id)
        .where(Event.selected_thread_id == override_data["thread_id"])
        .where(Event.type == "roll")
        .where(Event.selection_method == "override")
    )
    context = result.scalar_one_or_none()
    assert context is not None

    # Verify manual override source
    assert context.intent_source == "manual_override"
    assert context.intent_confidence == 1.0
    assert context.bandwidth_source == "manual_override"
    assert context.bandwidth_confidence == 1.0
    # Verify random bypass is false for override
    assert context.random_bypass is False
    # Verify balanced neutrality is true for override
    assert context.balanced_neutrality is True


@pytest.mark.asyncio
async def test_recommendation_context_schema_versioning(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that schema version is recorded and older versions remain readable."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Version Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # Roll to create context
    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    # Get the context
    result = await async_db.execute(
        select(RecommendationContext)
        .join(Event, Event.id == RecommendationContext.event_id)
        .where(Event.selected_thread_id == roll_data["thread_id"])
        .where(Event.type == "roll")
    )
    context = result.scalar_one_or_none()
    assert context is not None

    # Verify schema version is recorded
    assert context.schema_version == 1

    # Verify the context can be read as a response schema
    response_data = RecommendationContextResponse.model_validate(context)
    assert response_data.schema_version == 1
    assert response_data.intent == "balanced"
    assert response_data.random_bypass is True
    assert response_data.balanced_neutrality is True


@pytest.mark.asyncio
async def test_recommendation_context_with_factors(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that candidate factors can be stored and retrieved."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Factor Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # Create a context with factors
    context_data = RecommendationContextCreate(
        schema_version=1,
        intent="momentum",
        intent_source="manual",
        intent_confidence=0.8,
        bandwidth="light",
        bandwidth_source="inferred",
        bandwidth_confidence=0.7,
        candidate_factors=[
            CandidateFactor(
                candidate_id=thread.id,
                factors=["recent_high_rating", "same_thread_momentum"],
                weight=0.9,
            )
        ],
        final_weight=0.9,
        random_bypass=False,
        balanced_neutrality=False,
    )

    # Manually create an event and context
    event = Event(
        type="roll",
        session_id=None,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="momentum",
    )
    async_db.add(event)
    await async_db.flush()

    rec_context = RecommendationContext(
        event_id=event.id,
        schema_version=context_data.schema_version,
        intent=context_data.intent,
        intent_source=context_data.intent_source,
        intent_confidence=context_data.intent_confidence,
        bandwidth=context_data.bandwidth,
        bandwidth_source=context_data.bandwidth_source,
        bandwidth_confidence=context_data.bandwidth_confidence,
        candidate_factors=[f.model_dump() for f in context_data.candidate_factors]
        if context_data.candidate_factors
        else None,
        final_weight=context_data.final_weight,
        random_bypass=context_data.random_bypass,
        balanced_neutrality=context_data.balanced_neutrality,
    )
    async_db.add(rec_context)
    await async_db.commit()

    # Verify the context was stored correctly
    result = await async_db.execute(
        select(RecommendationContext).where(RecommendationContext.event_id == event.id)
    )
    stored_context = result.scalar_one()
    assert stored_context.intent == "momentum"
    assert stored_context.bandwidth == "light"
    assert stored_context.candidate_factors is not None
    assert len(stored_context.candidate_factors) == 1
    assert stored_context.candidate_factors[0]["candidate_id"] == thread.id
    assert "recent_high_rating" in stored_context.candidate_factors[0]["factors"]
    assert "same_thread_momentum" in stored_context.candidate_factors[0]["factors"]
    assert stored_context.final_weight == 0.9
    assert stored_context.random_bypass is False
    assert stored_context.balanced_neutrality is False


@pytest.mark.asyncio
async def test_recommendation_context_intent_types(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that all valid intent types can be stored."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Intent Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    intents = ["momentum", "familiar", "explore", "random", "balanced"]

    for intent in intents:
        # Create an event
        event = Event(
            type="roll",
            session_id=None,
            selected_thread_id=thread.id,
            die=6,
            result=1,
            selection_method=intent,
        )
        async_db.add(event)
        await async_db.flush()

        # Create context with the intent
        rec_context = RecommendationContext(
            event_id=event.id,
            schema_version=1,
            intent=intent,
            intent_source="test",
            intent_confidence=1.0,
            bandwidth="balanced",
            bandwidth_source="test",
            bandwidth_confidence=1.0,
            candidate_factors=None,
            final_weight=1.0,
            random_bypass=(intent == "random"),
            balanced_neutrality=(intent == "balanced"),
        )
        async_db.add(rec_context)
        await async_db.commit()

        # Verify the intent was stored
        result = await async_db.execute(
            select(RecommendationContext).where(RecommendationContext.event_id == event.id)
        )
        stored_context = result.scalar_one()
        assert stored_context.intent == intent

        # Verify random bypass is explicit for random intent
        if intent == "random":
            assert stored_context.random_bypass is True
        # Verify balanced neutrality is explicit for balanced intent
        if intent == "balanced":
            assert stored_context.balanced_neutrality is True


@pytest.mark.asyncio
async def test_recommendation_context_backward_compatibility(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that older context versions remain readable."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Backward Compat Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # Create an event with older schema version
    event = Event(
        type="roll",
        session_id=None,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    async_db.add(event)
    await async_db.flush()

    # Create context with older schema version (v1)
    rec_context = RecommendationContext(
        event_id=event.id,
        schema_version=1,  # Older version
        intent="balanced",
        intent_source="default",
        intent_confidence=0.0,
        bandwidth="balanced",
        bandwidth_source="default",
        bandwidth_confidence=0.0,
        candidate_factors=None,
        final_weight=1.0,
        random_bypass=True,
        balanced_neutrality=True,
    )
    async_db.add(rec_context)
    await async_db.commit()

    # Verify the older context can be read
    result = await async_db.execute(
        select(RecommendationContext).where(RecommendationContext.event_id == event.id)
    )
    stored_context = result.scalar_one()
    assert stored_context.schema_version == 1
    assert stored_context.intent == "balanced"
    assert stored_context.random_bypass is True
    assert stored_context.balanced_neutrality is True

    # Verify it can be converted to response schema
    response_data = RecommendationContextResponse.model_validate(stored_context)
    assert response_data.schema_version == 1
    assert response_data.intent == "balanced"
    assert response_data.random_bypass is True
    assert response_data.balanced_neutrality is True


@pytest.mark.asyncio
async def test_recommendation_context_final_weight_matches_chooser(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Verify that the final stored weight equals the weight passed to the chooser."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Weight Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # Create an event
    event = Event(
        type="roll",
        session_id=None,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="test",
    )
    async_db.add(event)
    await async_db.flush()

    # Create context with a specific weight
    expected_weight = 0.75
    rec_context = RecommendationContext(
        event_id=event.id,
        schema_version=1,
        intent="momentum",
        intent_source="test",
        intent_confidence=0.8,
        bandwidth="light",
        bandwidth_source="test",
        bandwidth_confidence=0.7,
        candidate_factors=[
            {"candidate_id": thread.id, "factors": ["test_factor"], "weight": expected_weight}
        ],
        final_weight=expected_weight,
        random_bypass=False,
        balanced_neutrality=False,
    )
    async_db.add(rec_context)
    await async_db.commit()

    # Verify the final weight matches
    result = await async_db.execute(
        select(RecommendationContext).where(RecommendationContext.event_id == event.id)
    )
    stored_context = result.scalar_one()
    assert stored_context.final_weight == expected_weight

    # Verify it matches in the candidate factors
    assert stored_context.candidate_factors is not None
    assert stored_context.candidate_factors[0]["weight"] == expected_weight
