"""Pure unit tests for momentum intent weighting (issue #1755).

Cover:
- Recently/highly rated active runs receive a modest momentum boost.
- Momentum decays with staleness.
- Low-rated recent runs do not receive an automatic positive boost solely for recency.
- Bonuses are capped and never exceed the bounded pool limits (implicitly by
  design, since bonuses only affect weights within the bounded pool).
- Pure-random bypass remains untouched (weights equal 1.0 when no positive
  momentum applies).
- Streak depth, decay, rating interaction, and cap behavior.
"""

import pytest
from datetime import UTC, datetime, timedelta

from app.momentum import (
    _calculate_staleness_decay_hours,
    _decay_factor,
    compute_momentum_bonus,
    weighted_momentum_selection,
    _MAX_MOMENTUM_BONUS,
)


class FakeEvent:
    """Lightweight stand-in for Event records in pure-unit tests."""

    def __init__(self, type: str, thread_id: int | None = None, selected_thread_id: int | None = None) -> None:
        """Initialize a fake event.

        Args:
            type: The event type (e.g., "rate", "roll").
            thread_id: Optional thread ID for rate events.
            selected_thread_id: Optional thread ID for roll events.
        """
        self.type = type
        self.thread_id = thread_id
        self.selected_thread_id = selected_thread_id


class FakeThread:
    """Lightweight stand-in for Thread objects in pure-unit tests."""

    def __init__(
        self,
        id: int = 1,
        last_rating: float | None = None,
        last_activity_at: datetime | None = None,
        status: str = "active",
    ) -> None:
        """Initialize a fake thread.

        Args:
            id: Thread identifier.
            last_rating: Optional last rating value.
            last_activity_at: Optional last activity timestamp.
            status: Thread status (default "active").
        """
        self.id = id
        self.title = f"Thread {id}"
        self.format = "Comic"
        self.last_rating = last_rating
        self.last_activity_at = last_activity_at
        self.status = status
        self.queue_position = id
        self.issues_remaining = 3


@pytest.mark.asyncio
async def test_high_rating_receives_positive_boost() -> None:
    """Recently/highly rated active runs receive a modest momentum boost."""
    now = datetime.now(UTC)
    thread = FakeThread(id=1, last_rating=5.0, last_activity_at=now - timedelta(hours=2))
    bonus = compute_momentum_bonus(thread, session_events=[], now=now)
    assert bonus > 0.0
    assert bonus <= _MAX_MOMENTUM_BONUS


@pytest.mark.asyncio
async def test_low_rating_receives_no_positive_boost() -> None:
    """Low-rated recent runs do not receive an automatic positive boost solely for recency."""
    now = datetime.now(UTC)
    thread_low = FakeThread(id=1, last_rating=2.5, last_activity_at=now - timedelta(hours=1))
    bonus = compute_momentum_bonus(thread_low, session_events=[], now=now)
    assert bonus == 0.0


@pytest.mark.asyncio
async def test_decay_reduces_bonus_over_time() -> None:
    """Momentum decays with staleness."""
    now = datetime.now(UTC)
    fresh = FakeThread(id=1, last_rating=4.5, last_activity_at=now - timedelta(hours=1))
    stale = FakeThread(id=2, last_rating=4.5, last_activity_at=now - timedelta(days=10))
    fresh_bonus = compute_momentum_bonus(fresh, session_events=[], now=now)
    stale_bonus = compute_momentum_bonus(stale, session_events=[], now=now)
    assert fresh_bonus > stale_bonus
    assert stale_bonus < fresh_bonus


@pytest.mark.asyncio
async def test_bonus_is_capped() -> None:
    """Bonuses cannot exceed the defined cap."""
    now = datetime.now(UTC)
    # Extremely fresh, extremely high-rated thread with streak.
    thread = FakeThread(id=1, last_rating=5.0, last_activity_at=now - timedelta(minutes=30))
    events = [
        FakeEvent(type="rate", thread_id=1),
        FakeEvent(type="rate", thread_id=1),
        FakeEvent(type="rate", thread_id=1),
        FakeEvent(type="rate", thread_id=1),
        FakeEvent(type="roll", selected_thread_id=1),
    ]
    bonus = compute_momentum_bonus(thread, session_events=events, now=now)
    assert bonus <= _MAX_MOMENTUM_BONUS


@pytest.mark.asyncio
async def test_pure_random_bypass_untouched() -> None:
    """When all bonuses are zero, selection remains pure-random (equal weights)."""
    now = datetime.now(UTC)
    rows = [(FakeThread(id=1, last_rating=3.0, last_activity_at=now - timedelta(hours=1)), 5, "1")]
    # Manually construct bounded_rows matching roll tuple format.
    bounded_rows = [(rows[0][0], rows[0][1], rows[0][2])]
    index, max_bonus = await weighted_momentum_selection(
        db=None,  # type: ignore[arg-type]
        bounded_rows=bounded_rows,
        user_id=1,
        session_events=[],
        now=now,
    )
    assert index == 0
    assert max_bonus == 0.0


@pytest.mark.asyncio
async def test_streak_depth_increases_bonus() -> None:
    """Current streak depth contributes modestly to the bonus."""
    now = datetime.now(UTC)
    no_streak = FakeThread(id=1, last_rating=4.5, last_activity_at=now - timedelta(hours=2))
    with_streak = FakeThread(id=2, last_rating=4.5, last_activity_at=now - timedelta(hours=2))
    streak_events = [
        FakeEvent(type="rate", thread_id=2),
        FakeEvent(type="rate", thread_id=2),
        FakeEvent(type="rate", thread_id=2),
        FakeEvent(type="roll", selected_thread_id=2),
    ]
    no_bonus = compute_momentum_bonus(no_streak, session_events=[], now=now)
    streak_bonus = compute_momentum_bonus(with_streak, session_events=streak_events, now=now)
    assert streak_bonus >= no_bonus


@pytest.mark.asyncio
async def test_no_positive_boost_for_low_rating_with_recency() -> None:
    """Even very recent low-rated runs get zero positive momentum."""
    now = datetime.now(UTC)
    thread = FakeThread(id=1, last_rating=3.5, last_activity_at=now - timedelta(minutes=5))
    bonus = compute_momentum_bonus(thread, session_events=[], now=now)
    assert bonus == 0.0


@pytest.mark.asyncio
async def test_decay_factor_decreases_monotonically() -> None:
    """Decay factor must drop as staleness increases."""
    factor_fresh = _decay_factor(0.0)
    factor_stale = _decay_factor(100.0)
    assert factor_fresh > factor_stale
    assert factor_fresh == pytest.approx(1.0, rel=1e-3)
    assert factor_stale < 1.0


def test_staleness_calculation_with_none_activity() -> None:
    """No recent activity yields infinite staleness -> zero decay factor."""
    now = datetime.now(UTC)
    hours = _calculate_staleness_decay_hours(reference_at=None, now=now)
    assert hours == float("inf")
    assert _decay_factor(hours) == 0.0


@pytest.mark.asyncio
async def test_high_rating_without_activity_timestamp_does_not_crash() -> None:
    """A highly rated thread lacking last_activity_at must not raise.

    Regresses a defect where last_rating (a float) was passed to the
    staleness helper in place of a datetime, causing an AttributeError.
    """
    now = datetime.now(UTC)
    thread = FakeThread(id=1, last_rating=5.0, last_activity_at=None)
    bonus = compute_momentum_bonus(thread, session_events=[], now=now)
    # No activity timestamp => fully decayed; no positive boost is awarded.
    assert bonus == 0.0

