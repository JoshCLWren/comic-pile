"""Bounded combination of bandwidth and intent factors for Roll candidates.

Phase 8 of the personalized-Roll architecture (#1685, ticket #1761): the
session's bandwidth and exactly one active intent compose into one transparent
per-candidate weight inside the existing bounded die pool. The dice model stays
central - contextual factors only reweight candidates that are already
eligible, never expand or shrink the pool.

Product rules implemented here:

- ``bandwidth`` (light/balanced/deep) aligns or misaligns candidates by their
  estimated reading effort; unknown effort is exactly neutral.
- Exactly ONE intent factor is active per roll. ``balanced`` contributes an
  exactly neutral factor with no hidden bias; ``momentum``, ``familiar``, and
  ``explore`` each apply their own bounded bonus; ``random`` is an explicit
  contextual bypass that reproduces legacy uniform selection.
- Every per-factor cap and the final-weight floor/ceiling are defined once,
  centrally, in this module. Combination multiplies the two factors a single
  time and clamps the product; no composition can escape the caps.
- Taste/metadata effects aggregate additively under one deliberate aggregate
  cap, so many correlated metadata matches can never multiply into runaway
  scores and can never overpower die-pool eligibility.
- Each candidate keeps its reason/factor breakdown so every selection remains
  explainable after the fact.

This module is deliberately dependency-free (standard library only) so every
factor, cap, breakdown, bypass, and selection rule can be unit tested without
a database or application imports.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

# --- Session context labels ---------------------------------------------------

BANDWIDTH_LIGHT: Final[str] = "light"
BANDWIDTH_BALANCED: Final[str] = "balanced"
BANDWIDTH_DEEP: Final[str] = "deep"
ALL_BANDWIDTHS: Final[frozenset[str]] = frozenset(
    {BANDWIDTH_LIGHT, BANDWIDTH_BALANCED, BANDWIDTH_DEEP}
)

INTENT_BALANCED: Final[str] = "balanced"
INTENT_MOMENTUM: Final[str] = "momentum"
INTENT_FAMILIAR: Final[str] = "familiar"
INTENT_EXPLORE: Final[str] = "explore"
INTENT_RANDOM: Final[str] = "random"
ALL_INTENTS: Final[frozenset[str]] = frozenset(
    {INTENT_BALANCED, INTENT_MOMENTUM, INTENT_FAMILIAR, INTENT_EXPLORE, INTENT_RANDOM}
)

# --- Central caps ---------------------------------------------------------------
# All caps live here so no call site can quietly loosen them.

# Bandwidth deviations from neutral are capped at this absolute amount.
BANDWIDTH_DEVIATION_CAP: Final[float] = 0.15

# Per-intent multiplicative caps (factor values, not bonuses).
MOMENTUM_FACTOR_CAP: Final[float] = 1.5
FAMILIAR_FACTOR_CAP: Final[float] = 1.35
EXPLORE_FACTOR_CAP: Final[float] = 1.25

# Deliberate aggregate ceiling on total taste bonus within the Familiar intent.
# Correlated metadata matches stack additively up to here and then stop, so
# metadata volume can never multiply into runaway scores.
FAMILIAR_AGGREGATE_BONUS_CAP: Final[float] = FAMILIAR_FACTOR_CAP - 1.0

# Final combined weight is clamped into [floor, cap] centrally.
FINAL_WEIGHT_FLOOR: Final[float] = 0.5
FINAL_WEIGHT_CAP: Final[float] = 1.75

# --- Effort bands (minutes) -------------------------------------------------------

EFFORT_LIGHT_MAX_MINUTES: Final[float] = 12.0
EFFORT_MEDIUM_MAX_MINUTES: Final[float] = 18.0

EFFORT_BAND_LIGHT: Final[str] = "light"
EFFORT_BAND_MEDIUM: Final[str] = "medium"
EFFORT_BAND_HEAVY: Final[str] = "heavy"

# Raw alignment table: how well each bandwidth pairs with each effort band.
# Values above 1.0 align with the session, below 1.0 misalign. Deviations are
# clamped to BANDWIDTH_DEVIATION_CAP before use.
_BANDWIDTH_EFFORT_ALIGNMENT: Final[Mapping[tuple[str, str], float]] = {
    (BANDWIDTH_LIGHT, EFFORT_BAND_LIGHT): 1.10,
    (BANDWIDTH_LIGHT, EFFORT_BAND_MEDIUM): 1.00,
    (BANDWIDTH_LIGHT, EFFORT_BAND_HEAVY): 0.85,
    (BANDWIDTH_BALANCED, EFFORT_BAND_LIGHT): 1.00,
    (BANDWIDTH_BALANCED, EFFORT_BAND_MEDIUM): 1.00,
    (BANDWIDTH_BALANCED, EFFORT_BAND_HEAVY): 1.00,
    (BANDWIDTH_DEEP, EFFORT_BAND_LIGHT): 0.90,
    (BANDWIDTH_DEEP, EFFORT_BAND_MEDIUM): 1.00,
    (BANDWIDTH_DEEP, EFFORT_BAND_HEAVY): 1.10,
}

# --- Momentum tuning -----------------------------------------------------------------

MOMENTUM_RECENCY_DECAY_HALF_LIFE_DAYS: Final[float] = 14.0
MOMENTUM_STALENESS_DAYS: Final[float] = 45.0
MOMENTUM_BASE_BONUS: Final[float] = 0.25
MOMENTUM_MIN_POSITIVE_RATING: Final[float] = 3.5
MOMENTUM_HIGH_RATING_THRESHOLD: Final[float] = 4.0
MOMENTUM_STREAK_BONUS_PER_READ: Final[float] = 0.05
MOMENTUM_STREAK_MAX_READS: Final[int] = 4

# --- Familiar (Taste Bank) tuning ------------------------------------------------------

VERDICT_CONFIRMED: Final[str] = "confirmed"
VERDICT_SOMETIMES: Final[str] = "sometimes"
VERDICT_INFERRED: Final[str] = "inferred"
VERDICT_REJECTED: Final[str] = "rejected"

TASTE_CATEGORY_CREATOR: Final[str] = "creator"
TASTE_CATEGORY_CHARACTER: Final[str] = "character"
TASTE_CATEGORY_TEAM: Final[str] = "team"
TASTE_CATEGORY_PUBLISHER: Final[str] = "publisher"
TASTE_CATEGORY_ERA: Final[str] = "era"
TASTE_CATEGORIES: Final[tuple[str, ...]] = (
    TASTE_CATEGORY_CREATOR,
    TASTE_CATEGORY_CHARACTER,
    TASTE_CATEGORY_TEAM,
    TASTE_CATEGORY_PUBLISHER,
    TASTE_CATEGORY_ERA,
)

# Verdict weights are additive bonus contributions. Explicit verdicts are the
# authority: inferred evidence never boosts, rejected evidence never boosts.
_VERDICT_BONUS: Final[Mapping[str, float]] = {
    VERDICT_CONFIRMED: 0.15,
    VERDICT_SOMETIMES: 0.075,
    VERDICT_INFERRED: 0.0,
    VERDICT_REJECTED: 0.0,
}

# --- Explore tuning ---------------------------------------------------------------------

EXPLORE_NOVEL_BONUS: Final[float] = 0.15
EXPLORE_LESS_EXPOSED_BONUS: Final[float] = 0.075
EXPLORE_KNOWN_EXPOSURE_COUNT: Final[int] = 3
EXPLORE_ADJACENCY_BONUS_PER_ANCHOR: Final[float] = 0.05
EXPLORE_ADJACENCY_MAX_ANCHORS: Final[int] = 2

# --- Reason codes -------------------------------------------------------------------------

REASON_BANDWIDTH_ALIGNED: Final[str] = "bandwidth_effort_aligned"
REASON_BANDWIDTH_MISALIGNED: Final[str] = "bandwidth_effort_misaligned"
REASON_EFFORT_UNKNOWN_NEUTRAL: Final[str] = "effort_unknown_neutral"

REASON_INTENT_BALANCED_NEUTRAL: Final[str] = "intent_balanced_neutral"
REASON_RECENT_HIGH_RATING: Final[str] = "recent_high_rating"
REASON_RECENT_MODERATE_READ: Final[str] = "recent_moderate_read"
REASON_HIGH_RATED_STREAK: Final[str] = "high_rated_streak"
REASON_STALE_RUN_DECAY: Final[str] = "stale_run_decay"
REASON_LOW_RATING_NO_BOOST: Final[str] = "low_rating_no_boost"

REASON_TASTE_CONFIRMED: Final[str] = "taste_confirmed"
REASON_TASTE_SOMETIMES: Final[str] = "taste_sometimes"
REASON_TASTE_AGGREGATE_CAPPED: Final[str] = "taste_aggregate_capped"
REASON_TASTE_REJECTED_IGNORED: Final[str] = "taste_rejected_ignored"

REASON_NOVEL_CANDIDATE: Final[str] = "novel_candidate"
REASON_LESS_EXPOSED_CANDIDATE: Final[str] = "less_exposed_candidate"
REASON_KNOWN_CANDIDATE_NEUTRAL: Final[str] = "known_candidate_neutral"
REASON_TASTE_ADJACENT: Final[str] = "taste_adjacent"

REASON_FINAL_WEIGHT_CLAMPED: Final[str] = "final_weight_clamped"
REASON_RANDOM_BYPASS: Final[str] = "random_contextual_bypass"

WEIGHTING_MODE_WEIGHTED: Final[str] = "weighted"
WEIGHTING_MODE_BYPASSED: Final[str] = "bypassed"


@dataclass(frozen=True, slots=True)
class CandidateSignals:
    """Reader-history signals for one candidate inside the bounded die pool.

    All fields are optional evidence; missing evidence fails to neutral rather
    than being scored as maximally good or bad.

    Attributes:
        thread_id: Candidate thread identifier.
        effort_minutes: Estimated reading effort in minutes, when known.
        last_rating: Most recent rating given to this thread, if any.
        days_since_last_read: Age of the most recent read/rate in days, if any.
        high_rated_streak: Count of consecutive most-recent ratings at or above
            ``MOMENTUM_HIGH_RATING_THRESHOLD``.
        matched_verdict_by_category: Strongest Taste Bank verdict matched per
            taste category for this candidate's normalized metadata keys.
        prior_exposure_count: Number of prior completed reads of the thread.
        adjacent_anchor_categories: Confirmed Taste Bank anchor categories
            shared by this candidate's metadata.
    """

    thread_id: int
    effort_minutes: float | None = None
    last_rating: float | None = None
    days_since_last_read: float | None = None
    high_rated_streak: int = 0
    matched_verdict_by_category: Mapping[str, str] = field(default_factory=dict)
    prior_exposure_count: int = 0
    adjacent_anchor_categories: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class WeightedCandidate:
    """Explainable final weight for one candidate.

    Attributes:
        thread_id: Candidate thread identifier.
        final_weight: Combined weight after central caps, as passed to chooser.
        bandwidth_factor: The bandwidth-side factor used.
        intent_factor: The single active intent-side factor used.
        reasons: Stable reason codes explaining both sides and any clamp.
    """

    thread_id: int
    final_weight: float
    bandwidth_factor: float
    intent_factor: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PoolWeighting:
    """Result of contextual weighting for one roll's bounded pool.

    Attributes:
        mode: ``weighted`` when per-candidate weights were produced;
            ``bypassed`` when the random intent explicitly skips context.
        bandwidth: Session bandwidth label used.
        intent: Active intent label used.
        contextual_bypass: True only for the random-intent bypass.
        candidates: Per-candidate weights in pool order; empty when bypassed.
    """

    mode: str
    bandwidth: str
    intent: str
    contextual_bypass: bool
    candidates: tuple[WeightedCandidate, ...]


def _effort_band(effort_minutes: float) -> str:
    """Bucket a known effort estimate into its effort band.

    Args:
        effort_minutes: Estimated reading effort in minutes.

    Returns:
        One of ``light``, ``medium``, ``heavy``.
    """
    if effort_minutes < EFFORT_LIGHT_MAX_MINUTES:
        return EFFORT_BAND_LIGHT
    if effort_minutes <= EFFORT_MEDIUM_MAX_MINUTES:
        return EFFORT_BAND_MEDIUM
    return EFFORT_BAND_HEAVY


def _capped_bonus_factor(bonus: float, cap: float) -> float:
    """Turn a non-negative additive bonus into a factor clamped under ``cap``.

    Args:
        bonus: Non-negative additive bonus above the neutral base.
        cap: Maximum allowed factor value.

    Returns:
        The capped factor rounded to six decimals; neutral on invalid input.
    """
    if not math.isfinite(bonus) or bonus <= 0.0:
        return 1.0
    return round(min(cap, 1.0 + bonus), 6)


def bandwidth_factor(bandwidth: str, effort_minutes: float | None) -> tuple[float, tuple[str, ...]]:
    """Compute the bandwidth-side factor for one candidate.

    Light bandwidth favors light-effort candidates and dampens heavy ones;
    deep bandwidth mirrors it; balanced bandwidth is exactly neutral. Unknown
    effort is exactly neutral for any bandwidth. Deviations are centrally
    capped at ``BANDWIDTH_DEVIATION_CAP``.

    Args:
        bandwidth: One of ``light``, ``balanced``, ``deep``.
        effort_minutes: Candidate reading-effort estimate, when known.

    Returns:
        Tuple of the factor and its stable reason codes.

    Raises:
        ValueError: If the bandwidth label is unrecognized.
    """
    if bandwidth not in ALL_BANDWIDTHS:
        raise ValueError(f"Invalid bandwidth: {bandwidth}")
    if bandwidth == BANDWIDTH_BALANCED:
        return 1.0, ()
    if effort_minutes is None:
        return 1.0, (REASON_EFFORT_UNKNOWN_NEUTRAL,)

    raw_alignment = _BANDWIDTH_EFFORT_ALIGNMENT[(bandwidth, _effort_band(effort_minutes))]
    deviation = min(BANDWIDTH_DEVIATION_CAP, abs(raw_alignment - 1.0))
    factor = round(1.0 + deviation if raw_alignment >= 1.0 else 1.0 - deviation, 6)
    if factor == 1.0:
        return 1.0, ()
    reason = REASON_BANDWIDTH_ALIGNED if factor > 1.0 else REASON_BANDWIDTH_MISALIGNED
    return factor, (reason,)


def momentum_factor(signals: CandidateSignals) -> tuple[float, tuple[str, ...]]:
    """Compute the Momentum intent factor from recent reading behavior.

    Recent reads with positive ratings earn a decaying bonus; higher recent
    ratings strengthen it; consecutive high-rated reads add a small capped
    streak increment. Stale runs and low-rated runs never gain a boost solely
    for recency.

    Args:
        signals: The candidate's reader-history signals.

    Returns:
        Tuple of the factor (never above ``MOMENTUM_FACTOR_CAP``) and reasons.
    """
    if signals.days_since_last_read is None or signals.last_rating is None:
        return 1.0, ()

    effective_days = max(0.0, float(signals.days_since_last_read))
    if effective_days >= MOMENTUM_STALENESS_DAYS:
        return 1.0, (REASON_STALE_RUN_DECAY,)
    decay = 0.5 ** (effective_days / MOMENTUM_RECENCY_DECAY_HALF_LIFE_DAYS)

    rating = float(signals.last_rating)
    if rating < MOMENTUM_MIN_POSITIVE_RATING:
        return 1.0, (REASON_LOW_RATING_NO_BOOST,)

    span = MOMENTUM_HIGH_RATING_THRESHOLD - MOMENTUM_MIN_POSITIVE_RATING
    strength = min(1.0, max(0.0, (rating - MOMENTUM_MIN_POSITIVE_RATING) / span))
    bonus = MOMENTUM_BASE_BONUS * decay * strength

    reasons: list[str] = []
    if rating >= MOMENTUM_HIGH_RATING_THRESHOLD:
        reasons.append(REASON_RECENT_HIGH_RATING)
    else:
        reasons.append(REASON_RECENT_MODERATE_READ)

    streak = max(0, int(signals.high_rated_streak))
    if streak > 0:
        bonus += min(streak, MOMENTUM_STREAK_MAX_READS) * MOMENTUM_STREAK_BONUS_PER_READ * decay
        reasons.append(REASON_HIGH_RATED_STREAK)

    return _capped_bonus_factor(bonus, MOMENTUM_FACTOR_CAP), tuple(reasons)


def familiar_factor(signals: CandidateSignals) -> tuple[float, tuple[str, ...]]:
    """Compute the Familiar intent factor from confirmed Taste Bank matches.

    Matched explicit verdicts contribute additive bonuses (confirmed strongest,
    sometimes half as much). The total taste bonus aggregates under ONE central
    cap (``FAMILIAR_AGGREGATE_BONUS_CAP``), so many correlated metadata matches
    cannot multiply into runaway scores. Rejected signals never boost; missing
    or unconfirmed-only metadata fails to neutral.

    Args:
        signals: The candidate's matched Taste Bank verdicts by category.

    Returns:
        Tuple of the factor (never above ``FAMILIAR_FACTOR_CAP``) and reasons.
    """
    if not signals.matched_verdict_by_category:
        return 1.0, ()

    reasons: list[str] = []
    bonus = 0.0
    for category in TASTE_CATEGORIES:
        verdict = signals.matched_verdict_by_category.get(category)
        if verdict is None:
            continue
        if verdict == VERDICT_REJECTED:
            reasons.append(REASON_TASTE_REJECTED_IGNORED)
            continue
        contribution = _VERDICT_BONUS.get(verdict, 0.0)
        uncapped_bonus = bonus + contribution
        bonus = min(FAMILIAR_AGGREGATE_BONUS_CAP, uncapped_bonus)
        if uncapped_bonus > FAMILIAR_AGGREGATE_BONUS_CAP >= contribution > 0.0:
            reasons.append(REASON_TASTE_AGGREGATE_CAPPED)
        if verdict == VERDICT_CONFIRMED:
            reasons.append(REASON_TASTE_CONFIRMED)
        elif verdict == VERDICT_SOMETIMES:
            reasons.append(REASON_TASTE_SOMETIMES)
        # Inferred contributes no bonus and earns no boost reason.

    if bonus <= 0.0:
        return 1.0, tuple(reasons)

    return _capped_bonus_factor(bonus, FAMILIAR_FACTOR_CAP), tuple(reasons)


def explore_factor(signals: CandidateSignals) -> tuple[float, tuple[str, ...]]:
    """Compute the Explore intent factor from exposure and taste adjacency.

    Unread candidates earn the largest novelty bonus and lightly-exposed ones
    a partial bonus; known candidates stay exactly neutral but fully eligible
    rather than being excluded. A small adjacency bonus applies only while the
    candidate still has genuine novelty and shares confirmed anchors.

    Args:
        signals: The candidate's exposure and anchor signals.

    Returns:
        Tuple of the factor (never above ``EXPLORE_FACTOR_CAP``) and reasons.
    """
    exposure = max(0, int(signals.prior_exposure_count))
    if exposure >= EXPLORE_KNOWN_EXPOSURE_COUNT:
        return 1.0, (REASON_KNOWN_CANDIDATE_NEUTRAL,)

    reasons: list[str] = []
    if exposure <= 0:
        novelty_bonus = EXPLORE_NOVEL_BONUS
        reasons.append(REASON_NOVEL_CANDIDATE)
    else:
        novelty_bonus = EXPLORE_LESS_EXPOSED_BONUS
        reasons.append(REASON_LESS_EXPOSED_CANDIDATE)

    distinct_anchors = {
        category for category in signals.adjacent_anchor_categories if category in TASTE_CATEGORIES
    }
    adjacency_bonus = (
        min(len(distinct_anchors), EXPLORE_ADJACENCY_MAX_ANCHORS)
        * EXPLORE_ADJACENCY_BONUS_PER_ANCHOR
    )
    if adjacency_bonus > 0.0:
        reasons.append(REASON_TASTE_ADJACENT)

    return (
        _capped_bonus_factor(novelty_bonus + adjacency_bonus, EXPLORE_FACTOR_CAP),
        tuple(reasons),
    )


def intent_factor(intent: str, signals: CandidateSignals) -> tuple[float, tuple[str, ...]]:
    """Compute the single active intent-side factor for one candidate.

    Args:
        intent: Active reading intent.
        signals: The candidate's reader-history signals.

    Returns:
        Tuple of the factor and its stable reason codes. Balanced intent is
        exactly neutral with an explicit marker reason.

    Raises:
        ValueError: If the intent is unrecognized or is the random bypass.
    """
    if intent not in ALL_INTENTS:
        raise ValueError(f"Invalid intent: {intent}")
    if intent == INTENT_BALANCED:
        return 1.0, (REASON_INTENT_BALANCED_NEUTRAL,)
    if intent == INTENT_MOMENTUM:
        return momentum_factor(signals)
    if intent == INTENT_FAMILIAR:
        return familiar_factor(signals)
    if intent == INTENT_EXPLORE:
        return explore_factor(signals)
    raise ValueError("Random intent has no per-candidate intent factor")


def combine_factors(
    thread_id: int,
    bandwidth_part: float,
    intent_part: float,
    reasons: Sequence[str],
) -> WeightedCandidate:
    """Combine the two factors into one centrally-capped candidate weight.

    The bandwidth factor and the single active intent factor are multiplied
    exactly once and the product is clamped into
    ``[FINAL_WEIGHT_FLOOR, FINAL_WEIGHT_CAP]``. A clamp appends an explicit
    reason code so post-hoc audits can see when a bound engaged.

    Args:
        thread_id: Candidate thread identifier.
        bandwidth_part: Already-capped bandwidth-side factor.
        intent_part: Already-capped intent-side factor.
        reasons: Reason codes accumulated from both sides.

    Returns:
        The candidate's explainable final weight breakdown.

    Raises:
        ValueError: If either factor is not finite or not positive.
    """
    for name, value in (("bandwidth", bandwidth_part), ("intent", intent_part)):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} factor must be finite and positive, got {value}")

    combined = bandwidth_part * intent_part
    all_reasons = list(reasons)
    if combined > FINAL_WEIGHT_CAP:
        combined = FINAL_WEIGHT_CAP
        all_reasons.append(REASON_FINAL_WEIGHT_CLAMPED)
    elif combined < FINAL_WEIGHT_FLOOR:
        combined = FINAL_WEIGHT_FLOOR
        all_reasons.append(REASON_FINAL_WEIGHT_CLAMPED)

    return WeightedCandidate(
        thread_id=thread_id,
        final_weight=round(combined, 6),
        bandwidth_factor=round(bandwidth_part, 6),
        intent_factor=round(intent_part, 6),
        reasons=tuple(all_reasons),
    )


def weight_candidate(bandwidth: str, intent: str, signals: CandidateSignals) -> WeightedCandidate:
    """Compute one candidate's full weighted breakdown.

    Args:
        bandwidth: Session bandwidth label.
        intent: Active intent label (not ``random``).
        signals: The candidate's reader-history signals.

    Returns:
        The candidate's final capped weight with its reason/factor breakdown.

    Raises:
        ValueError: If bandwidth or intent is invalid, or intent is ``random``.
    """
    if intent == INTENT_RANDOM:
        raise ValueError("Random intent bypasses contextual weighting")
    bandwidth_part, bandwidth_reasons = bandwidth_factor(bandwidth, signals.effort_minutes)
    intent_part, intent_reasons = intent_factor(intent, signals)
    return combine_factors(
        signals.thread_id,
        bandwidth_part,
        intent_part,
        (*bandwidth_reasons, *intent_reasons),
    )


def weight_pool(
    bandwidth: str,
    intent: str,
    signals: Sequence[CandidateSignals],
) -> PoolWeighting:
    """Weight every candidate in the bounded pool, or bypass explicitly.

    Args:
        bandwidth: Session bandwidth label.
        intent: Active intent label; ``random`` triggers the explicit bypass.
        signals: Signals for each candidate in the bounded die pool, in pool
            order.

    Returns:
        A ``PoolWeighting`` whose candidate order mirrors the input order.
        Random intent returns a bypass record with no per-candidate weights so
        callers reproduce legacy uniform selection exactly.

    Raises:
        ValueError: If bandwidth or intent is invalid.
    """
    if bandwidth not in ALL_BANDWIDTHS:
        raise ValueError(f"Invalid bandwidth: {bandwidth}")
    if intent not in ALL_INTENTS:
        raise ValueError(f"Invalid intent: {intent}")

    if intent == INTENT_RANDOM:
        return PoolWeighting(
            mode=WEIGHTING_MODE_BYPASSED,
            bandwidth=bandwidth,
            intent=intent,
            contextual_bypass=True,
            candidates=(),
        )

    weighted = tuple(weight_candidate(bandwidth, intent, item) for item in signals)
    return PoolWeighting(
        mode=WEIGHTING_MODE_WEIGHTED,
        bandwidth=bandwidth,
        intent=intent,
        contextual_bypass=False,
        candidates=weighted,
    )


def select_candidate_index(pool_size: int, weighting: PoolWeighting, rng: random.Random) -> int:
    """Select one index inside the bounded pool using the prepared weighting.

    Weighted mode performs roulette selection over per-candidate weights, which
    are guaranteed positive by the central floor, so no candidate is ever fully
    excluded from eligibility. Bypassed mode reproduces legacy uniform
    selection exactly.

    Args:
        pool_size: Number of candidates in the bounded die pool.
        weighting: Weighting produced by :func:`weight_pool` for this roll.
        rng: Random source; injectable for deterministic tests.

    Returns:
        Selected index into the pool order.

    Raises:
        ValueError: If the pool is empty or inconsistent with the weighting.
    """
    if pool_size <= 0:
        raise ValueError("Cannot select from an empty pool")

    if weighting.contextual_bypass:
        if weighting.candidates:
            raise ValueError("Bypassed weighting must carry no per-candidate weights")
        return rng.randrange(pool_size)

    if len(weighting.candidates) != pool_size:
        raise ValueError(
            f"Weighting covers {len(weighting.candidates)} candidates but pool has {pool_size}"
        )

    weights = [candidate.final_weight for candidate in weighting.candidates]
    total = sum(weights)
    threshold = rng.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if threshold < cumulative:
            return index
    return pool_size - 1
