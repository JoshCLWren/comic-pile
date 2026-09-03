"""Tests for ephemeral session bandwidth state (issue #1706)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.constants import Bandwidth, BandwidthSource
from app.models import Session as SessionModel
from app.models import Snapshot, Thread
from app.schemas.session import SessionListItem
from comic_pile.bandwidth import (
    BANDWIDTH_CHOICES,
    BANDWIDTH_SOURCE_CHOICES,
    CURRENT_BANDWIDTH_MODE_VERSION,
    apply_bandwidth_state,
    capture_ephemeral_bandwidth,
    clear_ephemeral_bandwidth,
    restore_ephemeral_bandwidth,
    validate_bandwidth_state,
)
from comic_pile.session import end_session, get_or_create, resolve_current_session


@pytest.mark.asyncio
async def test_predicted_and_active_bandwidth_stored_independently(
    async_db: AsyncSession, default_user
) -> None:
    """AC1: Active sessions store predicted and active bandwidth independently."""
    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Predicted only: active slot stays empty.
    await apply_bandwidth_state(
        async_db,
        session,
        predicted_bandwidth=Bandwidth.BALANCED,
        active_bandwidth=None,
        bandwidth_source=BandwidthSource.INFERRED,
        bandwidth_confidence=0.7,
    )
    assert session.predicted_bandwidth == "balanced"
    assert session.active_bandwidth is None

    # Active set later without disturbing predicted.
    await apply_bandwidth_state(
        async_db,
        session,
        predicted_bandwidth="balanced",
        active_bandwidth=Bandwidth.LIGHT,
        bandwidth_source=BandwidthSource.MANUAL,
        bandwidth_confidence=None,
        bandwidth_version=None,
    )
    assert session.predicted_bandwidth == "balanced"
    assert session.active_bandwidth == "light"
    assert session.bandwidth_source == "manual"

    persisted = await async_db.get(SessionModel, session.id)
    assert persisted is not None
    assert persisted.predicted_bandwidth == "balanced"
    assert persisted.active_bandwidth == "light"


@pytest.mark.asyncio
async def test_existing_sessions_without_bandwidth_remain_valid(
    async_db: AsyncSession, default_user
) -> None:
    """AC2: Legacy sessions created before bandwidth columns remain valid."""
    legacy = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(legacy)
    await async_db.commit()
    await async_db.refresh(legacy)

    fetched = (
        (await async_db.execute(select(SessionModel).where(SessionModel.id == legacy.id)))
        .scalars()
        .one()
    )
    assert fetched.predicted_bandwidth is None
    assert fetched.active_bandwidth is None
    assert fetched.bandwidth_confidence is None
    assert fetched.bandwidth_source is None
    assert fetched.bandwidth_version is None
    assert fetched.bandwidth_updated_at is None


@pytest.mark.asyncio
async def test_new_sessions_start_without_inherited_bandwidth(
    async_db: AsyncSession, default_user
) -> None:
    """AC2: Fresh sessions never inherit a stale session's bandwidth values."""
    stale = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC) - timedelta(hours=8),
        predicted_bandwidth="deep",
        active_bandwidth="deep",
        bandwidth_source="quiz",
        bandwidth_confidence=0.9,
    )
    async_db.add(stale)
    await async_db.commit()

    created = await get_or_create(async_db, user_id=default_user.id)
    assert created.id != stale.id
    # The stale row keeps its own legacy state; nothing leaks across sessions.
    assert stale.predicted_bandwidth == "deep"
    assert stale.bandwidth_source == "quiz"
    # The fresh session receives its own one-time inferred initialization.
    assert created.predicted_bandwidth == "balanced"
    assert created.active_bandwidth == "balanced"
    assert created.bandwidth_source == "inferred"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"predicted_bandwidth": "cozy"},
        {"predicted_bandwidth": None, "active_bandwidth": "extreme"},
        {"predicted_bandwidth": "light", "bandwidth_source": "oracle"},
        {"predicted_bandwidth": "light", "active_bandwidth": None},
    ],
)
def test_invalid_bandwidth_values_rejected(kwargs: dict) -> None:
    """AC3: Invalid enum values and missing provenance are rejected safely."""
    with pytest.raises(ValueError):
        validate_bandwidth_state(**kwargs)


@pytest.mark.parametrize("confidence", [-0.1, 1.5, 2.0])
def test_out_of_range_confidence_rejected(confidence: float) -> None:
    """AC3: Confidence outside the inclusive 0..1 range is rejected."""
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_bandwidth_state(bandwidth_confidence=confidence)


def test_null_bandwidth_state_is_valid() -> None:
    """All-null bandwidth state validates: existing sessions remain legal."""
    validate_bandwidth_state()


@pytest.mark.asyncio
async def test_apply_rejects_invalid_state_without_database_write(
    async_db: AsyncSession, default_user
) -> None:
    """AC3: apply_bandwidth_state raises before mutating or flushing the row."""
    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()

    with pytest.raises(ValueError, match="predicted_bandwidth"):
        await apply_bandwidth_state(
            async_db,
            session,
            predicted_bandwidth="sleepy",
            active_bandwidth=None,
            bandwidth_source=BandwidthSource.INFERRED,
        )

    await async_db.refresh(session)
    assert session.predicted_bandwidth is None
    assert session.bandwidth_updated_at is None


@pytest.mark.asyncio
async def test_database_check_constraints_reject_invalid_rows(
    async_db: AsyncSession, default_user
) -> None:
    """AC3: Persisted CHECK constraints reject invalid enum and confidence values."""
    # Capture identifiers before any rollback: Session.rollback() expires
    # loaded instances, and touching expired attributes afterwards would
    # trigger synchronous lazy loading (MissingGreenlet) in async context.
    user_id = default_user.id

    bad_bandwidth = SessionModel(
        start_die=6, user_id=user_id, active_bandwidth="overwhelmed"
    )
    async_db.add(bad_bandwidth)
    with pytest.raises(IntegrityError):
        await async_db.flush()
    await async_db.rollback()

    bad_confidence = SessionModel(
        start_die=6,
        user_id=user_id,
        predicted_bandwidth="light",
        bandwidth_source="manual",
        bandwidth_confidence=1.25,
    )
    async_db.add(bad_confidence)
    with pytest.raises(IntegrityError):
        await async_db.flush()
    await async_db.rollback()

    valid_boundary = SessionModel(
        start_die=6,
        user_id=user_id,
        predicted_bandwidth="deep",
        bandwidth_source="snooze",
        bandwidth_confidence=0.0,
    )
    async_db.add(valid_boundary)
    await async_db.flush()
    assert valid_boundary.bandwidth_confidence == 0.0


@pytest.mark.asyncio
async def test_end_session_clears_ephemeral_bandwidth(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """AC4: Ending a session terminates its ephemeral bandwidth lifetime."""
    session = sample_data["sessions"][0]
    await apply_bandwidth_state(
        async_db,
        session,
        predicted_bandwidth=Bandwidth.DEEP,
        active_bandwidth=Bandwidth.DEEP,
        bandwidth_source=BandwidthSource.INFERRED,
        bandwidth_confidence=0.8,
    )
    await async_db.commit()

    await end_session(session.id, async_db)

    await async_db.refresh(session)
    assert session.ended_at is not None
    assert session.predicted_bandwidth is None
    assert session.active_bandwidth is None
    assert session.bandwidth_confidence is None
    assert session.bandwidth_source is None
    assert session.bandwidth_version is None
    assert session.bandwidth_updated_at is None


@pytest.mark.asyncio
async def test_active_session_keeps_its_own_bandwidth_on_reuse(
    async_db: AsyncSession, sample_data: dict
) -> None:
    """AC4: Reusing the current session preserves its in-lifetime state."""
    # The fixture seeds multiple unended sessions; resolution (not seed order)
    # decides which row is authoritative, so target the resolved session.
    session = await resolve_current_session(async_db, user_id=sample_data["user"].id)
    assert session is not None
    await apply_bandwidth_state(
        async_db,
        session,
        predicted_bandwidth="light",
        active_bandwidth=None,
        bandwidth_source="inferred",
        bandwidth_confidence=0.55,
    )
    await async_db.commit()

    resolved = await get_or_create(async_db, user_id=session.user_id)
    assert resolved.id == session.id
    assert resolved.predicted_bandwidth == "light"
    assert resolved.bandwidth_confidence == 0.55


@pytest.mark.asyncio
async def test_get_or_create_initializes_inferred_bandwidth_exactly_once(
    async_db: AsyncSession, default_user
) -> None:
    """AC: New sessions receive inferred neutral state once, never recomputed."""
    created = await get_or_create(async_db, user_id=default_user.id)
    assert created.predicted_bandwidth == "balanced"
    assert created.active_bandwidth == "balanced"
    assert created.bandwidth_source == "inferred"
    assert created.bandwidth_confidence == 0.1
    assert created.bandwidth_version == CURRENT_BANDWIDTH_MODE_VERSION
    assert created.bandwidth_updated_at is not None

    initialized_updated_at = created.bandwidth_updated_at

    resolved = await get_or_create(async_db, user_id=default_user.id)
    assert resolved.id == created.id
    # Bootstrap refreshes must not rewrite the initialized prediction.
    assert resolved.bandwidth_updated_at == initialized_updated_at
    assert resolved.bandwidth_confidence == 0.1

    persisted = await async_db.get(SessionModel, created.id)
    assert persisted is not None
    assert persisted.predicted_bandwidth == "balanced"
    assert persisted.bandwidth_source == "inferred"


@pytest.mark.asyncio
async def test_get_or_create_preserves_manual_override(
    async_db: AsyncSession, default_user
) -> None:
    """AC: Explicit overrides survive subsequent bootstrap requests untouched."""
    override = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
        predicted_bandwidth="deep",
        active_bandwidth="light",
        bandwidth_source="manual",
        bandwidth_confidence=0.9,
    )
    async_db.add(override)
    await async_db.commit()

    overridden_at = override.bandwidth_updated_at

    resolved = await get_or_create(async_db, user_id=default_user.id)
    assert resolved.id == override.id
    assert resolved.predicted_bandwidth == "deep"
    assert resolved.active_bandwidth == "light"
    assert resolved.bandwidth_source == "manual"
    assert resolved.bandwidth_confidence == 0.9
    assert resolved.bandwidth_updated_at == overridden_at


@pytest.mark.asyncio
async def test_get_or_create_initializes_legacy_unended_session(
    async_db: AsyncSession, default_user
) -> None:
    """AC: Uninitialized legacy sessions get mode state on first bootstrap."""
    legacy = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(legacy)
    await async_db.commit()
    assert legacy.bandwidth_source is None

    resolved = await get_or_create(async_db, user_id=default_user.id)
    assert resolved.id == legacy.id
    assert resolved.predicted_bandwidth == "balanced"
    assert resolved.active_bandwidth == "balanced"
    assert resolved.bandwidth_source == "inferred"
    assert resolved.bandwidth_version == CURRENT_BANDWIDTH_MODE_VERSION


@pytest.mark.asyncio
async def test_bandwidth_initialization_fails_closed_to_balanced(
    async_db: AsyncSession, default_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: Inference failure leaves Roll usable with balanced behavior."""
    import comic_pile.bandwidth as bandwidth_module

    def _explode(
        observations: object,
        *,
        session_hour: int | None = None,
    ) -> object:
        raise RuntimeError("simulated inference outage")

    monkeypatch.setattr(bandwidth_module, "infer_bandwidth", _explode)

    created = await get_or_create(async_db, user_id=default_user.id)
    assert created.predicted_bandwidth == "balanced"
    assert created.active_bandwidth == "balanced"
    assert created.bandwidth_source == "inferred"
    assert created.bandwidth_confidence == 0.1


@pytest.mark.asyncio
async def test_clear_ephemeral_bandwidth_resets_all_fields(default_user) -> None:
    """clear_ephemeral_bandwidth wipes every bandwidth field in memory."""
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        predicted_bandwidth="deep",
        active_bandwidth="light",
        bandwidth_source="quiz",
        bandwidth_confidence=0.4,
        bandwidth_version="3",
        bandwidth_updated_at=datetime.now(UTC),
    )
    clear_ephemeral_bandwidth(session)
    assert capture_ephemeral_bandwidth(session) == {
        "predicted_bandwidth": None,
        "active_bandwidth": None,
        "bandwidth_confidence": None,
        "bandwidth_source": None,
        "bandwidth_version": None,
        "bandwidth_updated_at": None,
    }


def test_capture_and_restore_round_trip() -> None:
    """AC4: Undo-style capture/restore returns bandwidth to pre-correction state."""

    class _StubSession:
        predicted_bandwidth: str | None
        active_bandwidth: str | None
        bandwidth_confidence: float | None
        bandwidth_source: str | None
        bandwidth_version: str | None
        bandwidth_updated_at: datetime | None

    source = _StubSession()
    source.predicted_bandwidth = "balanced"
    source.active_bandwidth = "light"
    source.bandwidth_confidence = 0.9
    source.bandwidth_source = "inferred"
    source.bandwidth_version = CURRENT_BANDWIDTH_MODE_VERSION
    updated_at = datetime.now(UTC).replace(microsecond=0)
    source.bandwidth_updated_at = updated_at

    captured = capture_ephemeral_bandwidth(source)
    assert captured["bandwidth_updated_at"] == updated_at.isoformat()

    target = _StubSession()
    target.predicted_bandwidth = "deep"
    target.active_bandwidth = "deep"
    target.bandwidth_confidence = 0.2
    target.bandwidth_source = "snooze"
    target.bandwidth_version = "99"
    target.bandwidth_updated_at = datetime.now(UTC)

    restore_ephemeral_bandwidth(target, captured)
    assert target.predicted_bandwidth == "balanced"
    assert target.active_bandwidth == "light"
    assert target.bandwidth_confidence == 0.9
    assert target.bandwidth_source == "inferred"
    assert target.bandwidth_version == CURRENT_BANDWIDTH_MODE_VERSION
    assert target.bandwidth_updated_at == updated_at


def test_restore_ignores_snapshots_without_bandwidth_keys() -> None:
    """Older snapshots predating bandwidth tracking leave live values untouched."""

    class _StubSession:
        predicted_bandwidth: str | None
        active_bandwidth: str | None

    session = _StubSession()
    session.predicted_bandwidth = "deep"
    session.active_bandwidth = "light"

    restore_ephemeral_bandwidth(session, {"start_die": 6, "manual_die": None})
    assert session.predicted_bandwidth == "deep"
    assert session.active_bandwidth == "light"


def test_restore_rejects_impossible_values() -> None:
    """Restore refuses values that could never satisfy persistence checks."""

    class _StubSession:
        predicted_bandwidth = None
        active_bandwidth = None

    with pytest.raises(ValueError, match="active_bandwidth"):
        restore_ephemeral_bandwidth(_StubSession(), {"active_bandwidth": "zzz"})


def test_restore_rejects_invalid_source_and_confidence() -> None:
    """AC3: Restore rejects invalid source and out-of-range confidence safely."""

    class _StubSession:
        bandwidth_source: str | None = None
        bandwidth_confidence: float | None = None

    with pytest.raises(ValueError, match="bandwidth_source"):
        restore_ephemeral_bandwidth(_StubSession(), {"bandwidth_source": "oracle"})

    with pytest.raises(ValueError, match="between 0 and 1"):
        restore_ephemeral_bandwidth(_StubSession(), {"bandwidth_confidence": 1.8})

    with pytest.raises(ValueError, match="between 0 and 1"):
        restore_ephemeral_bandwidth(_StubSession(), {"bandwidth_confidence": -0.2})


@pytest.mark.asyncio
async def test_current_session_endpoint_exposes_bandwidth_state(
    client: AsyncClient, async_db: AsyncSession, default_user
) -> None:
    """Active-session reads expose stored predicted/active bandwidth independently."""
    from app.models import User as UserModel

    result = await async_db.execute(select(UserModel).where(UserModel.id == default_user.id))
    user = result.scalar_one()

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(UTC),
        predicted_bandwidth="balanced",
        active_bandwidth="light",
        bandwidth_source="manual",
        bandwidth_confidence=0.75,
        bandwidth_version="1",
        bandwidth_updated_at=datetime.now(UTC),
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
    # Bandwidth state is nested under the "bandwidth" field
    assert data["bandwidth"] is not None
    assert data["bandwidth"]["predicted_bandwidth"] == "balanced"
    assert data["bandwidth"]["active_bandwidth"] == "light"
    assert data["bandwidth"]["confidence"] == 0.75
    assert data["bandwidth"]["source"] == "manual"
    assert data["bandwidth"]["mode_version"] == "1"


@pytest.mark.asyncio
async def test_get_session_by_id_exposes_null_bandwidth_for_legacy_row(
    auth_client: AsyncClient, async_db: AsyncSession, default_user
) -> None:
    """Legacy sessions serialize with null bandwidth fields, staying API-valid."""
    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    data = response.json()
    # Bandwidth state is nested under the "bandwidth" field
    assert data["bandwidth"] is not None
    assert data["bandwidth"]["predicted_bandwidth"] is None
    assert data["bandwidth"]["active_bandwidth"] is None
    assert data["bandwidth"]["source"] is None


def test_bandwidth_state_never_lands_on_thread_or_list_view() -> None:
    """AC5: Ephemeral state stays off durable affinity data and narrow views."""
    assert not hasattr(Thread, "predicted_bandwidth")
    assert not hasattr(Thread, "active_bandwidth")
    assert not hasattr(Thread, "bandwidth_confidence")
    assert "predicted_bandwidth" not in SessionListItem.model_fields
    assert "active_bandwidth" not in SessionListItem.model_fields
    assert BANDWIDTH_CHOICES == {"light", "balanced", "deep"}
    assert BANDWIDTH_SOURCE_CHOICES == {"inferred", "manual", "snooze", "quiz"}


@pytest.mark.asyncio
async def test_undo_delta_restore_recovers_pre_rating_bandwidth(
    async_db: AsyncSession, sample_data: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undoing a rating restores the exact bandwidth captured before it."""
    from app.api.undo import (
        _is_delta_snapshot,
        _latest_delta_snapshot,
        _restore_from_delta_snapshot,
    )
    from app.services.snapshot_contract import SNAPSHOT_VERSION, SNAPSHOT_VERSION_KEY

    session = sample_data["sessions"][0]
    thread = sample_data["threads"][0]

    pre_state = {
        "start_die": 6,
        "manual_die": None,
        "current_die": 6,
        "pending_thread_id": None,
        "pending_thread_updated_at": None,
        "ended_at": None,
        "snoozed_thread_ids": None,
        "predicted_bandwidth": "balanced",
        "active_bandwidth": "light",
        "bandwidth_confidence": 0.8,
        "bandwidth_source": "inferred",
        "bandwidth_version": CURRENT_BANDWIDTH_MODE_VERSION,
        "bandwidth_updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states={
            SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            str(thread.id): {"issues_remaining": thread.issues_remaining},
        },
        session_state=pre_state,
        description="After rating",
    )
    async_db.add(snapshot)
    await async_db.commit()
    await async_db.refresh(snapshot)

    assert _is_delta_snapshot(snapshot)

    # Simulate a post-rating correction changing the live state.
    session.predicted_bandwidth = "deep"
    session.active_bandwidth = "deep"
    session.bandwidth_source = "snooze"
    session.bandwidth_confidence = 0.1
    session.bandwidth_version = "42"
    session.bandwidth_updated_at = datetime.now(UTC)
    await async_db.commit()

    latest = await _latest_delta_snapshot(async_db, session.id)
    assert latest is not None and latest.id == snapshot.id

    refreshed = await async_db.get(SessionModel, session.id)
    assert refreshed is not None
    await _restore_from_delta_snapshot(async_db, refreshed, latest)

    assert refreshed.predicted_bandwidth == "balanced"
    assert refreshed.active_bandwidth == "light"
    assert refreshed.bandwidth_source == "inferred"
    assert refreshed.bandwidth_confidence == 0.8
    assert refreshed.bandwidth_version == CURRENT_BANDWIDTH_MODE_VERSION
    assert refreshed.bandwidth_updated_at is not None
    assert refreshed.bandwidth_updated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_apply_stamps_mode_version_and_timestamp(
    async_db: AsyncSession, default_user
) -> None:
    """Applying state stamps the current mode version and update timestamp."""
    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()

    before = datetime.now(UTC)
    await apply_bandwidth_state(
        async_db,
        session,
        predicted_bandwidth="deep",
        active_bandwidth="balanced",
        bandwidth_source=BandwidthSource.QUIZ,
        bandwidth_confidence=1.0,
    )
    assert session.bandwidth_version == CURRENT_BANDWIDTH_MODE_VERSION
    assert session.bandwidth_updated_at is not None
    stamped = session.bandwidth_updated_at
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=UTC)
    assert stamped >= before
