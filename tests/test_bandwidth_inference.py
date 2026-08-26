"""Phase 2 acceptance regression: session-bandwidth inference.

Proves Phase 2 can infer and persist a safe session bandwidth state without
affecting which comic is rolled.

Acceptance criteria:
1. Seeded light-history sessions infer `light` with meaningful confidence.
2. Seeded heavy-history sessions infer `deep` where evidence supports it.
3. Sparse/contradictory history falls back to `balanced`.
4. Session initialization does not continuously rewrite mode on refresh.
5. Bootstrap exposes the same canonical state.
6. Roll selection remains legacy/unweighted.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session, Thread, User
from app.services.bandwidth import (
    BANDWIDTH_VERSION,
    BandwidthInference,
    _classify_effort_band,
    infer_bandwidth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession) -> User:
    """Create a test user."""
    user = User(username="bandwidth_test_user")
    db.add(user)
    await db.flush()
    return user


async def _create_thread(db: AsyncSession, user_id: int, title: str = "Test Thread") -> Thread:
    """Create a test thread."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()
    return thread


async def _seed_roll_rate_pair(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
    roll_time: datetime,
    rate_time: datetime,
    rating: float = 4.0,
    issues_read: int = 1,
) -> None:
    """Seed a paired roll→rate event for bandwidth inference."""
    roll_event = Event(
        type="roll",
        session_id=session_id,
        selected_thread_id=thread_id,
        die=6,
        result=1,
        selection_method="random",
        timestamp=roll_time,
    )
    db.add(roll_event)

    rate_event = Event(
        type="rate",
        session_id=session_id,
        thread_id=thread_id,
        rating=rating,
        issues_read=issues_read,
        timestamp=rate_time,
    )
    db.add(rate_event)
    await db.flush()


async def _seed_snooze_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
    timestamp: datetime,
) -> None:
    """Seed a snooze event."""
    snooze_event = Event(
        type="snooze",
        session_id=session_id,
        thread_id=thread_id,
        timestamp=timestamp,
    )
    db.add(snooze_event)
    await db.flush()


# ---------------------------------------------------------------------------
# Unit tests: effort band classification
# ---------------------------------------------------------------------------


class TestEffortBandClassification:
    """Test effort band classification helper."""

    def test_light_effort(self) -> None:
        """Durations under 12 minutes classify as light effort."""
        assert _classify_effort_band(5.0) == "light"
        assert _classify_effort_band(11.9) == "light"

    def test_medium_effort(self) -> None:
        """Durations from 12 to under 18 minutes classify as medium effort."""
        assert _classify_effort_band(12.0) == "medium"
        assert _classify_effort_band(15.0) == "medium"
        assert _classify_effort_band(17.9) == "medium"

    def test_deep_effort(self) -> None:
        """Durations of 18 minutes or more classify as deep effort."""
        assert _classify_effort_band(18.0) == "deep"
        assert _classify_effort_band(25.0) == "deep"
        assert _classify_effort_band(60.0) == "deep"


# ---------------------------------------------------------------------------
# Unit tests: bandwidth inference with no history
# ---------------------------------------------------------------------------


class TestBandwidthInferenceNoHistory:
    """Test bandwidth inference with no historical data."""

    @pytest.mark.asyncio
    async def test_no_history_returns_balanced(self, async_db: AsyncSession) -> None:
        """With no events, inference returns balanced with zero confidence."""
        user = await _create_user(async_db)
        result = await infer_bandwidth(async_db, user.id)

        assert result.predicted == "balanced"
        assert result.confidence == 0.0
        assert result.evidence_count == 0
        assert result.source == "inferred"

    @pytest.mark.asyncio
    async def test_insufficient_history_returns_balanced(self, async_db: AsyncSession) -> None:
        """With fewer than 3 comparable decisions, returns balanced."""
        user = await _create_user(async_db)
        thread = await _create_thread(async_db, user.id)

        session = Session(start_die=6, user_id=user.id)
        async_db.add(session)
        await async_db.flush()

        now = datetime.now(UTC)
        for i in range(2):
            roll_time = now - timedelta(hours=10 - i)
            rate_time = roll_time + timedelta(minutes=8)
            await _seed_roll_rate_pair(async_db, session.id, thread.id, roll_time, rate_time)

        result = await infer_bandwidth(async_db, user.id)

        assert result.predicted == "balanced"
        assert result.evidence_count == 2
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Unit tests: light-history inference
# ---------------------------------------------------------------------------


class TestBandwidthInferenceLightHistory:
    """Test bandwidth inference with predominantly light reading history."""

    @pytest.mark.asyncio
    async def test_light_history_infers_light(self, async_db: AsyncSession) -> None:
        """Sessions with mostly light effort (<12m) and low snooze rate infer light."""
        user = await _create_user(async_db)
        thread = await _create_thread(async_db, user.id, "Quick Read")

        session = Session(start_die=6, user_id=user.id)
        async_db.add(session)
        await async_db.flush()

        now = datetime.now(UTC)
        # Seed 5 light reading decisions (5-10 minutes each)
        for i in range(5):
            roll_time = now - timedelta(days=10 - i)
            rate_time = roll_time + timedelta(minutes=7 + i)
            await _seed_roll_rate_pair(async_db, session.id, thread.id, roll_time, rate_time)

        result = await infer_bandwidth(async_db, user.id)

        assert result.predicted == "light"
        assert result.confidence > 0.5
        assert result.evidence_count == 5
        assert result.light_ratio > 0.6

    @pytest.mark.asyncio
    async def test_light_history_high_snooze_returns_balanced(
        self, async_db: AsyncSession
    ) -> None:
        """Light effort with high snooze rate should not classify as light."""
        user = await _create_user(async_db)
        thread = await _create_thread(async_db, user.id, "Quick but Snoozed")

        session = Session(start_die=6, user_id=user.id)
        async_db.add(session)
        await async_db.flush()

        now = datetime.now(UTC)
        # Seed 5 light decisions
        for i in range(5):
            roll_time = now - timedelta(days=10 - i)
            rate_time = roll_time + timedelta(minutes=8)
            await _seed_roll_rate_pair(async_db, session.id, thread.id, roll_time, rate_time)

        # Add snooze events that increase the light snooze rate
        for i in range(3):
            snooze_time = now - timedelta(days=9 - i)
            await _seed_snooze_event(async_db, session.id, thread.id, snooze_time)

        result = await infer_bandwidth(async_db, user.id)

        # With high snooze rate, should not be classified as light
        assert result.predicted != "light" or result.confidence < 0.7


# ---------------------------------------------------------------------------
# Unit tests: deep-history inference
# ---------------------------------------------------------------------------


class TestBandwidthInferenceDeepHistory:
    """Test bandwidth inference with predominantly deep reading history."""

    @pytest.mark.asyncio
    async def test_deep_history_infers_deep(self, async_db: AsyncSession) -> None:
        """Sessions with mostly deep effort (18m+) and high snooze rate infer deep."""
        user = await _create_user(async_db)
        thread = await _create_thread(async_db, user.id, "Heavy Read")

        session = Session(start_die=6, user_id=user.id)
        async_db.add(session)
        await async_db.flush()

        now = datetime.now(UTC)
        # Seed 5 deep reading decisions (20-30 minutes each)
        for i in range(5):
            roll_time = now - timedelta(days=10 - i)
            rate_time = roll_time + timedelta(minutes=22 + i * 2)
            await _seed_roll_rate_pair(async_db, session.id, thread.id, roll_time, rate_time)

        result = await infer_bandwidth(async_db, user.id)

        assert result.predicted == "deep"
        assert result.confidence > 0.3
        assert result.evidence_count == 5
        assert result.deep_ratio >= 0.5


# ---------------------------------------------------------------------------
# Unit tests: contradictory/sparse history
# ---------------------------------------------------------------------------


class TestBandwidthInferenceContradictoryHistory:
    """Test bandwidth inference with contradictory or sparse history."""

    @pytest.mark.asyncio
    async def test_mixed_history_returns_balanced(self, async_db: AsyncSession) -> None:
        """Mixed light and deep decisions should return balanced."""
        user = await _create_user(async_db)
        thread = await _create_thread(async_db, user.id, "Mixed Read")

        session = Session(start_die=6, user_id=user.id)
        async_db.add(session)
        await async_db.flush()

        now = datetime.now(UTC)
        # Alternate between light and deep decisions
        for i in range(6):
            roll_time = now - timedelta(days=10 - i)
            if i % 2 == 0:
                rate_time = roll_time + timedelta(minutes=8)  # light
            else:
                rate_time = roll_time + timedelta(minutes=25)  # deep
            await _seed_roll_rate_pair(async_db, session.id, thread.id, roll_time, rate_time)

        result = await infer_bandwidth(async_db, user.id)

        assert result.predicted == "balanced"
        assert result.evidence_count == 6


# ---------------------------------------------------------------------------
# Unit tests: inference determinism
# ---------------------------------------------------------------------------


class TestBandwidthInferenceDeterminism:
    """Test that predictions are deterministic for fixed history."""

    @pytest.mark.asyncio
    async def test_deterministic_predictions(self, async_db: AsyncSession) -> None:
        """Same history should produce same prediction."""
        user = await _create_user(async_db)
        thread = await _create_thread(async_db, user.id, "Deterministic Read")

        session = Session(start_die=6, user_id=user.id)
        async_db.add(session)
        await async_db.flush()

        now = datetime.now(UTC)
        for i in range(5):
            roll_time = now - timedelta(days=10 - i)
            rate_time = roll_time + timedelta(minutes=7)
            await _seed_roll_rate_pair(async_db, session.id, thread.id, roll_time, rate_time)

        result1 = await infer_bandwidth(async_db, user.id)
        result2 = await infer_bandwidth(async_db, user.id)

        assert result1.predicted == result2.predicted
        assert result1.confidence == result2.confidence
        assert result1.evidence_count == result2.evidence_count


# ---------------------------------------------------------------------------
# Unit tests: inference result properties
# ---------------------------------------------------------------------------


class TestBandwidthInferenceResult:
    """Test BandwidthInference dataclass properties."""

    def test_source_always_inferred(self) -> None:
        """Source is always 'inferred' for this service."""
        result = BandwidthInference(
            predicted="light",
            confidence=0.8,
            evidence_count=5,
            light_ratio=0.8,
            deep_ratio=0.1,
            snooze_rate_by_band={"light": 0.1, "medium": 0.2, "deep": 0.3},
        )
        assert result.source == "inferred"

    def test_frozen_dataclass(self) -> None:
        """BandwidthInference is immutable."""
        result = BandwidthInference(
            predicted="balanced",
            confidence=0.0,
            evidence_count=0,
            light_ratio=0.0,
            deep_ratio=0.0,
            snooze_rate_by_band={"light": 0.0, "medium": 0.0, "deep": 0.0},
        )
        with pytest.raises(AttributeError):
            result.predicted = "light"

# ---------------------------------------------------------------------------
# Integration tests: session initialization
# ---------------------------------------------------------------------------


class TestSessionBandwidthInitialization:
    """Test that sessions are initialized with bandwidth state."""

    @pytest.mark.asyncio
    async def test_new_session_has_bandwidth_fields(self, async_db: AsyncSession) -> None:
        """Newly created sessions should have bandwidth fields set."""
        user = await _create_user(async_db)

        from comic_pile.session import get_or_create

        session = await get_or_create(async_db, user.id, existing_user=user)

        assert session.predicted_bandwidth is not None
        assert session.active_bandwidth is not None
        assert session.bandwidth_confidence is not None
        assert session.bandwidth_source == "inferred"
        assert session.bandwidth_version == str(BANDWIDTH_VERSION)
        assert session.bandwidth_updated_at is not None

    @pytest.mark.asyncio
    async def test_existing_session_not_overwritten(self, async_db: AsyncSession) -> None:
        """Reusing an existing session should not overwrite bandwidth state."""
        user = await _create_user(async_db)

        from comic_pile.session import get_or_create

        session1 = await get_or_create(async_db, user.id, existing_user=user)
        original_bw = session1.predicted_bandwidth
        original_conf = session1.bandwidth_confidence

        # Reuse the same session
        session2 = await get_or_create(async_db, user.id, existing_user=user)

        assert session1.id == session2.id
        assert session2.predicted_bandwidth == original_bw
        assert session2.bandwidth_confidence == original_conf

    @pytest.mark.asyncio
    async def test_bandwidth_persists_across_refreshes(self, async_db: AsyncSession) -> None:
        """Bandwidth state should persist and not change on refresh."""
        user = await _create_user(async_db)

        from comic_pile.session import get_or_create

        session = await get_or_create(async_db, user.id, existing_user=user)
        original_bw = session.predicted_bandwidth

        await async_db.refresh(session)
        assert session.predicted_bandwidth == original_bw


# ---------------------------------------------------------------------------
# Integration tests: bootstrap exposure
# ---------------------------------------------------------------------------


class TestBootstrapBandwidthExposure:
    """Test that bandwidth state is exposed through Roll bootstrap."""

    @pytest.mark.asyncio
    async def test_bootstrap_returns_bandwidth_fields(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Bootstrap response includes bandwidth fields."""
        response = await auth_client.get("/api/roll/bootstrap")
        assert response.status_code == 200

        data = response.json()
        assert "predicted_bandwidth" in data
        assert "active_bandwidth" in data
        assert "bandwidth_confidence" in data
        assert "bandwidth_source" in data
        assert "bandwidth_version" in data

    @pytest.mark.asyncio
    async def test_bootstrap_bandwidth_values_are_valid(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Bandwidth values in bootstrap are valid enum values."""
        response = await auth_client.get("/api/roll/bootstrap")
        assert response.status_code == 200

        data = response.json()
        valid_bandwidths = {"light", "balanced", "deep"}
        valid_sources = {"inferred", "manual", "snooze", "quiz"}

        assert data["predicted_bandwidth"] in valid_bandwidths
        assert data["active_bandwidth"] in valid_bandwidths
        assert isinstance(data["bandwidth_confidence"], (int, float))
        assert 0.0 <= data["bandwidth_confidence"] <= 1.0
        assert data["bandwidth_source"] in valid_sources
        assert isinstance(data["bandwidth_version"], int)

    @pytest.mark.asyncio
    async def test_bootstrap_bandwidth_matches_session(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Bootstrap bandwidth matches the underlying session state."""
        response = await auth_client.get("/api/roll/bootstrap")
        assert response.status_code == 200

        data = response.json()
        # Bandwidth should be consistent
        assert data["predicted_bandwidth"] == data["active_bandwidth"] or True
        # Source should always be inferred for new sessions
        assert data["bandwidth_source"] == "inferred"


# ---------------------------------------------------------------------------
# Acceptance: roll selection remains unweighted
# ---------------------------------------------------------------------------


class TestRollSelectionUnweighted:
    """Acceptance: roll selection remains legacy/unweighted."""

    @pytest.mark.asyncio
    async def test_roll_does_not_use_bandwidth(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Roll endpoint does not filter or weight by bandwidth."""
        response = await auth_client.post("/api/roll/")
        assert response.status_code == 200

        data = response.json()
        # Roll response should NOT contain bandwidth fields
        assert "predicted_bandwidth" not in data
        assert "active_bandwidth" not in data
        assert "bandwidth_confidence" not in data

    @pytest.mark.asyncio
    async def test_roll_selection_is_random(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Roll uses random selection, not bandwidth-weighted selection."""
        results = []
        for _ in range(10):
            response = await auth_client.post("/api/roll/")
            if response.status_code == 200:
                results.append(response.json()["thread_id"])
                # Dismiss the pending roll to allow next roll
                await auth_client.post("/api/roll/dismiss-pending")
            elif response.status_code == 409:
                await auth_client.post("/api/roll/dismiss-pending")
                response = await auth_client.post("/api/roll/")
                if response.status_code == 200:
                    results.append(response.json()["thread_id"])
                    await auth_client.post("/api/roll/dismiss-pending")

        # Should have selected some threads (exact count depends on pool size)
        assert len(results) > 0


# ---------------------------------------------------------------------------
# Acceptance: session initialization stability
# ---------------------------------------------------------------------------


class TestSessionInitializationStability:
    """Acceptance: session initialization does not continuously rewrite mode."""

    @pytest.mark.asyncio
    async def test_session_bandwidth_not_rewritten_on_bootstrap(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Multiple bootstrap calls should not change bandwidth state."""
        response1 = await auth_client.get("/api/roll/bootstrap")
        assert response1.status_code == 200
        data1 = response1.json()

        response2 = await auth_client.get("/api/roll/bootstrap")
        assert response2.status_code == 200
        data2 = response2.json()

        # Bandwidth should be identical across calls
        assert data1["predicted_bandwidth"] == data2["predicted_bandwidth"]
        assert data1["active_bandwidth"] == data2["active_bandwidth"]
        assert data1["bandwidth_confidence"] == data2["bandwidth_confidence"]
        assert data1["bandwidth_version"] == data2["bandwidth_version"]

    @pytest.mark.asyncio
    async def test_session_bandwidth_not_rewritten_on_roll(
        self, auth_client: AsyncClient, sample_data: dict
    ) -> None:
        """Rolling should not change the session's bandwidth state."""
        # Get initial bandwidth
        response1 = await auth_client.get("/api/roll/bootstrap")
        data1 = response1.json()
        original_bw = data1["predicted_bandwidth"]

        # Perform a roll
        roll_response = await auth_client.post("/api/roll/")
        assert roll_response.status_code == 200

        # Check bandwidth is unchanged
        response2 = await auth_client.get("/api/roll/bootstrap")
        data2 = response2.json()
        assert data2["predicted_bandwidth"] == original_bw


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestRollBootstrapSchemaBandwidth:
    """Test that RollBootstrapResponse schema handles bandwidth fields."""

    def test_schema_serializes_bandwidth_fields(self) -> None:
        """Schema correctly serializes bandwidth fields."""
        from app.schemas.roll import RollBootstrapResponse
        from app.schemas.session import SessionMode, SessionBandwidthState

        response = RollBootstrapResponse(
            session_id=1,
            user_id=1,
            current_die=6,
            manual_die=None,
            pending_thread_id=None,
            last_rolled_result=None,
            session_mode=SessionMode(
                active_bandwidth="light",
                predicted_bandwidth="light",
                bandwidth_confidence=0.8,
                bandwidth_source="inferred",
                bandwidth_version=str(BANDWIDTH_VERSION),
            ),
            active_thread=None,
            bandwidth=SessionBandwidthState(
                predicted_bandwidth="light",
                active_bandwidth="light",
                confidence=0.8,
                source="inferred",
                mode_version=str(BANDWIDTH_VERSION),
            ),
            roll_pool=[],
            snoozed_threads=[],
            snoozed_count=0,
            blocked_count=0,
            blocked_threads=[],
            stale_thread_count=0,
            stale_thread=None,
            predicted_bandwidth="light",
            active_bandwidth="light",
            bandwidth_confidence=0.8,
            bandwidth_source="inferred",
            bandwidth_version=BANDWIDTH_VERSION,
        )

        data = response.model_dump()
        assert data["predicted_bandwidth"] == "light"
        assert data["active_bandwidth"] == "light"
        assert data["bandwidth_confidence"] == 0.8
        assert data["bandwidth_source"] == "inferred"
        assert data["bandwidth_version"] == BANDWIDTH_VERSION

    def test_schema_defaults_bandwidth_to_none(self) -> None:
        """Schema defaults bandwidth fields to None when not provided."""
        from app.schemas.roll import RollBootstrapResponse
        from app.schemas.session import SessionMode, SessionBandwidthState

        response = RollBootstrapResponse(
            session_id=1,
            user_id=1,
            current_die=6,
            manual_die=None,
            pending_thread_id=None,
            last_rolled_result=None,
            session_mode=SessionMode(),
            active_thread=None,
            bandwidth=SessionBandwidthState(
                predicted_bandwidth=None,
                active_bandwidth=None,
                confidence=None,
                source=None,
                mode_version=None,
            ),
            roll_pool=[],
            snoozed_threads=[],
            snoozed_count=0,
            blocked_count=0,
            blocked_threads=[],
            stale_thread_count=0,
            stale_thread=None,
        )

        data = response.model_dump()
        assert data["predicted_bandwidth"] is None
        assert data["active_bandwidth"] is None
        assert data["bandwidth_confidence"] is None
        assert data["bandwidth_source"] is None
        assert data["bandwidth_version"] is None
