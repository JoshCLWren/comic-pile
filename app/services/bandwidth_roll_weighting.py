"""Apply documented bandwidth weights inside the bounded roll pool.

Phase 3 selection-integration ticket #1715: consumes the pure bandwidth
weights delivered by #1712 (:mod:`comic_pile.recommendation_weights`) and
feeds them with the Phase 1 reading-effort pipeline (#1700 decision
latencies -> #1701 observation rules -> #1702/#1705 effort aggregation).

Guarantees carried over from the ticket contracts:

- Candidate eligibility and die boundaries are untouched; only candidates
  already inside the bounded pool can receive a weight or be selected.
- ``balanced`` (and any absent/unrecognized bandwidth) yields exactly
  neutral weights so the legacy unweighted selection path is preserved.
- Unknown or sparse (untrusted) effort estimates stay exactly neutral so
  missing evidence can never distort selection.
- Every documented weight is strictly positive, so contextual weighting
  redistributes probability only inside the pool and never excludes a
  candidate. Invalid inputs degrade safely to neutral weighting.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session as SessionModel, Thread
from app.services.decision_latency import derive_roll_rate_latencies
from comic_pile.reading_effort import EffortSummary, EffortObservation, aggregate_efforts
from comic_pile.reading_effort_observation_rules import (
    DurationObservation,
    classify_reading_effort_observations,
)
from comic_pile.recommendation_weights import (
    build_candidate_weights,
    normalize_bandwidth,
)

PoolRow = tuple[Thread, int, str | None]


async def load_user_decision_events(db: AsyncSession, user_id: int) -> list[Event]:
    """Load the user's roll and rate events needed for effort derivation.

    Read-only helper scoped to one user through the owning reading sessions,
    so another reader's history can never influence this reader's weights.

    Args:
        db: Database session used exclusively for reads.
        user_id: Authenticated reader whose decision history is loaded.

    Returns:
        Roll and rate events ordered by event ID.
    """
    stmt = (
        select(Event)
        .join(SessionModel, Event.session_id == SessionModel.id)
        .where(SessionModel.user_id == user_id)
        .where(Event.type.in_(frozenset({"roll", "rate"})))
        .order_by(Event.id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def build_user_effort_summary(events: list[Event]) -> EffortSummary:
    """Aggregate validated decision latencies into per-thread effort estimates.

    Applies the #1700 latency derivation and the #1701 observation rules so
    only trustworthy roll-to-rate durations feed the #1705 aggregation.
    Observations deliberately carry no issue linkage because the bounded roll
    pool exposes thread identity only; all evidence therefore lands in the
    thread-level pools where candidate lookups happen.

    Args:
        events: The user's persisted roll and rate events.

    Returns:
        Thread-keyed effort estimates. Pools are empty when no valid
        observations exist, and every lookup then resolves to unknown effort.
    """
    latencies = derive_roll_rate_latencies(events)
    durations = [
        DurationObservation(
            duration_seconds=latency.elapsed_seconds,
            roll_event_id=latency.roll_event_id,
            rate_event_id=latency.rate_event_id,
            thread_id=latency.thread_id,
        )
        for latency in latencies
    ]
    observations: list[EffortObservation] = []
    for result in classify_reading_effort_observations(durations):
        thread_id = result.observation.thread_id
        if result.included and thread_id is not None:
            observations.append(
                EffortObservation(
                    thread_id=thread_id,
                    issue_id=None,
                    duration_seconds=result.observation.duration_seconds,
                )
            )
    return aggregate_efforts(observations)


def resolve_candidate_efforts(
    summary: EffortSummary,
    bounded_rows: list[PoolRow],
) -> list[tuple[int, float | None]]:
    """Resolve one trusted effort estimate in minutes per pool candidate.

    Only trusted estimates (enough observed readings) inform weighting;
    sparse history stays neutral per the Phase 1 confidence contract. Rows
    may be ``(Thread, unread_count, issue_number)`` tuples or plain threads.

    Args:
        summary: Aggregated effort indexes for the user's reading history.
        bounded_rows: Die-bounded candidate rows in pool order.

    Returns:
        One ``(thread_id, effort_minutes_or_None)`` pair per candidate,
        preserving pool order.
    """
    efforts: list[tuple[int, float | None]] = []
    for row in bounded_rows:
        thread_obj = row[0] if isinstance(row, tuple) else row
        estimate = summary.threads.get(thread_obj.id)
        trusted_minutes = (
            estimate.median_seconds / 60 if estimate is not None and estimate.trusted else None
        )
        efforts.append((thread_obj.id, trusted_minutes))
    return efforts


def build_bandwidth_candidate_weights(
    bounded_rows: list[PoolRow],
    efforts: list[tuple[int, float | None]],
    bandwidth: str | None,
) -> tuple[list[float], bool]:
    """Build documented per-candidate weights plus an applied flag.

    Wraps :func:`comic_pile.recommendation_weights.build_candidate_weights`
    so every weight comes from the single centralized cap table instead of
    ad-hoc formulas. Unknown or unrecognized bandwidth normalizes to
    ``balanced`` (neutral), satisfying the safe-fallback acceptance rule.

    Args:
        bounded_rows: Die-bounded candidate rows in pool order.
        efforts: One ``(thread_id, effort_minutes_or_None)`` pair per row.
        bandwidth: Active session bandwidth label, if any.

    Returns:
        Tuple of (one strictly positive float per candidate in pool order,
        True when any weight deviates from neutral).
    """
    mode = normalize_bandwidth(bandwidth)
    weighted_candidates = build_candidate_weights(efforts, mode)
    weights = [candidate.weight for candidate in weighted_candidates]
    applied = len({round(weight, 9) for weight in weights}) > 1
    return weights, applied


async def resolve_bandwidth_weights(
    db: AsyncSession,
    *,
    user_id: int,
    bounded_rows: list[PoolRow],
    bandwidth: str | None,
) -> tuple[list[float], bool]:
    """Resolve documented bandwidth weights for one roll's bounded pool.

    End-to-end orchestration: load the reader's decision history, derive
    validated effort estimates, and apply the #1712 weight table inside the
    existing die-bounded pool. Any failure of evidence simply yields neutral
    weights, so selection degrades to the legacy uniform path.

    Args:
        db: Database session used exclusively for reads.
        user_id: Authenticated reader whose history informs the weights.
        bounded_rows: Die-bounded candidate rows in pool order.
        bandwidth: Requested or session-derived bandwidth label, if any.

    Returns:
        Tuple of (one positive weight per bounded candidate, True when any
        weight deviates from neutral).
    """
    events = await load_user_decision_events(db, user_id)
    summary = build_user_effort_summary(events)
    efforts = resolve_candidate_efforts(summary, bounded_rows)
    return build_bandwidth_candidate_weights(bounded_rows, efforts, bandwidth)
