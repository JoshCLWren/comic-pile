"""Momentum intent weighting from recent reading behavior.

Keeps bonuses capped and decaying. Only highly-rated recent runs receive
a positive boost; low-rated recent runs do not receive an automatic
positive boost solely for recency. Bonuses are bounded to the current
die pool and never pull candidates outside it. The pure-random path
remains untouched when no momentum-weighted selection is requested.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime

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


def _calculate_staleness_decay_hours(
    reference_at: datetime | None,
    now: datetime | None = None,
) -> float:
    if now is None:
        now = datetime.now(UTC)
    if reference_at is None:
        # No recent activity means full decay; return large value.
        return float("inf")
    # Ensure reference has timezone info for subtraction.
    reference = (
        reference_at.replace(tzinfo=UTC)
        if reference_at.tzinfo is None
        else reference_at
    )
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

    # Compute staleness from the most recent activity timestamp. Threads
    # without a known activity time have fully decayed momentum.
    staleness_hours = _calculate_staleness_decay_hours(
        thread.last_activity_at,
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
    bandwidth_weights: list[float] | None = None,
) -> tuple[int, float]:
    """Select an index from bounded_rows using momentum-weighted random choice.

    When ``bandwidth_weights`` is supplied (one positive weight per pool row,
    e.g. from ``app.services.bandwidth_roll_weighting``), each momentum
    weight is multiplied by its bandwidth weight so the reader-bandwidth axis
    biases the same pool without ever excluding a candidate. A neutral
    bandwidth weight (1.0) leaves the momentum result untouched.

    Args:
        db: SQLAlchemy async session (reserved for future per-thread queries).
        bounded_rows: Candidate pool already bounded to the current die size.
        user_id: Authenticated user id (reserved for future per-user queries).
        session_events: Recent session events for streak/depth context.
        now: Reference timestamp; defaults to current UTC time.
        bandwidth_weights: Optional per-candidate bandwidth multiplier weights.

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
        # Handle both tuple rows (Thread, unread, issue_number) and plain threads.
        thread_obj = row[0] if isinstance(row, tuple) else row
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

    # Apply the reader-bandwidth axis multiplicatively when provided.
    if bandwidth_weights is not None:
        if len(bandwidth_weights) != len(weights):
            raise ValueError("bandwidth_weights length must match bounded_rows")
        weights = [w * bw for w, bw in zip(weights, bandwidth_weights, strict=False)]

    # Weighted random selection using cumulative weights.
    total_weight = sum(weights)
    if total_weight <= 0:
        # Fallback to uniform random if weights collapse (should not happen).
        selected_index = random.randint(0, len(bounded_rows) - 1)
    else:
        pick = random.uniform(0, total_weight)
        cumulative = 0.0
        selected_index = 0
        for i, w in enumerate(weights):
            cumulative += w
            if pick <= cumulative:
                selected_index = i
                break

    return selected_index, max_bonus
