"""Tests for ephemeral session reading-intent state (issue #1728)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.constants import INTENT_SOURCE_VALUES, INTENT_VALUES, Intent, IntentSource
from app.models import Session as SessionModel
from app.models import Thread
from app.schemas.session import SessionListItem, build_session_intent_state
from comic_pile.session import get_or_create


def test_intent_constants_include_all_first_class_values() -> None:
    """AC: The canonical intent vocabulary lists every supported value incl. random."""
    assert INTENT_VALUES == ("balanced", "momentum", "familiar", "explore", "random")
    assert set(Intent) == {
        Intent.BALANCED,
        Intent.MOMENTUM,
        Intent.FAMILIAR,
        Intent.EXPLORE,
        Intent.RANDOM,
    }
    assert Intent.RANDOM.value == "random"
    assert INTENT_SOURCE_VALUES == ("inferred", "manual", "snooze", "quiz")
    assert set(IntentSource) == {
        IntentSource.INFERRED,
        IntentSource.MANUAL,
        IntentSource.SNOOZE,
        IntentSource.QUIZ,
    }


@pytest.mark.asyncio
async def test_intent_stored_independently_from_bandwidth(
    async_db: AsyncSession, default_user
) -> None:
    """AC1: A session stores active intent without disturbing bandwidth columns."""
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
        active_intent="momentum",
        predicted_intent="momentum",
        intent_source="manual",
        intent_confidence=0.9,
        intent_version="manual-test",
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    persisted = await async_db.get(SessionModel, session.id)
    assert persisted is not None
    assert persisted.active_intent == "momentum"
    assert persisted.predicted_intent == "momentum"
    assert persisted.intent_source == "manual"
    assert persisted.intent_confidence == 0.9
    # Bandwidth columns stay untouched/independent.
    assert persisted.active_bandwidth is None
    assert persisted.predicted_bandwidth is None
    assert persisted.bandwidth_source is None


@pytest.mark.asyncio
async def test_random_is_a_first_class_intent_value(
    async_db: AsyncSession, default_user
) -> None:
    """AC2: random persists as a stored intent value and reads back cleanly."""
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
        active_intent="random",
        predicted_intent="random",
        intent_source="manual",
        intent_confidence=1.0,
    )
    async_db.add(session)
    await async_db.flush()

    built = build_session_intent_state(
        predicted_intent=session.predicted_intent,
        active_intent=session.active_intent,
        confidence=session.intent_confidence,
        source=session.intent_source,
        mode_version=session.intent_version,
    )
    assert built.active_intent == "random"
    assert built.predicted_intent == "random"


@pytest.mark.asyncio
async def test_existing_sessions_default_safely_to_null_semantics(
    async_db: AsyncSession, default_user
) -> None:
    """AC3: Legacy sessions serialize to an all-null balanced-default shape."""
    legacy = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(legacy)
    await async_db.commit()
    await async_db.refresh(legacy)

    fetched = (
        (await async_db.execute(select(SessionModel).where(SessionModel.id == legacy.id)))
        .scalars()
        .one()
    )
    assert fetched.active_intent is None
    assert fetched.predicted_intent is None
    assert fetched.intent_confidence is None
    assert fetched.intent_source is None
    assert fetched.intent_version is None

    built = build_session_intent_state(
        predicted_intent=fetched.predicted_intent,
        active_intent=fetched.active_intent,
        confidence=fetched.intent_confidence,
        source=fetched.intent_source,
        mode_version=fetched.intent_version,
    )
    assert built.active_intent is None
    assert built.predicted_intent is None
    assert built.source is None


def test_build_session_intent_state_normalizes_invalid_values() -> None:
    """Legacy garbage in stored intent columns normalizes to the safe null shape."""
    built = build_session_intent_state(
        predicted_intent="mystery",
        active_intent="rampage",
        confidence=4.0,
        source="oracle",
        mode_version="v9",
    )
    assert built.active_intent is None
    assert built.predicted_intent is None
    assert built.confidence is None
    assert built.source is None
    # mode_version is free-form and passes through unchanged.
    assert built.mode_version == "v9"

    valid = build_session_intent_state(
        predicted_intent="explore",
        active_intent="familiar",
        confidence=0.5,
        source="inferred",
        mode_version=None,
    )
    assert valid.active_intent == "familiar"
    assert valid.predicted_intent == "explore"
    assert valid.confidence == 0.5
    assert valid.source == "inferred"


def test_intent_state_never_lands_on_thread_or_narrow_list_view() -> None:
    """AC4: Intent stays ephemeral session state, not Thread or list affinity."""
    assert not hasattr(Thread, "active_intent")
    assert not hasattr(Thread, "predicted_intent")
    assert not hasattr(Thread, "intent_confidence")
    assert "active_intent" not in SessionListItem.model_fields
    assert "predicted_intent" not in SessionListItem.model_fields


@pytest.mark.asyncio
async def test_database_check_constraints_reject_invalid_intent_rows(
    async_db: AsyncSession, default_user
) -> None:
    """AC: Persisted CHECK constraints reject invalid intent enum and confidence."""
    user_id = default_user.id

    bad_intent = SessionModel(start_die=6, user_id=user_id, active_intent="daydream")
    async_db.add(bad_intent)
    with pytest.raises(IntegrityError):
        await async_db.flush()
    await async_db.rollback()

    bad_source = SessionModel(
        start_die=6,
        user_id=user_id,
        predicted_intent="balanced",
        intent_source="oracle",
    )
    async_db.add(bad_source)
    with pytest.raises(IntegrityError):
        await async_db.flush()
    await async_db.rollback()

    bad_confidence = SessionModel(
        start_die=6,
        user_id=user_id,
        active_intent="random",
        intent_source="manual",
        intent_confidence=1.5,
    )
    async_db.add(bad_confidence)
    with pytest.raises(IntegrityError):
        await async_db.flush()
    await async_db.rollback()

    valid_boundary = SessionModel(
        start_die=6,
        user_id=user_id,
        predicted_intent="explore",
        active_intent="random",
        intent_source="snooze",
        intent_confidence=0.0,
    )
    async_db.add(valid_boundary)
    await async_db.flush()
    assert valid_boundary.intent_confidence == 0.0
    assert valid_boundary.active_intent == "random"


@pytest.mark.asyncio
async def test_current_session_endpoint_exposes_intent_state(
    client: AsyncClient, async_db: AsyncSession, default_user
) -> None:
    """Active-session reads expose stored active/predicted intent independently."""
    from app.models import User as UserModel

    result = await async_db.execute(select(UserModel).where(UserModel.id == default_user.id))
    user = result.scalar_one()

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(UTC),
        active_intent="explore",
        predicted_intent="explore",
        intent_source="inferred",
        intent_confidence=0.7,
        intent_version="intent-v1",
    )
    async_db.add(session)
    await async_db.commit()

    token = create_access_token(data={"sub": user.username, "jti": "test"})
    response = await client.get(
        "/api/sessions/current/", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["intent"] is not None
    assert data["intent"]["active_intent"] == "explore"
    assert data["intent"]["predicted_intent"] == "explore"
    assert data["intent"]["confidence"] == 0.7
    assert data["intent"]["source"] == "inferred"
    assert data["intent"]["mode_version"] == "intent-v1"


@pytest.mark.asyncio
async def test_get_session_by_id_exposes_null_intent_for_legacy_row(
    auth_client: AsyncClient, async_db: AsyncSession, default_user
) -> None:
    """Legacy sessions serialize with null intent fields, staying API-valid."""
    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] is not None
    assert data["intent"]["active_intent"] is None
    assert data["intent"]["predicted_intent"] is None
    assert data["intent"]["source"] is None


@pytest.mark.asyncio
async def test_new_session_defaults_intent_to_null_not_thread_affinity(
    async_db: AsyncSession, default_user
) -> None:
    """AC4: Fresh sessions do not inherit a prior session's intent values."""
    stale = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=8),
        active_intent="momentum",
        predicted_intent="momentum",
        intent_source="manual",
    )
    async_db.add(stale)
    await async_db.commit()

    created = await get_or_create(async_db, user_id=default_user.id)
    assert created.id != stale.id
    # The stale row keeps its own state; nothing leaks across sessions.
    assert stale.active_intent == "momentum"
    assert stale.intent_source == "manual"
    # The fresh session starts with no inherited reading intent.
    assert created.active_intent is None
    assert created.predicted_intent is None
    assert created.intent_source is None


@pytest.mark.asyncio
async def test_end_session_clears_ephemeral_intent(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """AC4: Ending a session terminates its ephemeral reading-intent lifetime."""
    from comic_pile.session import end_session

    session = sample_data["sessions"][0]
    session.active_intent = "explore"
    session.predicted_intent = "explore"
    session.intent_source = "manual"
    session.intent_confidence = 0.9
    session.intent_version = "manual-test"
    await async_db.commit()
    await async_db.refresh(session)

    await end_session(session.id, async_db)

    await async_db.refresh(session)
    assert session.ended_at is not None
    assert session.active_intent is None
    assert session.predicted_intent is None
    assert session.intent_source is None
    assert session.intent_confidence is None
    assert session.intent_version is None
