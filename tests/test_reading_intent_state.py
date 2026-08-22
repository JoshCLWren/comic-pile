"""Regression coverage for ephemeral reading-intent session state (#1728)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, Thread, User
from comic_pile.reading_intent import (
    DEFAULT_INTENT,
    DEFAULT_INTENT_SOURCE,
    INTENT_SOURCES,
    INTENT_STATE_VERSION,
    INTENT_VALUES,
    PLACEHOLDER_INTENT_CONFIDENCE,
    initial_intent_state,
    is_valid_intent,
    normalize_intent,
)
from comic_pile.session import get_or_create


def test_intent_vocabulary_is_exactly_the_product_model() -> None:
    """The five product-model intents are first-class, including random."""
    assert INTENT_VALUES == ("balanced", "momentum", "familiar", "explore", "random")


def test_random_is_a_first_class_intent_value() -> None:
    """Random is accepted like every other intent value."""
    assert "random" in INTENT_VALUES
    assert is_valid_intent("random")


def test_intent_sources_cover_every_planned_provenance() -> None:
    """Intent provenance matches the bandwidth-state source contract."""
    assert INTENT_SOURCES == ("inferred", "manual", "snooze", "quiz")


@pytest.mark.parametrize("value", [None, "", "BANDWIDTH", "light", "deep", "unknown"])
def test_unset_and_unknown_values_default_to_balanced(value: str | None) -> None:
    """Legacy or invalid stored values resolve to the balanced default."""
    assert normalize_intent(value) == DEFAULT_INTENT


def test_initial_intent_state_is_placeholder_inferred_balanced() -> None:
    """New sessions record a low-confidence inferred balanced intent."""
    assert initial_intent_state() == {
        "reading_intent": DEFAULT_INTENT,
        "reading_intent_source": DEFAULT_INTENT_SOURCE,
        "reading_intent_confidence": PLACEHOLDER_INTENT_CONFIDENCE,
        "reading_intent_version": INTENT_STATE_VERSION,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", INTENT_VALUES)
async def test_session_round_trips_every_first_class_intent(
    intent: str, async_db: AsyncSession, default_user: User
) -> None:
    """Sessions store active intent plus provenance independently of any other axis."""
    session = Session(
        start_die=6,
        user_id=default_user.id,
        reading_intent=intent,
        reading_intent_source="manual",
        reading_intent_confidence=1.0,
        reading_intent_version=INTENT_STATE_VERSION,
    )
    async_db.add(session)
    await async_db.commit()

    stored = await async_db.get(Session, session.id)

    assert stored is not None
    assert stored.reading_intent == intent
    assert stored.reading_intent_source == "manual"
    assert stored.reading_intent_confidence == 1.0
    assert stored.reading_intent_version == INTENT_STATE_VERSION


@pytest.mark.asyncio
async def test_new_sessions_initialize_inferred_balanced_intent(
    async_db: AsyncSession, default_user: User
) -> None:
    """Session creation records the placeholder inferred intent state."""
    created = await get_or_create(async_db, default_user.id)

    assert created.reading_intent == DEFAULT_INTENT
    assert created.reading_intent_source == DEFAULT_INTENT_SOURCE
    assert created.reading_intent_confidence == PLACEHOLDER_INTENT_CONFIDENCE
    assert created.reading_intent_version == INTENT_STATE_VERSION


@pytest.mark.asyncio
async def test_legacy_sessions_without_intent_default_safely(
    async_db: AsyncSession, default_user: User
) -> None:
    """Pre-existing rows keep NULL intent and behave as balanced without a backfill."""
    legacy = Session(start_die=6, user_id=default_user.id)
    async_db.add(legacy)
    await async_db.commit()

    stored = await async_db.get(Session, legacy.id)

    assert stored is not None
    assert stored.reading_intent is None
    assert stored.reading_intent_source is None
    assert stored.reading_intent_confidence is None
    assert stored.reading_intent_version is None
    assert normalize_intent(stored.reading_intent) == DEFAULT_INTENT


@pytest.mark.asyncio
async def test_changing_intent_never_touches_thread_affinity(
    async_db: AsyncSession, default_user: User
) -> None:
    """Intent stays ephemeral session state; threads keep their queue identity."""
    thread = Thread(
        title="Saga",
        format="comic",
        issues_remaining=5,
        queue_position=3,
        status="active",
        last_rating=4.5,
        user_id=default_user.id,
    )
    async_db.add(thread)
    await async_db.flush()
    session = Session(
        start_die=6,
        user_id=default_user.id,
        **initial_intent_state(),
    )
    async_db.add(session)
    await async_db.commit()
    thread_id = thread.id
    session_id = session.id

    session.reading_intent = "random"
    session.reading_intent_source = "manual"
    session.reading_intent_confidence = 1.0
    await async_db.commit()

    reloaded_thread = await async_db.get(Thread, thread_id)
    reloaded_session = await async_db.get(Session, session_id)

    assert reloaded_thread is not None
    assert reloaded_thread.queue_position == 3
    assert reloaded_thread.last_rating == 4.5
    assert reloaded_thread.status == "active"
    assert reloaded_session is not None
    assert reloaded_session.reading_intent == "random"


@pytest.mark.parametrize("column", ["reading_intent", "reading_intent_source"])
def test_intent_columns_exist_only_on_sessions(column: str) -> None:
    """The intent axis lives on sessions, never on durable Thread affinity."""
    assert hasattr(Session, column)
    assert not hasattr(Thread, column)


@pytest.mark.asyncio
async def test_current_session_endpoint_still_serves_with_intent_columns(
    auth_client: AsyncClient,
) -> None:
    """Adding intent state does not disturb the existing session API contract."""
    response = await auth_client.get("/api/sessions/current/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_die"] > 0
