"""Regression for the recorded roll selection method (issue #3762).

The session timeline renders each roll as "Selected by <selection_method>".
That label used to follow the weight values of a single draw instead of the
active reading mode, so one fixed Balanced intent recorded different labels
for different rolls: a pool whose candidates all carried a neutral weight
recorded ``random`` while a pool with any real signal recorded ``momentum``
(#3762). ``random`` now means only the documented random bypass.

This file pins that contract:

- one active mode always records one selection method, whatever the pool
  happens to contain;
- ``random`` is recorded only for the random-intent bypass;
- ``bandwidth`` is recorded for the effort-weighted bandwidths;
- ``legacy`` is recorded only for the operator kill switch;
- the recorded reason codes name the same control path as the method.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, RecommendationContext, Thread, User
from app.services.roll_service import derive_recorded_selection_method
from comic_pile.recommendation_selection import SelectionMode


async def _add_thread(
    db: AsyncSession,
    user: User,
    title: str,
    *,
    queue_position: int,
) -> Thread:
    """Create one active reading thread for the user.

    Args:
        db: Active database session.
        user: Owner of the thread.
        title: Thread title.
        queue_position: Queue position inside the die pool.

    Returns:
        The persisted thread.
    """
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _latest_roll_event(db: AsyncSession) -> Event:
    """Return the most recently recorded roll event.

    Args:
        db: Active database session.

    Returns:
        The newest ``roll`` event.
    """
    result = await db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    return result.scalar_one()


async def _context_for(db: AsyncSession, event: Event) -> RecommendationContext:
    """Return the recommendation context recorded for one roll event.

    Args:
        db: Active database session.
        event: Roll event whose context is requested.

    Returns:
        The persisted recommendation context for the event.
    """
    result = await db.execute(
        select(RecommendationContext).where(RecommendationContext.event_id == event.id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Pure derivation: the recorded method follows the active mode
# ---------------------------------------------------------------------------


def test_balanced_mode_records_momentum() -> None:
    """Balanced bandwidth records the momentum-weighted control path."""
    method, codes = derive_recorded_selection_method(
        resolved_mode=SelectionMode.LEGACY_UNIFORM,
        selection_bandwidth="balanced",
    )
    assert method == "momentum"
    assert codes == ["momentum_weighted"]


def test_contextual_weighted_mode_records_momentum() -> None:
    """A momentum intent on balanced bandwidth records the momentum path."""
    method, codes = derive_recorded_selection_method(
        resolved_mode=SelectionMode.CONTEXTUAL_WEIGHTED,
        selection_bandwidth="balanced",
    )
    assert method == "momentum"
    assert codes == ["momentum_weighted"]


@pytest.mark.parametrize("bandwidth", ["light", "deep"])
def test_effort_weighted_bandwidths_record_bandwidth(bandwidth: str) -> None:
    """Light and deep bandwidth record the effort-weighted control path.

    Args:
        bandwidth: The effort-weighted bandwidth under test.
    """
    method, codes = derive_recorded_selection_method(
        resolved_mode=SelectionMode.CONTEXTUAL_WEIGHTED,
        selection_bandwidth=bandwidth,
    )
    assert method == "bandwidth"
    assert codes == ["bandwidth_weighted"]


def test_random_bypass_records_random() -> None:
    """The random-intent bypass records the random method and reason code."""
    method, codes = derive_recorded_selection_method(
        resolved_mode=SelectionMode.PURE_RANDOM_BYPASS,
        selection_bandwidth="balanced",
    )
    assert method == "random"
    assert codes == ["pure_random"]


def test_forced_legacy_records_legacy() -> None:
    """The operator kill switch records the legacy method and reason code."""
    method, codes = derive_recorded_selection_method(
        resolved_mode=SelectionMode.FORCED_LEGACY,
        selection_bandwidth="balanced",
    )
    assert method == "legacy"
    assert codes == ["forced_legacy"]


# ---------------------------------------------------------------------------
# Live Roll endpoint: one intent, one recorded label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_balanced_intent_records_one_method_across_pools(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """One fixed intent records one selection method for every roll.

    This is the reported symptom: with Balanced intent for all rolls, one roll
    recorded "Selected by random" and the next recorded "Selected by
    momentum". The first pool carries no momentum signal, the second one does,
    and both rolls must still record the same method.
    """
    await _add_thread(async_db, default_user, "Spider-Man", queue_position=1)
    rated = await _add_thread(async_db, default_user, "Iron Man", queue_position=2)
    await async_db.commit()

    first_response = await auth_client.post(
        "/api/roll/", json={"intent": "balanced", "bandwidth": "balanced"}
    )
    assert first_response.status_code == 200
    first_event = await _latest_roll_event(async_db)
    first_context = await _context_for(async_db, first_event)

    # Clear the pending roll so the next one can be drawn.
    assert (await auth_client.post("/api/v1/roll/dismiss-pending")).status_code == 204

    # Give one candidate a strong recent rating so the momentum weights of the
    # second pool really differ from the first one.
    rated.last_rating = 5.0
    rated.last_activity_at = datetime.now(UTC) - timedelta(hours=1)
    await async_db.commit()

    second_response = await auth_client.post(
        "/api/roll/", json={"intent": "balanced", "bandwidth": "balanced"}
    )
    assert second_response.status_code == 200
    second_event = await _latest_roll_event(async_db)
    second_context = await _context_for(async_db, second_event)

    # The two draws really did differ: only the second one carried a
    # weighting signal.
    assert first_context.random_bypass is True
    assert second_context.random_bypass is False

    # The recorded selection context still follows the active mode.
    assert first_event.selection_method == "momentum"
    assert second_event.selection_method == "momentum"
    assert first_event.recommendation_reason_codes == ["momentum_weighted"]
    assert second_event.recommendation_reason_codes == ["momentum_weighted"]


@pytest.mark.asyncio
async def test_random_intent_records_random_method(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The random intent records the random method even with a strong signal."""
    await _add_thread(async_db, default_user, "Uncanny X-Men", queue_position=1)
    rated = await _add_thread(async_db, default_user, "X-Force", queue_position=2)
    rated.last_rating = 5.0
    rated.last_activity_at = datetime.now(UTC) - timedelta(hours=1)
    await async_db.commit()

    response = await auth_client.post("/api/roll/", json={"intent": "random"})
    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    assert event.selection_method == "random"
    assert event.recommendation_reason_codes == ["pure_random"]


@pytest.mark.asyncio
async def test_light_bandwidth_records_bandwidth_method_without_signal(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Light bandwidth records the bandwidth method even without effort data.

    Unknown effort leaves every bandwidth weight neutral. The recorded method
    still names the effort-weighted control path, so a light-bandwidth reader
    never sees the label change with the data.
    """
    await _add_thread(async_db, default_user, "Daredevil", queue_position=1)
    await _add_thread(async_db, default_user, "Hawkeye", queue_position=2)
    await async_db.commit()

    response = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    assert event.selection_method == "bandwidth"
    assert event.recommendation_reason_codes == ["bandwidth_weighted"]


@pytest.mark.asyncio
async def test_forced_legacy_control_mode_records_legacy_method(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator kill switch records the legacy method for every intent.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session.
        default_user: Reader who owns the queue.
        monkeypatch: Monkeypatcher used to flip the operator control mode.
    """
    await _add_thread(async_db, default_user, "Moon Knight", queue_position=1)
    await async_db.commit()

    from app.config import get_recommendation_settings

    monkeypatch.setenv("RECOMMENDATION_CONTROL_MODE", "legacy")
    get_recommendation_settings.cache_clear()
    try:
        response = await auth_client.post("/api/roll/", json={"intent": "balanced"})
    finally:
        monkeypatch.delenv("RECOMMENDATION_CONTROL_MODE", raising=False)
        get_recommendation_settings.cache_clear()

    assert response.status_code == 200

    event = await _latest_roll_event(async_db)
    assert event.selection_method == "legacy"
    assert event.recommendation_reason_codes == ["forced_legacy"]
