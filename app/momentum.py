"""Momentum intent weighting from recent reading behavior.

Keeps bonuses capped and decaying. Only highly-rated recent runs receive
a positive boost; low-rated recent runs do not receive an automatic
positive boost solely for recency. Bonuses are bounded to the current
die pool and never pull candidates outside it. The pure-random path
remains untouched when no momentum-weighted selection is requested.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread

# Maximum momentum bonus (capped) for any single candidate.
_MAX_MOMENTUM_BONUS = 2.0

# Rating threshold below which no positive momentum is awarded.
_HIGH_RATING_THRESHOLD = 4.0

# Decay half-life in hours: bonus halves every 48 hours of staleness.
_DECAY_HALF_LIFE_HOURS = 48.0

# Small bonus per consecutive read (streak depth), capped.
_STREAK_BONUS_PER_STEP = 0.25
_MAX_STREAK_DEPTH = 4


def _streak_depth_for_thread(thread: Thread, session_events: list[Event]) -> int:
    """Compute how many consecutive reads the thread has in this session."""
    # Count rate/roll events that selected or acted on this thread.
    # For simplicity, count rate events with matching thread_id.
    depth = sum(
        1 for event in session_events if event.type == "rate" and event.thread_id == thread.id
    )
    # Also consider roll events where the thread was selected.
    depth += sum(
        1 for event in session_events
        if event.type == "roll" and event.selected_thread_id == thread.id
    )
    return min(depth, _MAX_STREAK_DEPTH)


def _recent_rate_events(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    hours_back: int = 168,
) -> list[Event]:
    """Fetch recent rate events for a thread (synchronous helper for weight calc)."""
    # This is a lightweight synchronous query wrapper; callers in async
    # contexts should await the async variant below.
    raise NotImplementedError("Use async variant in roll context.")


async def _fetch_recent_rate_events(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    hours_back: int = 168,
) -> list[Event]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back)
    result = await db.execute(
        select(Event)
        .where(Event.type == "rate")
        .where(Event.thread_id == thread_id)
        .where(Event.timestamp >= cutoff)
        .order_by(Event.timestamp.desc())
    )
    return list(result.scalars().all())


def _calculate_staleness_decay_hours(
    last_activity_at: datetime | None,
    last_rating_at: datetime | None,
    now: datetime = None,
) -> float:
    if now is None:
        now = datetime.now(UTC)
    reference = last_activity_at or last_rating_at
    if reference is None:
        # No recent activity means full decay; return large value.
        return float("inf")
    # Ensure reference has timezone info for subtraction
    reference = reference.replace(tzinfo=UTC) if reference.tzinfo is None else reference
    delta_hours = (now - reference).total_seconds() / 3600.0
    return max(0.0, delta_hours)


def _decay_factor(staleness_hours: float, half_life_hours: float = _DECAY_HALF_LIFE_HOURS) -> float:
    """Exponential decay: factor = 2^(-staleness / half_life)."""
    if staleness_hours == float("inf") or staleness_hours < 0:
        return 0.0
    return math.pow(2.0, -staleness_hours / half_life_hours)


def compute_momentum_bonus(
    thread: Thread,
    session_events: list[Event],
    last_rating: float | None = None,
    now: datetime | None = None,
) -> float:
    """Compute a capped, decaying momentum bonus for a thread.

    Args:
        thread: The active thread being evaluated.
        session_events: Recent session events for streak/depth context.
        last_rating: Most recent durable rating for the thread (from Thread.model).
        now: Reference timestamp; defaults to current UTC time.

    Returns:
        A float bonus value capped at ``_MAX_MOMENTUM_BONUS``. Positive only
        when the most recent durable rating is high; zero (or near-zero) for
        low-rated runs so they do not receive an automatic positive boost.
    """
    if now is None:
        now = datetime.now(UTC)

    # Use the durable last_rating from the thread model when available,
    # otherwise fall back to the session event history.
    effective_rating = last_rating if last_rating is not None else thread.last_rating

    if effective_rating is None:
        # No rating evidence means no positive momentum boost.
        return 0.0

    # Low-rated recent runs must not receive an automatic positive boost.
    if effective_rating < _HIGH_RATING_THRESHOLD:
        return 0.0

    # Compute staleness from the most recent activity timestamp.
    staleness_hours = _calculate_staleness_decay_hours(
        thread.last_activity_at,
        thread.last_rating,
        now=now,
    )

    decay_factor_value = _decay_factor(staleness_hours)

    # Modest base bonus scaled by how highly rated the thread is.
    base_bonus = min(
        (effective_rating - _HIGH_RATING_THRESHOLD) * 0.5,
        1.0,
    )
    decayed_bonus = base_bonus * decay_factor_value

    # Streak depth adds a small additional boost, capped.
    streak_depth = _streak_depth_for_thread(thread, session_events)
    streak_bonus = min(streak_depth * _STREAK_BONUS_PER_STEP, 1.0)
    # Streak also decays slightly with overall staleness.
    streak_bonus *= max(0.25, decay_factor_value)

    total_bonus = decayed_bonus + streak_bonus
    return min(total_bonus, _MAX_MOMENTUM_BONUS)


async def weighted_momentum_selection(
    db: AsyncSession,
    bounded_rows: list,
    user_id: int,
    session_events: list[Event] | None = None,
    now: datetime | None = None,
) -> tuple[int, float]:
    """Select an index from bounded_rows using momentum-weighted random choice.

    Returns:
        A tuple of (selected_index, applied_max_bonus) where selected_index
        is within the bounded pool and applied_max_bonus reports the largest
        bonus value among candidates (for observability / cap verification).
    """
    if session_events is None:
        session_events = []
    if now is None:
        now = datetime.now(UTC)

    if not bounded_rows:
        raise ValueError("bounded_rows must not be empty")

    # Compute bonuses for each thread in the bounded pool.
    bonuses = []
    for row in bounded_rows:
        thread = row[0] if isinstance(row, tuple) else row
        # Handle both tuple rows (Thread, unread, issue_number) and plain threads.
        if isinstance(row, tuple):
            thread_obj = row[0]
        else:
            thread_obj = row
        bonus = compute_momentum_bonus(
            thread=thread_obj,
            session_events=session_events,
            last_rating=thread_obj.last_rating,
            now=now,
        )
        bonuses.append(bonus)

    max_bonus = max(bonuses) if bonuses else 0.0

    # Weights are 1.0 + bonus, so a zero bonus equals pure-random weight.
    weights = [1.0 + b for b in bonuses]

    # Weighted random selection using cumulative weights.
    total_weight = sum(weights)
    if total_weight <= 0:
        # Fallback to uniform random if weights collapse (should not happen).
        import random
        selected_index = random.randint(0, len(bounded_rows) - 1)
    else:
        import random
        pick = random.uniform(0, total_weight)
        cumulative = 0.0
        selected_index = 0
        for i, w in enumerate(weights):
            cumulative += w
            if pick <= cumulative:
                selected_index = i
                break

    return selected_index, max_bonus
