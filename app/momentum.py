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
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread

# Stable compact reason codes recorded in recommendation contexts.
MOMENTUM_RECENT_HIGH_RATING = "recent_high_rating"
MOMENTUM_SAME_THREAD_MOMENTUM = "same_thread_momentum"

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


@dataclass(frozen=True)
class MomentumCandidateWeight:
    """Chooser-facing weight and reason codes for a single candidate.

    Attributes:
        candidate_id: The thread ID this weight applies to.
        weight: The exact combined weight passed to the chooser (1.0 + bonus).
        factors: Stable compact reason codes explaining the bonus components.
    """

    candidate_id: int
    weight: float
    factors: tuple[str, ...]


def _momentum_components(
    thread: Thread,
    session_events: list[Event],
    last_rating: float | None = None,
    now: datetime | None = None,
) -> tuple[float, float]:
    """Compute the capped momentum bonus split into its two components.

    Args:
        thread: The active thread being evaluated.
        session_events: Recent session events for streak/depth context.
        last_rating: Most recent durable rating for the thread (from Thread.model).
        now: Reference timestamp; defaults to current UTC time.

    Returns:
        A ``(rating_component, streak_component)`` tuple whose sum is the
        capped total bonus. Each component is individually non-negative.
    """
    if now is None:
        now = datetime.now(UTC)

    # Use the durable last_rating from the thread model when available,
    # otherwise fall back to the session event history.
    effective_rating = last_rating if last_rating is not None else thread.last_rating

    if effective_rating is None:
        # No rating evidence means no positive momentum boost.
        return 0.0, 0.0

    # Low-rated recent runs must not receive an automatic positive boost;
    # without a rating component the streak component is also suppressed so
    # low-rated runs never gain positive momentum from streak depth alone.
    if effective_rating < _HIGH_RATING_THRESHOLD:
        return 0.0, 0.0

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
    rating_component = base_bonus * decay_factor_value

    # Streak depth adds a small additional boost, capped.
    streak_depth = _streak_depth_for_thread(thread, session_events)
    streak_component = min(streak_depth * _STREAK_BONUS_PER_STEP, 1.0)
    # Streak also decays slightly with overall staleness.
    streak_component *= max(0.25, decay_factor_value)

    return rating_component, streak_component


def compute_momentum_breakdown(
    thread: Thread,
    session_events: list[Event],
    last_rating: float | None = None,
    now: datetime | None = None,
) -> MomentumCandidateWeight:
    """Compute the chooser weight plus stable reason codes for one candidate.

    Args:
        thread: The active thread being evaluated.
        session_events: Recent session events for streak/depth context.
        last_rating: Most recent durable rating for the thread (from Thread.model).
        now: Reference timestamp; defaults to current UTC time.

    Returns:
        A :class:`MomentumCandidateWeight` with ``weight`` equal to
        ``1.0 + compute_momentum_bonus(...)`` and reason codes naming every
        positive bonus component.
    """
    rating_component, streak_component = _momentum_components(
        thread=thread,
        session_events=session_events,
        last_rating=last_rating,
        now=now,
    )
    total_bonus = min(rating_component + streak_component, _MAX_MOMENTUM_BONUS)

    factors: list[str] = []
    if rating_component > 0.0:
        factors.append(MOMENTUM_RECENT_HIGH_RATING)
    if streak_component > 0.0:
        factors.append(MOMENTUM_SAME_THREAD_MOMENTUM)

    return MomentumCandidateWeight(
        candidate_id=thread.id,
        weight=1.0 + total_bonus,
        factors=tuple(factors),
    )


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
    rating_component, streak_component = _momentum_components(
        thread=thread,
        session_events=session_events,
        last_rating=last_rating,
        now=now,
    )
    return min(rating_component + streak_component, _MAX_MOMENTUM_BONUS)


async def weighted_momentum_selection(
    db: AsyncSession | None,
    bounded_rows: list,
    user_id: int,
    session_events: list[Event] | None = None,
    now: datetime | None = None,
) -> tuple[int, float, list[MomentumCandidateWeight]]:
    """Select an index from bounded_rows using momentum-weighted random choice.

    Returns:
        A tuple of ``(selected_index, applied_max_bonus, candidate_weights)``
        where selected_index is within the bounded pool, applied_max_bonus
        reports the largest bonus value among candidates (for observability /
        cap verification), and candidate_weights carries the exact chooser
        weight plus reason codes for every bounded candidate in pool order.
    """
    if session_events is None:
        session_events = []
    if now is None:
        now = datetime.now(UTC)

    if not bounded_rows:
        raise ValueError("bounded_rows must not be empty")

    # Compute chooser weights plus per-candidate reason codes for the pool.
    breakdowns = []
    for row in bounded_rows:
        # Handle both tuple rows (Thread, unread, issue_number) and plain threads.
        thread_obj = row[0] if isinstance(row, tuple) else row
        breakdowns.append(
            compute_momentum_breakdown(
                thread=thread_obj,
                session_events=session_events,
                last_rating=thread_obj.last_rating,
                now=now,
            )
        )

    weights = [breakdown.weight for breakdown in breakdowns]
    bonuses = [weight - 1.0 for weight in weights]
    max_bonus = max(bonuses) if bonuses else 0.0

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

    return selected_index, max_bonus, breakdowns
