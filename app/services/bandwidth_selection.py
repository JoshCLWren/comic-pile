"""Bandwidth-aware bounded roll selection.

Phase 3 of the personalized-Roll architecture (issue #1685, ticket #1720).
This service owns the *selection* step that changes Roll behavior: given the
session's active bandwidth and the already-bounded die pool, it weights
candidates by reading effort and combines that with the momentum factor, then
picks one index strictly inside the pool.

The die remains the hard candidate-pool boundary. This module never expands
or shrinks the pool and never selects outside it: it only redistributes
selection probability among the candidates that are already eligible
(active, unblocked, unsnoozed, dependency-satisfied).

Product rules implemented here:

- ``light`` bandwidth favors lower-effort candidates; ``deep`` bandwidth
  gently favors higher-effort candidates while never excluding light reads.
- ``balanced``/default bandwidth contributes an exactly neutral bandwidth
  factor (1.0), so the legacy momentum-selection behavior is preserved
  byte-for-byte for balanced and default rolls.
- Unknown effort is exactly neutral for any bandwidth.
- The ``random`` intent is a clean escape hatch that bypasses contextual
  weighting and reproduces legacy uniform selection exactly.
- Combined candidate weights and stable reason codes are returned so the
  caller can persist exactly what was passed to the chooser.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.momentum import compute_momentum_breakdown
from app.models import Event, Thread
from app.services.reading_effort import compute_effort_estimate
from comic_pile.recommendation_weights import (
    WeightedCandidate,
    build_candidate_weights,
)
from comic_pile.recommendation_selection import (
    SelectionMode,
    normalize_bandwidth,
    resolve_selection_mode,
    select_from_pool,
)


@dataclass(frozen=True)
class CandidateWeight:
    """One candidate's combined weight plus its stable reason codes.

    Attributes:
        candidate_id: The candidate thread identifier.
        weight: Combined momentum x bandwidth weight passed to the chooser.
        factors: Stable reason codes from both the momentum and bandwidth
            sides; empty when the candidate is completely unweighted.
    """

    candidate_id: int
    weight: float
    factors: tuple[str, ...]


@dataclass(frozen=True)
class BandwidthSelection:
    """Result of one bandwidth-aware bounded selection.

    Attributes:
        selected_index: Zero-based index into the bounded pool.
        mode: Resolved control path that produced the selection.
        weights: Combined per-candidate weights in pool order.
        bandwidth_effective: The bandwidth label actually used for weighting.
        max_bonus: Largest momentum bonus among candidates, for observability.
        weights_applied: Whether contextual weighting shaped the draw (true
            only when some combined weight differs from 1.0).
    """

    selected_index: int
    mode: SelectionMode
    weights: tuple[CandidateWeight, ...]
    bandwidth_effective: str
    max_bonus: float
    weights_applied: bool


def _resolve_pool_row(row: object) -> Thread:
    """Extract the Thread object from a pool row of either shape.

    Args:
        row: A ``(Thread, unread_count, issue_number)`` tuple or a bare Thread.

    Returns:
        The candidate Thread object.
    """
    return cast(Thread, row[0]) if isinstance(row, tuple) else cast(Thread, row)


async def select_bandwidth_weighted(
    db: AsyncSession,
    *,
    bounded_rows: Sequence[object],
    user_id: int,
    session_events: Sequence[Event] | None = None,
    bandwidth: str | None = None,
    intent: str | None = None,
    now: datetime | None = None,
) -> BandwidthSelection:
    """Select one index inside the bounded pool using bandwidth weighting.

    Args:
        db: Async database session for effort estimation.
        bounded_rows: Already-bounded die-pool candidates, in pool order.
        user_id: Owner of the reading history.
        session_events: Recent session events for momentum context.
        bandwidth: Active session bandwidth; ``None`` means balanced.
        intent: Active reading intent; ``random`` bypasses weighting.
        now: Reference timestamp; defaults to current UTC.

    Returns:
        A :class:`BandwidthSelection` recording the chosen index, the resolved
        mode, combined per-candidate weights, and whether weighting applied.

    Raises:
        ValueError: If the bounded pool is empty.
    """
    if now is None:
        now = datetime.now(UTC)
    if session_events is None:
        session_events = []
    if not bounded_rows:
        raise ValueError("bounded_rows must not be empty")

    pool_size = len(bounded_rows)
    effective_bandwidth = normalize_bandwidth(bandwidth).value
    mode = resolve_selection_mode(bandwidth, intent)

    # Pure-random intent bypasses contextual weighting: reproduce the legacy
    # uniform draw exactly inside the bounded pool.
    if mode is SelectionMode.PURE_RANDOM_BYPASS:
        outcome = select_from_pool(
            pool_size,
            bandwidth=bandwidth,
            intent=intent,
            weights=None,
        )
        neutral_weights = tuple(
            CandidateWeight(
                candidate_id=_resolve_pool_row(bounded_rows[i]).id,
                weight=1.0,
                factors=(),
            )
            for i in range(pool_size)
        )
        return BandwidthSelection(
            selected_index=outcome.index,
            mode=outcome.mode,
            weights=neutral_weights,
            bandwidth_effective=effective_bandwidth,
            max_bonus=0.0,
            weights_applied=False,
        )

    # Legacy-uniform (balanced/balanced) and contextual-weighted (light/deep
    # etc.) paths both run momentum weighting; balanced bandwidth contributes
    # a neutral 1.0 bandwidth factor, so those draws stay identical to the
    # existing momentum behavior on main.
    threads = [_resolve_pool_row(bounded_rows[i]) for i in range(pool_size)]

    momentum_breakdowns = [
        compute_momentum_breakdown(
            thread=thread,
            session_events=list(session_events),
            last_rating=thread.last_rating,
            now=now,
        )
        for thread in threads
    ]
    momentum_weights = [breakdown.weight for breakdown in momentum_breakdowns]

    # Effort estimation is only needed when a bandwidth factor can actually
    # bias the draw. Balanced bandwidth contributes a neutral 1.0 factor for
    # every candidate regardless of effort, so we skip the per-candidate
    # effort queries on the common balanced/default path. Unknown effort is
    # exactly neutral for light/deep as well (build_candidate_weights treats a
    # missing estimate as weight 1.0).
    if effective_bandwidth in ("light", "deep"):
        effort_pairs: list[tuple[int, float | None]] = []
        for thread in threads:
            estimate = await compute_effort_estimate(
                db,
                user_id=user_id,
                thread_id=thread.id,
                issue_id=thread.next_unread_issue_id,
            )
            effort_pairs.append((thread.id, estimate.minutes))
    else:
        effort_pairs = [(thread.id, None) for thread in threads]

    bandwidth_weights: Sequence[WeightedCandidate] = build_candidate_weights(
        effort_pairs,
        effective_bandwidth,
    )

    # Combined weight = momentum_weight * bandwidth_weight. Balanced bandwidth
    # yields a 1.0 bandwidth factor, so combined equals momentum exactly.
    combined: list[float] = []
    weights_applied = False
    for momentum, bw in zip(momentum_weights, bandwidth_weights, strict=False):
        value = momentum * bw.weight
        combined.append(value)
        if abs(value - 1.0) > 1e-9:
            weights_applied = True

    total = sum(combined)
    pick = random.random() * total
    cumulative = 0.0
    selected_index = pool_size - 1
    for index, weight in enumerate(combined):
        cumulative += weight
        if pick < cumulative:
            selected_index = index
            break

    momentum_max_bonus = max((w - 1.0 for w in momentum_weights), default=0.0)

    combined_weights: list[CandidateWeight] = []
    for i, thread in enumerate(threads):
        reasons: list[str] = list(momentum_breakdowns[i].factors)
        # Persist a bandwidth reason code only when the bandwidth factor
        # actually biased this candidate (weight differs from neutral 1.0).
        # Balanced bandwidth and unknown effort are exactly neutral, so they
        # contribute no bandwidth reason, matching what was used in selection.
        if abs(bandwidth_weights[i].weight - 1.0) > 1e-9:
            reasons.extend(bandwidth_weights[i].reasons)
        combined_weights.append(
            CandidateWeight(
                candidate_id=thread.id,
                weight=combined[i],
                factors=tuple(dict.fromkeys(reasons)),
            )
        )

    return BandwidthSelection(
        selected_index=selected_index,
        mode=mode,
        weights=tuple(combined_weights),
        bandwidth_effective=effective_bandwidth,
        max_bonus=momentum_max_bonus,
        weights_applied=weights_applied,
    )
