"""Contract tests for versioned roll recommendation-context snapshots.

Covers the issue #1691 acceptance contract: every new roll persists a bounded,
versioned snapshot of the decision-time recommendation context; queue movement
after the roll cannot rewrite it; override rolls are distinguishable from
random draws; historical events without a snapshot remain valid; and roll
selection behavior is unchanged.
"""

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.services.recommendation_context import (
    ALGORITHM_VERSION_LEGACY_UNWEIGHTED,
    RECOMMENDATION_CONTEXT_SCHEMA_VERSION,
    RecommendationContextV1,
    build_recommendation_context,
    daypart_for_hour,
    validate_recommendation_context,
)
from tests.conftest import get_or_create_user_async

EXPECTED_ROLL_RESPONSE_KEYS = {
    "thread_id",
    "title",
    "format",
    "issues_remaining",
    "queue_position",
    "die_size",
    "explanation",
    "result",
    "offset",
    "snoozed_count",
    "issue_id",
    "issue_number",
    "next_issue_id",
    "next_issue_number",
    "total_issues",
    "reading_progress",
}


def _extract_selection_context(payload: dict[str, object] | None) -> dict[str, object] | None:
    """Extract the selection context from a merged recommendation context payload.

    The merged payload has the structure:
    {
        "selection": {...selection context...},
        "effort": {...effort context...}
    }

    Args:
        payload: The merged recommendation context from Event.recommendation_context.

    Returns:
        The selection context dict, or None if not present.
    """
    if not payload or not isinstance(payload, dict):
        return None
    return payload.get("selection") if isinstance(payload.get("selection"), dict) else None


async def _latest_roll_event(async_db: AsyncSession) -> Event:
    """Fetch the newest roll event with fresh database state."""
    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .order_by(Event.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _latest_roll_selection_context(async_db: AsyncSession) -> RecommendationContextV1:
    """Fetch and validate the newest roll event's selection context snapshot."""
    event = await _latest_roll_event(async_db)
    assert event.recommendation_context is not None
    selection_context = _extract_selection_context(event.recommendation_context)
    assert selection_context is not None
    return validate_recommendation_context(selection_context)


@pytest.mark.asyncio
async def test_random_roll_persists_versioned_context(
    auth_client: AsyncClient,
    sample_data: dict,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal random roll persists a v1 snapshot of the decision-time context."""
    selected_thread = sample_data["threads"][0]
    selected_thread.last_rating = 3.5
    selected_thread.last_activity_at = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
    await async_db.commit()

    # Force the die draw to pick the first bounded candidate deterministically.
    # The selector draws via app.momentum.random (uniform path when all
    # momentum weights are equal, randint fallback otherwise).
    monkeypatch.setattr("app.momentum.random.randint", lambda _start, _end: 0)
    monkeypatch.setattr("app.momentum.random.uniform", lambda _a, _b: 0.0)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200
    body = response.json()

    # User-visible roll response shape is unchanged by instrumentation.
    assert set(body.keys()) == EXPECTED_ROLL_RESPONSE_KEYS

    context = await _latest_roll_selection_context(async_db)
    assert context.schema_version == RECOMMENDATION_CONTEXT_SCHEMA_VERSION == 1
    assert context.algorithm_version == ALGORITHM_VERSION_LEGACY_UNWEIGHTED
    assert context.selection_method == "random"
    assert context.die_size == body["die_size"] == 8
    assert context.candidate_thread_ids == [1, 2, 4, 5]
    assert context.pool_size == len(context.candidate_thread_ids) == 4
    assert context.selected_thread_id == body["thread_id"] == selected_thread.id
    assert context.selected_candidate_index == 0
    assert context.selected_result == body["result"] == 1
    assert context.selected_queue_position == selected_thread.queue_position == 1
    assert context.selected_last_rating == 3.5
    assert context.selected_last_activity_at == "2026-08-01T15:00:00+00:00"

    # Session timezone arrives with #1690; until then the fields stay null.
    assert context.session_timezone is None
    assert context.local_hour is None
    assert context.daypart is None

    # The snapshot must round-trip as JSON exactly as stored.
    event = await _latest_roll_event(async_db)
    assert json.loads(json.dumps(event.recommendation_context)) == event.recommendation_context


@pytest.mark.asyncio
async def test_context_candidates_match_bounded_pool_for_large_library(
    auth_client: AsyncClient,
    sample_data: dict,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate IDs are the die-bounded pool in queue order, not the library."""
    user = await get_or_create_user_async(async_db)
    extra_threads = [
        Thread(
            title=f"Extra Series {offset}",
            format="Comic",
            issues_remaining=2,
            queue_position=10 + offset,
            status="active",
            user_id=user.id,
        )
        for offset in range(12)
    ]
    for thread in extra_threads:
        async_db.add(thread)
    await async_db.commit()
    extra_ids = [thread.id for thread in extra_threads]

    # Draw the last bounded candidate (die size 8) deterministically: a pick
    # equal to the total weight always resolves to the final candidate.
    monkeypatch.setattr("app.momentum.random.randint", lambda _start, _end: 0)
    monkeypatch.setattr("app.momentum.random.uniform", lambda _a, _b: _b)

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200
    body = response.json()

    context = await _latest_roll_selection_context(async_db)
    expected_candidates = [1, 2, 4, 5, *extra_ids[:4]]
    assert context.candidate_thread_ids == expected_candidates
    assert len(context.candidate_thread_ids) == context.die_size == body["die_size"] == 8
    assert context.pool_size == 8
    assert context.selected_candidate_index == 7
    assert context.selected_thread_id == expected_candidates[7] == body["thread_id"]
    assert context.selected_result == 8

    # Payload stays bounded: no titles or heavy thread metadata are serialized.
    event = await _latest_roll_event(async_db)
    serialized = json.dumps(event.recommendation_context)
    assert "Extra Series" not in serialized
    payload = event.recommendation_context
    assert isinstance(payload, dict)
    # The merged payload has "selection" and "effort" keys; neither should
    # contain thread titles or heavy metadata.
    selection_payload = payload.get("selection", {})
    effort_payload = payload.get("effort", {})
    for key in ("title", "notes", "description"):
        assert key not in selection_payload
        assert key not in effort_payload


@pytest.mark.asyncio
async def test_queue_movement_after_roll_cannot_change_snapshot(
    auth_client: AsyncClient,
    sample_data: dict,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Later queue movement never rewrites the stored position or candidate order."""
    monkeypatch.setattr("app.momentum.random.randint", lambda _start, _end: 0)
    monkeypatch.setattr("app.momentum.random.uniform", lambda _a, _b: 0.0)

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200

    context_before = await _latest_roll_selection_context(async_db)
    assert context_before.selected_queue_position == 1
    assert context_before.candidate_thread_ids == [1, 2, 4, 5]

    move_response = await auth_client.put(
        "/api/v1/queue/threads/1/position/", json={"new_position": 4}
    )
    assert move_response.status_code == 200

    positions_result = await async_db.execute(
        select(Thread.queue_position).where(Thread.id == 1)
    )
    assert positions_result.scalar_one() == 4

    context_after = await _latest_roll_selection_context(async_db)
    assert context_after == context_before
    assert context_after.selected_queue_position == 1
    assert context_after.candidate_thread_ids == [1, 2, 4, 5]


@pytest.mark.asyncio
async def test_override_context_distinguishes_manual_selection_from_random(
    auth_client: AsyncClient,
    sample_data: dict,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override rolls record method "override" with no draw index, unlike random."""
    monkeypatch.setattr("app.momentum.random.randint", lambda _start, _end: 0)
    monkeypatch.setattr("app.momentum.random.uniform", lambda _a, _b: 0.0)

    random_response = await auth_client.post("/api/roll/")
    assert random_response.status_code == 200

    override_response = await auth_client.post("/api/roll/override", json={"thread_id": 5})
    assert override_response.status_code == 200
    assert override_response.json()["result"] == 0

    result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .order_by(Event.id.desc())
        .limit(2)
        .execution_options(populate_existing=True)
    )
    override_event, random_event = result.scalars().all()

    override_selection_context = _extract_selection_context(override_event.recommendation_context)
    assert override_selection_context is not None
    override_context = validate_recommendation_context(override_selection_context)
    assert override_context.selection_method == "override"
    assert override_context.selected_candidate_index is None
    assert override_context.selected_result == 0 == override_event.result
    assert override_context.selected_thread_id == 5
    assert override_context.selected_queue_position == 5
    assert override_context.die_size == 8
    assert override_context.candidate_thread_ids == [1, 2, 4, 5]
    assert override_context.schema_version == RECOMMENDATION_CONTEXT_SCHEMA_VERSION

    random_selection_context = _extract_selection_context(random_event.recommendation_context)
    assert random_selection_context is not None
    random_context = validate_recommendation_context(random_selection_context)
    assert random_context.selection_method == "random"
    assert isinstance(random_context.selected_candidate_index, int)
    assert random_context.selected_result == 1
    assert random_context != override_context


@pytest.mark.asyncio
async def test_override_outside_bounded_pool_still_records_pool(
    auth_client: AsyncClient,
    sample_data: dict,
    async_db: AsyncSession,
) -> None:
    """Overriding a thread beyond the die still snapshots the bounded pool."""
    user = await get_or_create_user_async(async_db)
    for offset in range(6):
        async_db.add(
            Thread(
                title=f"Filler Series {offset}",
                format="Comic",
                issues_remaining=1,
                queue_position=10 + offset,
                status="active",
                user_id=user.id,
            )
        )
    far_thread = Thread(
        title="Far Down Queue",
        format="Comic",
        issues_remaining=1,
        queue_position=30,
        status="active",
        user_id=user.id,
    )
    async_db.add(far_thread)
    await async_db.commit()

    response = await auth_client.post(
        "/api/roll/override", json={"thread_id": far_thread.id}
    )
    assert response.status_code == 200

    context = await _latest_roll_selection_context(async_db)
    # Pool (11 threads) exceeds the die, so candidates stay bounded at 8.
    assert len(context.candidate_thread_ids) == context.die_size == 8
    assert far_thread.id not in context.candidate_thread_ids
    assert context.pool_size == 8
    assert context.selected_thread_id == far_thread.id
    assert context.selection_method == "override"
    assert context.selected_queue_position == 30


@pytest.mark.asyncio
async def test_historical_events_without_context_remain_valid(
    auth_client: AsyncClient,
    sample_data: dict,
) -> None:
    """Pre-existing events with no snapshot keep working and stay unexposed."""
    seeded_events = sample_data["events"]
    assert all(event.recommendation_context is None for event in seeded_events)

    session_id = sample_data["sessions"][0].id
    response = await auth_client.get(f"/api/sessions/{session_id}/details")
    assert response.status_code == 200
    details = response.json()
    assert len(details["events"]) >= 2
    assert all("recommendation_context" not in event for event in details["events"])


def test_builder_derives_local_fields_from_persisted_timezone() -> None:
    """Local hour and daypart derive only from a provided persisted timezone."""
    captured = datetime(2026, 1, 15, 18, 30, tzinfo=UTC)
    context = build_recommendation_context(
        selection_method="random",
        die_size=6,
        candidate_thread_ids=[7, 8],
        selected_thread_id=8,
        selected_queue_position=2,
        selected_candidate_index=1,
        selected_result=2,
        selected_last_rating=None,
        selected_last_activity_at=None,
        session_timezone="America/Chicago",
        captured_at=captured,
    )
    assert context["session_timezone"] == "America/Chicago"
    assert context["local_hour"] == 12
    assert context["daypart"] == "afternoon"
    assert validate_recommendation_context(context).local_hour == 12


def test_builder_fails_safe_on_invalid_timezone() -> None:
    """An unusable timezone leaves local fields null without raising."""
    context = build_recommendation_context(
        selection_method="random",
        die_size=6,
        candidate_thread_ids=[7],
        selected_thread_id=7,
        selected_queue_position=1,
        selected_candidate_index=0,
        selected_result=1,
        selected_last_rating=None,
        selected_last_activity_at=None,
        session_timezone="Not/AReal-Zone",
        captured_at=datetime(2026, 1, 15, 18, 30, tzinfo=UTC),
    )
    assert context["session_timezone"] == "Not/AReal-Zone"
    assert context["local_hour"] is None
    assert context["daypart"] is None
    assert validate_recommendation_context(context).schema_version == 1


def test_validator_rejects_unknown_schema_version() -> None:
    """Payloads claiming a different schema version fail the v1 contract."""
    payload = build_recommendation_context(
        selection_method="random",
        die_size=6,
        candidate_thread_ids=[7],
        selected_thread_id=7,
        selected_queue_position=1,
        selected_candidate_index=0,
        selected_result=1,
        selected_last_rating=None,
        selected_last_activity_at=None,
    )
    payload["schema_version"] = 99
    with pytest.raises(ValueError):
        validate_recommendation_context(payload)


def test_daypart_buckets_match_documented_boundaries() -> None:
    """Daypart buckets follow the documented hour boundaries."""
    assert daypart_for_hour(0) == "night"
    assert daypart_for_hour(4) == "night"
    assert daypart_for_hour(5) == "morning"
    assert daypart_for_hour(11) == "morning"
    assert daypart_for_hour(12) == "afternoon"
    assert daypart_for_hour(17) == "afternoon"
    assert daypart_for_hour(18) == "evening"
    assert daypart_for_hour(22) == "evening"
    assert daypart_for_hour(23) == "night"