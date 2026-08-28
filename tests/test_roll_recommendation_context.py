"""Tests for reading-effort estimates in roll recommendation-context snapshots.

Covers issue #1704: new roll events record selected-candidate effort
estimate/source, bounded candidate snapshots include effort where available,
missing estimates stay neutral/null without blocking Roll, context versioning
is explicit and compatible with legacy payloads, and selection probabilities
are unchanged.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.services.recommendation_context import (
    RECOMMENDATION_CONTEXT_VERSION,
    ContextCandidate,
    build_recommendation_context,
    candidate_efforts_from_context,
    selected_effort_from_context,
)
from app.services.reading_effort import (
    EFFORT_SOURCE_UNKNOWN,
    EffortEstimate,
    NEUTRAL_EFFORT_ESTIMATE,
    resolve_candidate_efforts,
    selected_effort_estimate,
)


async def _latest_roll_event(async_db: AsyncSession) -> Event:
    result = await async_db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    event = result.scalar_one()
    assert event is not None
    return event


@pytest.mark.asyncio
async def test_random_roll_context_has_effort_and_candidates(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Random rolls persist a recommendation context with effort estimates and candidate pool."""
    _ = sample_data
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    context = event.recommendation_context
    assert isinstance(context, dict)

    # Versioning is explicit via context_version key.
    assert context["context_version"] == RECOMMENDATION_CONTEXT_VERSION

    # The v2 context has a candidates list and a selected block.
    assert "candidates" in context
    assert "selected" in context
    assert isinstance(context["candidates"], list)
    assert len(context["candidates"]) > 0

    # Selected block has the expected structure.
    selected = context["selected"]
    assert selected["thread_id"] == event.selected_thread_id
    assert selected["result"] == event.result
    assert "effort" in selected
    effort = selected["effort"]
    assert "minutes" in effort
    assert "band" in effort
    assert "source" in effort
    assert "confidence" in effort

    # Candidate-level effort fields exist for later weighting.
    for candidate in context["candidates"]:
        assert set(candidate) >= {
            "thread_id",
            "effort_minutes",
            "effort_band",
            "effort_source",
            "effort_confidence",
        }


@pytest.mark.asyncio
async def test_roll_candidates_bounded_by_manual_die(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Candidate snapshots stay bounded to the effective die size."""
    _ = sample_data

    user_result = await async_db.execute(select(Thread.user_id).where(Thread.id == 1))
    user_id = user_result.scalar_one()

    for position in range(6, 13):
        async_db.add(
            Thread(
                title=f"Bulk Thread {position}",
                format="Comic",
                issues_remaining=1,
                queue_position=position,
                status="active",
                user_id=user_id,
            )
        )
    await async_db.commit()

    die_response = await auth_client.post("/api/roll/set-die?die=4")
    assert die_response.status_code == 200

    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200
    assert response.json()["die_size"] == 4

    event = await _latest_roll_event(async_db)
    context = event.recommendation_context
    assert context["pool_size"] == 4
    assert len(context["candidates"]) == 4
    assert event.selected_thread_id in [c["thread_id"] for c in context["candidates"]]


@pytest.mark.asyncio
async def test_override_roll_records_override_method_and_bounded_pool(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Override rolls record their distinct method plus the overridden candidate."""
    _ = sample_data
    response = await auth_client.post("/api/roll/override", json={"thread_id": 4})
    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    context = event.recommendation_context
    assert context is not None
    assert context["selection_method"] == "override"
    assert context["pool_size"] == 1
    assert [candidate["thread_id"] for candidate in context["candidates"]] == [4]
    assert context["selected"]["thread_id"] == 4
    assert context["selected"]["result"] == 0
    assert context["selected"]["effort"]["source"] == EFFORT_SOURCE_UNKNOWN


@pytest.mark.asyncio
async def test_missing_estimates_stay_neutral_and_historical_events_remain_valid(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """Rolls succeed without estimates and legacy NULL-context rows persist."""
    _ = sample_data
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    normalized = selected_effort_from_context(event.recommendation_context)
    assert normalized["minutes"] is None
    assert normalized["band"] is None
    assert normalized["confidence"] is None
    assert normalized["source"] == EFFORT_SOURCE_UNKNOWN

    # A historical-style event without context round-trips unchanged.
    legacy_event = Event(
        type="roll",
        die=8,
        result=3,
        selected_thread_id=2,
        selection_method="random",
        session_id=event.session_id,
    )
    async_db.add(legacy_event)
    await async_db.commit()
    await async_db.refresh(legacy_event)
    assert legacy_event.id is not None
    assert legacy_event.recommendation_context is None
    assert selected_effort_from_context(None)["minutes"] is None


def test_v1_payload_without_effort_fields_is_tolerated() -> None:
    """Legacy v1 contexts normalize to neutral effort instead of raising."""
    v1_context = {
        "context_version": 1,
        "algorithm_version": "legacy-unweighted-dice-v1",
        "selection_method": "random",
        "die_size": 8,
        "pool_size": 2,
        "session_timezone": None,
        "local_hour": None,
        "daypart": None,
        "selected": {
            "thread_id": 7,
            "candidate_index": 0,
            "result": 1,
            "queue_position": 1,
            "last_rating": 4.5,
            "last_activity_at": "2026-01-01T00:00:00+00:00",
        },
        "candidates": [
            {"thread_id": 7, "queue_position": 1},
            {"thread_id": 9, "queue_position": 2},
        ],
    }

    selected_effort = selected_effort_from_context(v1_context)
    assert selected_effort == {
        "minutes": None,
        "band": None,
        "source": EFFORT_SOURCE_UNKNOWN,
        "confidence": None,
    }

    candidate_efforts = candidate_efforts_from_context(v1_context)
    assert [entry["thread_id"] for entry in candidate_efforts] == [7, 9]
    for entry in candidate_efforts:
        assert entry["effort_minutes"] is None
        assert entry["effort_band"] is None
        assert entry["effort_source"] is None
        assert entry["effort_confidence"] is None


def test_malformed_context_payloads_degrade_to_neutral() -> None:
    """Malformed or absent contexts never raise for analysis readers."""
    assert selected_effort_from_context(None)["minutes"] is None
    assert selected_effort_from_context({})["source"] == EFFORT_SOURCE_UNKNOWN
    assert selected_effort_from_context({"selected": {}})["minutes"] is None
    assert (
        selected_effort_from_context({"selected": {"effort": "bogus"}})["source"]
        == EFFORT_SOURCE_UNKNOWN
    )
    assert (
        selected_effort_from_context({"selected": {"effort": {"minutes": "x"}}})["minutes"]
        is None
    )
    assert candidate_efforts_from_context(None) == []
    assert candidate_efforts_from_context({"candidates": "bogus"}) == []
    assert candidate_efforts_from_context({"candidates": ["bad", {"thread_id": 3}]}) == [
        {
            "thread_id": 3,
            "effort_minutes": None,
            "effort_band": None,
            "effort_source": None,
            "effort_confidence": None,
        }
    ]


def test_builder_records_provided_estimates_and_neutral_fallbacks() -> None:
    """Builder passes known estimates through and leaves missing ones neutral."""
    now = datetime.now(UTC)
    candidates = [
        ContextCandidate(thread_id=1, queue_position=1, last_rating=4.0, last_activity_at=now),
        ContextCandidate(thread_id=2, queue_position=2, last_rating=None, last_activity_at=None),
    ]
    efforts = {
        1: EffortEstimate(
            minutes=14.0, band="balanced", source="observed_thread", confidence=0.8,
            sample_count=2,
        )
    }

    context = build_recommendation_context(
        selection_method="random",
        die_size=8,
        candidates=candidates,
        selected_index=0,
        result=1,
        efforts_by_thread=efforts,
    )

    assert context["context_version"] == RECOMMENDATION_CONTEXT_VERSION
    assert context["selected"]["effort"] == {
        "minutes": 14.0,
        "band": "balanced",
        "source": "observed_thread",
        "confidence": 0.8,
    }
    assert context["candidates"][0]["effort_minutes"] == 14.0
    assert context["candidates"][0]["effort_band"] == "balanced"
    assert context["candidates"][1]["effort_minutes"] is None
    assert context["candidates"][1]["effort_source"] is None

    assert selected_effort_from_context(context)["minutes"] == 14.0
    normalized_candidates = candidate_efforts_from_context(context)
    assert normalized_candidates[0]["effort_minutes"] == 14.0
    assert normalized_candidates[1]["effort_minutes"] is None


def test_builder_rejects_empty_or_misaligned_pools() -> None:
    """Structural misuse fails fast instead of storing corrupt snapshots."""
    candidates = [
        ContextCandidate(thread_id=1, queue_position=1, last_rating=None, last_activity_at=None)
    ]
    with pytest.raises(ValueError):
        build_recommendation_context(
            selection_method="random",
            die_size=8,
            candidates=[],
            selected_index=0,
            result=1,
            efforts_by_thread={},
        )
    with pytest.raises(ValueError):
        build_recommendation_context(
            selection_method="random",
            die_size=8,
            candidates=candidates,
            selected_index=5,
            result=1,
            efforts_by_thread={},
        )


def test_effort_estimate_validation_enforces_vocabulary() -> None:
    """Estimate sources, bands, and confidence bounds are validated."""
    assert NEUTRAL_EFFORT_ESTIMATE.source.value == EFFORT_SOURCE_UNKNOWN

    with pytest.raises(ValueError):
        EffortEstimate(minutes=None, band=None, source="made_up", confidence=None, sample_count=0)
    with pytest.raises(ValueError):
        EffortEstimate(minutes=10.0, band="spicy", source="era_prior", confidence=0.5, sample_count=0)
    with pytest.raises(ValueError):
        EffortEstimate(minutes=10.0, band="light", source="era_prior", confidence=1.5, sample_count=0)


@pytest.mark.asyncio
async def test_resolve_candidate_efforts_returns_empty_mapping(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """With no estimator registered yet, resolution is empty and never blocks Roll."""
    _ = sample_data
    threads_result = await async_db.execute(select(Thread).where(Thread.id.in_([1, 2])))
    threads = list(threads_result.scalars())

    efforts = await resolve_candidate_efforts(async_db, threads)
    assert efforts == {}
    assert selected_effort_estimate(efforts, threads[0].id) == NEUTRAL_EFFORT_ESTIMATE
    assert selected_effort_estimate({}, None) == NEUTRAL_EFFORT_ESTIMATE
