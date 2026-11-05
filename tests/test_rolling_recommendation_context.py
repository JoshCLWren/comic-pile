"""Contract tests for rolling recommendation context snapshot.

Tests verify that:
- Every roll event persists a versioned recommendation-context snapshot.
- The bounded candidate IDs match the actual pool from which the roll was selected.
- Override/manual rolls record selection_method='override' and a distinguishable context.
- The snapshot payload shape matches the RollingRecommendationContext schema.
- Payload size is bounded by the candidate pool, not the full thread library.
"""

from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.config import get_recommendation_settings
from app.models import Event, Thread, User
from app.schemas.recommendation_context import RollingRecommendationContext
from app.services.reading_effort import (
    RECOMMENDATION_CONTEXT_ALGORITHM_VERSION_KEY,
    RECOMMENDATION_CONTEXT_CONTROL_MODE_KEY,
)
from tests.roll_flow import roll_pending_thread


@pytest.mark.asyncio
async def test_roll_persists_rolling_recommendation_context(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A roll event stores a versioned rolling_recommendation_context snapshot."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Context Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    await roll_pending_thread(async_db)

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread.id)
        .order_by(Event.id.desc())
        .limit(1)
    )
    event = result.scalar_one()
    ctx = event.rolling_recommendation_context
    assert ctx is not None
    assert ctx["schema_version"] == 1
    assert ctx["algorithm_version"] == "v1-contextual"
    assert ctx["control_mode"] == "contextual"
    assert cast(int, ctx["die_size"]) > 0
    assert cast(int, ctx["selected_queue_position"]) >= 1
    assert isinstance(ctx["bounded_candidate_ids"], list)
    assert len(cast(list[int], ctx["bounded_candidate_ids"])) > 0
    assert cast(int, ctx["selected_index"]) >= 0
    assert ctx["selection_method"] in ("random", "momentum")
    local_hour = cast(int | None, ctx["local_hour"])
    assert local_hour is None or 0 <= local_hour <= 23


@pytest.mark.asyncio
async def test_roll_bounded_candidate_ids_match_pool(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """The stored bounded_candidate_ids exactly match the bounded pool used for selection."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"Pool Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i + 1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(3)
    ]
    async_db.add_all(threads)
    await async_db.commit()

    data = (await roll_pending_thread(async_db)).model_dump()

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == data["thread_id"])
        .order_by(Event.id.desc())
        .limit(1)
    )
    event = result.scalar_one()
    ctx = event.rolling_recommendation_context
    assert ctx is not None

    bounded_candidate_ids = cast(list[int], ctx["bounded_candidate_ids"])
    assert data["thread_id"] in bounded_candidate_ids
    assert cast(int, ctx["selected_index"]) < len(bounded_candidate_ids)


@pytest.mark.asyncio
async def test_override_roll_records_override_selection_method(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """An override roll stores selection_method='override' in the context snapshot."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Override Context Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # Roll once to create a pending thread
    await roll_pending_thread(async_db)

    override_response = await auth_client.post(
        "/api/roll/override", json={"thread_id": thread.id}
    )
    assert override_response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selection_method == "override")
        .order_by(Event.id.desc())
        .limit(1)
    )
    event = result.scalar_one()
    ctx = event.rolling_recommendation_context
    assert ctx is not None
    assert ctx["selection_method"] == "override"
    assert ctx["bounded_candidate_ids"] == [thread.id]
    assert ctx["selected_index"] == 0


@pytest.mark.asyncio
async def test_rolling_recommendation_context_validates_against_schema(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """The stored context dict passes pydantic validation of RollingRecommendationContext."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Schema Validation Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    await roll_pending_thread(async_db)

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread.id)
        .order_by(Event.id.desc())
        .limit(1)
    )
    event = result.scalar_one()
    ctx = event.rolling_recommendation_context
    assert ctx is not None

    parsed = RollingRecommendationContext.model_validate(ctx)
    assert parsed.schema_version == 1
    assert parsed.die_size > 0
    assert parsed.selected_queue_position >= 1


@pytest.mark.asyncio
async def test_rolling_recommendation_context_bounded_payload_size(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """The context payload contains only thread IDs, not full thread objects."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Bounded Payload Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    await roll_pending_thread(async_db)

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread.id)
        .order_by(Event.id.desc())
        .limit(1)
    )
    event = result.scalar_one()
    ctx = event.rolling_recommendation_context
    assert ctx is not None

    bounded_candidate_ids = cast(list[int], ctx["bounded_candidate_ids"])
    for candidate_id in bounded_candidate_ids:
        assert isinstance(candidate_id, int)

    assert "title" not in ctx
    assert "format" not in ctx
    assert "issues_remaining" not in ctx


@pytest.mark.asyncio
async def test_legacy_control_mode_roll_records_forced_legacy_snapshot(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under RECOMMENDATION_CONTROL_MODE=legacy every roll records forced legacy."""
    now = datetime.now(UTC)
    threads = [
        Thread(
            title=f"Legacy Mode Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i + 1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        for i in range(3)
    ]
    async_db.add_all(threads)
    await async_db.commit()

    monkeypatch.setenv("RECOMMENDATION_CONTROL_MODE", "legacy")
    get_recommendation_settings.cache_clear()
    try:
        await roll_pending_thread(async_db, bandwidth="deep", intent="momentum")
    finally:
        monkeypatch.delenv("RECOMMENDATION_CONTROL_MODE", raising=False)
        get_recommendation_settings.cache_clear()

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.in_([thread.id for thread in threads]))
        .order_by(Event.id.desc())
        .limit(1)
    )
    event = result.scalar_one()
    assert event.selection_method == "legacy"
    assert event.recommendation_reason_codes == ["forced_legacy"]

    ctx = event.rolling_recommendation_context
    assert ctx is not None
    assert ctx["algorithm_version"] == "legacy"
    assert ctx["control_mode"] == "legacy"
    assert ctx["selection_method"] == "legacy"

    payload = event.recommendation_context
    assert payload is not None
    assert payload[RECOMMENDATION_CONTEXT_ALGORITHM_VERSION_KEY] == "legacy"
    assert payload[RECOMMENDATION_CONTEXT_CONTROL_MODE_KEY] == "legacy"
    assert payload["random_bypass"] is True
    assert payload["balanced_neutrality"] is True
