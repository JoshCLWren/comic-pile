"""API tests for recommendation-context recording on roll events."""

from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from comic_pile.recommendation_context import (
    RECOMMENDATION_CONTEXT_VERSION,
    read_recommendation_context,
)


async def _latest_roll_event(db: AsyncSession) -> Event:
    """Fetch the most recent roll event."""
    result = await db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    event = result.scalar_one()
    assert event is not None
    return event


def _context_dict(event: Event) -> dict[str, object]:
    context = event.recommendation_context
    assert isinstance(context, dict)
    return context


def _candidate_weights_by_thread(context: dict[str, object]) -> dict[int, float]:
    candidates = context["candidates"]
    assert isinstance(candidates, list)
    weights: dict[int, float] = {}
    for entry in candidates:
        assert isinstance(entry, dict)
        thread_id = entry["thread_id"]
        weight = entry["weight"]
        assert isinstance(thread_id, int)
        assert isinstance(weight, (int, float))
        weights[thread_id] = float(weight)
    return weights


async def test_light_roll_records_weighted_context(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    response = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert response.status_code == status.HTTP_200_OK

    event = await _latest_roll_event(async_db)
    context = _context_dict(event)

    # sample_data pool: Superman(0 unread), Batman(5), Flash(0), Aquaman(0).
    weights = _candidate_weights_by_thread(context)
    assert len(weights) == 4
    assert weights[1] == 3.0  # low effort boosted under light bandwidth
    assert weights[2] == 1.5  # medium effort mildly demoted under light

    selected_thread_id = context["selected_thread_id"]
    assert isinstance(selected_thread_id, int)
    assert weights[selected_thread_id] == context["selected_weight"]
    assert event.selected_thread_id == selected_thread_id
    assert event.selection_method == "weighted"

    view = read_recommendation_context(context)
    assert view.readable is True
    assert view.version == RECOMMENDATION_CONTEXT_VERSION
    assert view.weighting_applied is True
    assert view.bandwidth == "light"


async def test_deep_roll_records_deep_context(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    response = await auth_client.post("/api/roll/", json={"bandwidth": "deep"})
    assert response.status_code == status.HTTP_200_OK

    event = await _latest_roll_event(async_db)
    context = _context_dict(event)
    weights = _candidate_weights_by_thread(context)

    # Deep mode boosts the higher-effort candidate without excluding others.
    assert weights[2] == 1.5
    assert all(weight == 0.5 for thread_id, weight in weights.items() if thread_id != 2)
    assert min(weights.values()) > 0.0
    assert event.selection_method == "weighted"
    assert context["mode"] == "contextual_weighted"


async def test_balanced_default_records_neutral_bypass(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    response = await auth_client.post("/api/roll/")
    assert response.status_code == status.HTTP_200_OK
    payload = response.json()

    # Legacy roll response semantics remain intact.
    for field_name in (
        "thread_id",
        "title",
        "die_size",
        "result",
        "offset",
        "snoozed_count",
    ):
        assert field_name in payload

    event = await _latest_roll_event(async_db)
    context = _context_dict(event)

    assert context["version"] == RECOMMENDATION_CONTEXT_VERSION
    assert context["mode"] == "bypassed"
    assert context["bandwidth"] == "balanced"
    assert context["bandwidth_source"] == "default"
    assert context["bandwidth_confidence"] is None
    assert set(_candidate_weights_by_thread(context).values()) == {1.0}
    assert event.selection_method == "random"

    candidates = context["candidates"]
    assert isinstance(candidates, list)
    for entry in candidates:
        assert isinstance(entry, dict)
        reasons = entry["reasons"]
        assert isinstance(reasons, list)
        assert any(code.startswith("bypass:") for code in reasons)


async def test_random_intent_explicitly_bypasses_weighting(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    response = await auth_client.post(
        "/api/roll/",
        json={"bandwidth": "deep", "intent": "random"},
    )
    assert response.status_code == status.HTTP_200_OK

    event = await _latest_roll_event(async_db)
    context = _context_dict(event)

    assert context["intent"] == "random"
    assert context["mode"] == "bypassed"
    assert set(_candidate_weights_by_thread(context).values()) == {1.0}
    assert event.selection_method == "random"

    candidates = context["candidates"]
    assert isinstance(candidates, list)
    for entry in candidates:
        assert isinstance(entry, dict)
        reasons = entry["reasons"]
        assert isinstance(reasons, list)
        assert "bypass:random_intent" in reasons


async def test_requested_bandwidth_records_source_and_confidence(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    response = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert response.status_code == status.HTTP_200_OK

    event = await _latest_roll_event(async_db)
    context = _context_dict(event)
    assert context["bandwidth_source"] == "request"
    assert context["bandwidth_confidence"] == 1.0


async def test_unknown_bandwidth_rejected(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    response = await auth_client.post("/api/roll/", json={"bandwidth": "spicy"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_persisted_weights_match_the_weights_passed_to_selection(
    auth_client: AsyncClient,
    sample_data: dict,
    async_db: AsyncSession,
    monkeypatch,
) -> None:
    """Capture the exact weights handed to the draw and compare to storage."""
    import random as random_module

    from comic_pile import recommendation_context as rc

    captured: dict[str, object] = {}

    original_choices = random_module.Random.choices

    def spy_choices(self, population, weights=None, *, cum_weights=None, k=None):
        captured["weights"] = list(weights) if weights is not None else None
        return original_choices(self, population, weights=weights, k=1 if k else k)

    monkeypatch.setattr(random_module.Random, "choices", spy_choices)

    response = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert response.status_code == status.HTTP_200_OK
    assert captured["weights"] is not None

    event = await _latest_roll_event(async_db)
    context = _context_dict(event)
    stored_weights = [weight for _t, weight in read_recommendation_context(context).candidate_weights]
    assert stored_weights == [
        round(float(weight), 6) for weight in captured["weights"]  # type-agnostic capture
    ]
    del rc


async def test_older_unversioned_context_stays_readable_in_storage(
    auth_client: AsyncClient, sample_data: dict, async_db: AsyncSession
) -> None:
    """A pre-versioning snapshot persisted on an old event must stay readable."""
    legacy_payload = {
        "selected_thread_id": 1,
        "selected_weight": 2.5,
        "candidates": [
            {"thread_id": 1, "weight": 2.5},
            {"thread_id": 2, "weight": 0.75},
        ],
    }
    legacy_event = Event(
        type="roll",
        session_id=1,
        selected_thread_id=1,
        die=6,
        result=1,
        selection_method="random",
        recommendation_context=legacy_payload,
    )
    async_db.add(legacy_event)
    await async_db.flush()

    result = await db.execute(select(Event).where(Event.id == legacy_event.id))
    stored = result.scalar_one()
    view = read_recommendation_context(stored.recommendation_context)
    assert view.readable is True
    assert view.version == 0
    assert view.selected_thread_id == 1
    assert view.candidate_weights == ((1, 2.5), (2, 0.75))
