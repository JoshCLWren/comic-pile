"""Pure intent-weighted recommendation factor calculation.

Phase 8 of the personalized-Roll architecture (#1685): Momentum, Familiar,
and Explore intents alter only contextual ranking inside the existing bounded
die pool. This module is deliberately dependency-free (standard library only)
so every factor, cap, bypass, and persisted-context rule can be unit tested
without a database or application imports.

Product rules implemented here:

- ``momentum`` favors recent high-rated reading runs and decays with
  staleness; low-rated recent runs never receive a positive boost solely for
  being recent.
- ``familiar`` favors confirmed/qualified Taste Bank matches using stable
  normalized keys; rejected signals never boost and missing metadata fails to
  neutral.
- ``explore`` favors novel-but-adjacent candidates without excluding known
  favorites; unknown metadata stays eligible and neutral.
- ``balanced`` contributes exactly neutral weight.
- ``random`` is an explicit contextual bypass that reproduces legacy uniform
  selection inside the bounded die pool.
- Bandwidth and intent combine multiplicatively within centrally documented
  caps; no combination can escape them.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

RECOMMENDATION_CONTEXT_VERSION: Final[int] = 2

INTENT_BALANCED: Final[str] = "balanced"
INTENT_MOMENTUM: Final[str] = "momentum"
INTENT_FAMILIAR: Final[str] = "familiar"
INTENT_EXPLORE: Final[str] = "explore"
INTENT_RANDOM: Final[str] = "random"

ALL_INTENTS: Final[frozenset[str]] = frozenset(
    {
        INTENT_BALANCED,
        INTENT_MOMENTUM,
        INTENT_FAMILIAR,
        INTENT_EXPLORE,
        INTENT_RANDOM,
    }
)

ACTIVE_INTENTS: Final[frozenset[str]] = frozenset(
    {INTENT_MOMENTUM, INTENT_FAMILIAR, INTENT_EXPLORE}
)

BANDWIDTH_LIGHT: Final[str] = "light"
BANDWIDTH_BALANCED: Final[str] = "balanced"
BANDWIDTH_DEEP: Final[str] = "deep"
ALL_BANDWIDTHS: Final[frozenset[str]] = frozenset(
    {BANDWIDTH_LIGHT, BANDWIDTH_BALANCED, BANDWIDTH_DEEP}
)

VERDICT_CONFIRMED: Final[str] = "confirmed"
VERDICT_SOMETIMES: Final[str] = "sometimes"
VERDICT_INFERRED: Final[str] = "inferred"
VERDICT_REJECTED: Final[str] = "rejected"
ALL_VERDICTS: Final[frozenset[str]] = frozenset(
    {VERDICT_CONFIRMED, VERDICT_SOMETIMES, VERDICT_INFERRED, VERDICT_REJECTED}
)

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

MOMENTUM_FACTOR_CAP: Final[float] = 1.5
FAMILIAR_FACTOR_CAP: Final[float] = 1.35
EXPLORE_FACTOR_CAP: Final[float] = 1.25
PER_FACTOR_CAP: Final[float] = 1.5
BANDWIDTH_DEVIATION_CAP: Final[float] = 0.15
FINAL_WEIGHT_CAP: Final[float] = 1.75
FINAL_WEIGHT_FLOOR: Final[float] = 0.5

MOMENTUM_RECENCY_DECAY_HALF_LIFE_DAYS: Final[float] = 14.0
MOMENTUM_STALENESS_DAYS: Final[float] = 45.0
MOMENTUM_FRESH_RUN_DAYS: Final[float] = 7.0
MOMENTUM_RATING_THRESHOLD: Final[float] = 4.0
MOMENTUM_MIN_POSITIVE_RATING: Final[float] = 3.5
MOMENTUM_BASE_BONUS: Final[float] = 0.25
MOMENTUM_STREAK_BONUS_PER_READ: Final[float] = 0.05
MOMENTUM_STREAK_MAX_READS: Final[int] = 4

FAMILIAR_CONFIRMED_WEIGHT: Final[float] = 0.15
FAMILIAR_SOMETIMES_WEIGHT: Final[float] = 0.075
FAMILIAR_INFERRED_WEIGHT: Final[float] = 0.0

EXPLORE_NOVEL_BONUS: Final[float] = 0.15
EXPLORE_LESS_EXPOSED_BONUS: Final[float] = 0.075
EXPLORE_FAMILIAR_EXPOSURE_COUNT: Final[int] = 3
EXPLORE_ADJACENCY_BONUS_PER_ANCHOR: Final[float] = 0.05
EXPLORE_ADJACENCY_MAX_ANCHORS: Final[int] = 2

EFFORT_LIGHT_MAX_MINUTES: Final[float] = 12.0
EFFORT_MEDIUM_MAX_MINUTES: Final[float] = 18.0

EFFORT_BAND_LIGHT: Final[str] = "light"
EFFORT_BAND_MEDIUM: Final[str] = "medium"
EFFORT_BAND_HEAVY: Final[str] = "heavy"

BANDWIDTH_FACTORS: Final[Mapping[tuple[str, str], float]] = {
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

VERDICT_STRENGTH: Final[Mapping[str, int]] = {
    VERDICT_REJECTED: 0,
    VERDICT_INFERRED: 1,
    VERDICT_SOMETIMES: 2,
    VERDICT_CONFIRMED: 3,
}

VERDICT_WEIGHTS: Final[Mapping[str, float]] = {
    VERDICT_CONFIRMED: FAMILIAR_CONFIRMED_WEIGHT,
    VERDICT_SOMETIMES: FAMILIAR_SOMETIMES_WEIGHT,
    VERDICT_INFERRED: FAMILIAR_INFERRED_WEIGHT,
    VERDICT_REJECTED: 0.0,
}

WEIGHTING_MODE_WEIGHTED: Final[str] = "weighted"
WEIGHTING_MODE_BYPASSED: Final[str] = "bypassed"

REASON_RECENT_HIGH_RATING: Final[str] = "recent_high_rating"
REASON_SAME_THREAD_MOMENTUM: Final[str] = "same_thread_momentum"
REASON_HIGH_RATED_STREAK: Final[str] = "high_rated_streak"
REASON_STALE_RUN_DECAY: Final[str] = "stale_run_decay"
REASON_LOW_RATING_NO_BOOST: Final[str] = "low_rating_no_boost"
REASON_NOVEL_CANDIDATE: Final[str] = "novel_candidate"
REASON_LESS_EXPOSED_CANDIDATE: Final[str] = "less_exposed_candidate"
REASON_KNOWN_FAVORITE: Final[str] = "known_favorite"
REASON_TASTE_ADJACENT: Final[str] = "taste_adjacent"
REASON_REJECTED_SIGNAL_IGNORED: Final[str] = "rejected_signal_ignored"
REASON_BANDWIDTH_EFFORT_ALIGNED: Final[str] = "bandwidth_effort_aligned"
REASON_BANDWIDTH_EFFORT_MISALIGNED: Final[str] = "bandwidth_effort_misaligned"
REASON_EFFORT_UNKNOWN_NEUTRAL: Final[str] = "effort_unknown_neutral"
REASON_INTENT_BALANCED_NEUTRAL: Final[str] = "intent_balanced_neutral"
REASON_INTENT_RANDOM_BYPASS: Final[str] = "intent_random_bypass"


@dataclass(frozen=True, slots=True)
class CandidateContext:
    """Reader-history signals for one candidate inside the bounded die pool.

    Attributes:
        thread_id: Candidate thread identifier.
        effort_minutes: Estimated reading effort in minutes, when known.
        last_rating: Most recent rating given to this thread, if any.
        days_since_last_read: Age of the most recent read/rate, in days.
        recent_avg_rating: Mean of the most recent few ratings, if any.
        high_rated_streak: Count of consecutive most-recent ratings at or
            above ``MOMENTUM_RATING_THRESHOLD``.
        matched_verdict_by_category: Strongest Taste Bank verdict matched per
            taste category for this candidate's normalized metadata keys.
        prior_exposure_count: Number of prior completed reads of the thread.
        adjacent_confirmed_categories: Confirmed Taste Bank anchor categories
            shared by this candidate's metadata.
    """

    thread_id: int
    effort_minutes: float | None = None
    last_rating: float | None = None
    days_since_last_read: float | None = None
    recent_avg_rating: float | None = None
    high_rated_streak: int = 0
    matched_verdict_by_category: Mapping[str, str] = field(default_factory=dict)
    prior_exposure_count: int = 0
    adjacent_confirmed_categories: Collection[str] = ()


@dataclass(frozen=True, slots=True)
class CandidateWeight:
    """Final explainable weight for one candidate.

    Attributes:
        thread_id: Candidate thread identifier.
        final_weight: Combined weight after caps, as passed to the chooser.
        bandwidth_factor: The bandwidth-side factor used.
        intent_factor: The intent-side factor used.
        reasons: Stable compact reason codes explaining the factors.
    """

    thread_id: int
    final_weight: float
    bandwidth_factor: float
    intent_factor: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextualWeighting:
    """Result of contextual weighting for one roll.

    Attributes:
        mode: ``weighted`` when per-candidate weights were produced;
            ``bypassed`` when the intent explicitly skips context.
        intent: Active intent label.
        bandwidth: Active bandwidth label.
        contextual_bypass: True only for the random-intent bypass.
        candidates: Per-candidate weights; empty when bypassed.
    """

    mode: str
    intent: str
    bandwidth: str
    contextual_bypass: bool
    candidates: tuple[CandidateWeight, ...]


def normalize_taste_key(value: str) -> str:
    """Normalize one metadata value into a stable taste key fragment.

    Args:
        value: Raw provider or user-entered metadata value.

    Returns:
        Lowercased, whitespace-collapsed key with stray punctuation removed.
    """
    collapsed = " ".join(value.split()).lower()
    return "".join(ch for ch in collapsed if ch.isalnum() or ch == " ").strip()


def era_decade_key(year: int) -> str:
    """Return the stable decade-era key for a publication year.

    Args:
        year: Publication year, e.g. ``1994``.

    Returns:
        Decade bucket key such as ``era-1990s``.
    """
    decade = (int(year) // 10) * 10
    return f"era-{decade}s"


def strongest_verdict(verdicts: Iterable[str]) -> str | None:
    """Return the strongest verdict among non-empty input.

    Args:
        verdicts: Verdict values from ``ALL_VERDICTS``.

    Returns:
        The verdict with the highest strength, or ``None`` when empty.
    """
    present = [v for v in verdicts if v in ALL_VERDICTS]
    if not present:
        return None
    return max(present, key=lambda v: VERDICT_STRENGTH[v])


def _recency_decay(days: float) -> float:
    """Compute exponential recency decay between 0 and 1."""
    effective_days = max(0.0, days)
    if effective_days >= MOMENTUM_STALENESS_DAYS:
        return 0.0
    return 0.5 ** (effective_days / MOMENTUM_RECENCY_DECAY_HALF_LIFE_DAYS)


def _rating_strength(rating: float) -> float:
    """Scale a rating into a 0..1 strength between the momentum thresholds."""
    span = MOMENTUM_RATING_THRESHOLD - MOMENTUM_MIN_POSITIVE_RATING
    if span <= 0:
        return 1.0
    return min(1.0, max(0.0, (rating - MOMENTUM_MIN_POSITIVE_RATING) / span))


def _clamp_factor(factor: float, cap: float) -> float:
    """Clamp a multiplicative factor into ``[1/cap, cap]`` then ``[1, cap]``."""
    clamped = min(cap, max(1.0, factor))
    if not math.isfinite(clamped):
        return 1.0
    return round(clamped, 6)


def bandwidth_factor(
    bandwidth: str, effort_minutes: float | None
) -> tuple[float, tuple[str, ...]]:
    """Compute the bandwidth-side contextual factor for one candidate.

    Args:
        bandwidth: One of ``light``, ``balanced``, ``deep``.
        effort_minutes: Candidate reading-effort estimate, when known.

    Returns:
        Tuple of the factor and its stable reason codes. Balanced bandwidth
        and unknown effort both fail to exact neutrality.
    """
    if bandwidth not in ALL_BANDWIDTHS:
        raise ValueError(f"Invalid bandwidth: {bandwidth}")
    if bandwidth == BANDWIDTH_BALANCED or effort_minutes is None:
        reasons: tuple[str, ...] = ()
        if bandwidth != BANDWIDTH_BALANCED:
            reasons = (REASON_EFFORT_UNKNOWN_NEUTRAL,)
        return 1.0, reasons

    if effort_minutes < EFFORT_LIGHT_MAX_MINUTES:
        effort_band = EFFORT_BAND_LIGHT
    elif effort_minutes <= EFFORT_MEDIUM_MAX_MINUTES:
        effort_band = EFFORT_BAND_MEDIUM
    else:
        effort_band = EFFORT_BAND_HEAVY

    raw = BANDWIDTH_FACTORS[(bandwidth, effort_band)]
    deviation = min(BANDWIDTH_DEVIATION_CAP, abs(raw - 1.0))
    factor = 1.0 + deviation if raw >= 1.0 else 1.0 - deviation
    reason = (
        REASON_BANDWIDTH_EFFORT_ALIGNED
        if factor > 1.0
        else REASON_BANDWIDTH_EFFORT_MISALIGNED
    )
    return factor, (reason,) if factor != 1.0 else ()


def momentum_factor(context: CandidateContext) -> tuple[float, tuple[str, ...]]:
    """Compute the Momentum intent factor for one candidate.

    Recent high-rated runs are boosted, bonuses decay exponentially with
    staleness, streak depth adds a small capped increment, and low-rated runs
    never gain a boost solely for recency.

    Args:
        context: The candidate's reader-history signals.

    Returns:
        Tuple of the factor and its stable reason codes.
    """
    evidence_rating: float | None = None
    if context.last_rating is not None:
        evidence_rating = float(context.last_rating)
    if context.recent_avg_rating is not None:
        evidence_rating = (
            float(context.recent_avg_rating)
            if evidence_rating is None
            else max(evidence_rating, float(context.recent_avg_rating))
        )

    if context.days_since_last_read is None or evidence_rating is None:
        return 1.0, ()

    decay = _recency_decay(float(context.days_since_last_read))
    if decay <= 0.0:
        return 1.0, (REASON_STALE_RUN_DECAY,)

    strength = _rating_strength(evidence_rating)
    if strength <= 0.0:
        return 1.0, (REASON_LOW_RATING_NO_BOOST,)

    reasons: list[str] = []
    bonus = MOMENTUM_BASE_BONUS * decay * strength

    if evidence_rating >= MOMENTUM_RATING_THRESHOLD:
        reasons.append(REASON_RECENT_HIGH_RATING)
    else:
        reasons.append(REASON_SAME_THREAD_MOMENTUM)

    streak = max(0, int(context.high_rated_streak))
    if streak > 0:
        bonus += (
            min(streak, MOMENTUM_STREAK_MAX_READS) * MOMENTUM_STREAK_BONUS_PER_READ * decay
        )
        reasons.append(REASON_HIGH_RATED_STREAK)

    factor = _clamp_factor(1.0 + bonus, MOMENTUM_FACTOR_CAP)
    return factor, tuple(reasons)


def familiar_factor(context: CandidateContext) -> tuple[float, tuple[str, ...]]:
    """Compute the Familiar intent factor for one candidate.

    Confirmed Taste Bank matches weigh most, qualified ``sometimes`` matches
    half as much, unconfirmed inferred signals contribute nothing, and
    rejected signals never boost. Effects aggregate additively under one cap
    so correlated metadata cannot run away.

    Args:
        context: The candidate's matched Taste Bank verdicts by category.

    Returns:
        Tuple of the factor and its stable reason codes.
    """
    if not context.matched_verdict_by_category:
        return 1.0, ()

    reasons: list[str] = []
    bonus = 0.0
    for category in TASTE_CATEGORIES:
        verdict = context.matched_verdict_by_category.get(category)
        if verdict is None:
            continue
        if verdict == VERDICT_REJECTED:
            reasons.append(REASON_REJECTED_SIGNAL_IGNORED)
            continue
        bonus += VERDICT_WEIGHTS[verdict]
        if verdict == VERDICT_CONFIRMED:
            reasons.append(f"{VERDICT_CONFIRMED}_{category}")
        elif verdict == VERDICT_SOMETIMES:
            reasons.append(f"{VERDICT_SOMETIMES}_{category}")
        else:
            reasons.append(f"{VERDICT_INFERRED}_{category}")

    if bonus <= 0.0:
        return 1.0, tuple(reasons)

    factor = _clamp_factor(1.0 + min(bonus, FAMILIAR_FACTOR_CAP - 1.0), FAMILIAR_FACTOR_CAP)
    return factor, tuple(reasons)


def explore_factor(context: CandidateContext) -> tuple[float, tuple[str, ...]]:
    """Compute the Explore intent factor for one candidate.

    Unread candidates earn the largest novelty bonus, lightly-exposed
    candidates earn a partial bonus, and known favorites stay exactly neutral
    rather than being excluded. A small adjacency bonus applies only when the
    candidate has genuine novelty and shares confirmed Taste Bank anchors.

    Args:
        context: The candidate's exposure and adjacency signals.

    Returns:
        Tuple of the factor and its stable reason codes.
    """
    exposure = max(0, int(context.prior_exposure_count))
    novelty_bonus = 0.0
    reasons: list[str] = []

    if exposure <= 0:
        novelty_bonus = EXPLORE_NOVEL_BONUS
        reasons.append(REASON_NOVEL_CANDIDATE)
    elif exposure < EXPLORE_FAMILIAR_EXPOSURE_COUNT:
        novelty_bonus = EXPLORE_LESS_EXPOSED_BONUS
        reasons.append(REASON_LESS_EXPOSED_CANDIDATE)
    else:
        reasons.append(REASON_KNOWN_FAVORITE)
        return 1.0, tuple(reasons)

    distinct_anchors = {
        category
        for category in context.adjacent_confirmed_categories
        if category in TASTE_CATEGORIES
    }
    adjacency_bonus = (
        min(len(distinct_anchors), EXPLORE_ADJACENCY_MAX_ANCHORS)
        * EXPLORE_ADJACENCY_BONUS_PER_ANCHOR
    )
    if adjacency_bonus > 0.0:
        reasons.append(REASON_TASTE_ADJACENT)

    factor = _clamp_factor(
        1.0 + min(novelty_bonus + adjacency_bonus, EXPLORE_FACTOR_CAP - 1.0),
        EXPLORE_FACTOR_CAP,
    )
    return factor, tuple(reasons)


def intent_factor(intent: str, context: CandidateContext) -> tuple[float, tuple[str, ...]]:
    """Compute the single active intent-side factor for one candidate.

    Args:
        intent: Active reading intent.
        context: The candidate's signals.

    Returns:
        Tuple of the factor and its stable reason codes. Balanced intent is
        exactly neutral.

    Raises:
        ValueError: If the intent is not a recognized value.
    """
    if intent not in ALL_INTENTS:
        raise ValueError(f"Invalid intent: {intent}")
    if intent == INTENT_BALANCED:
        return 1.0, (REASON_INTENT_BALANCED_NEUTRAL,)
    if intent == INTENT_MOMENTUM:
        return momentum_factor(context)
    if intent == INTENT_FAMILIAR:
        return familiar_factor(context)
    if intent == INTENT_EXPLORE:
        return explore_factor(context)
    raise ValueError("Random intent has no per-candidate intent factor")


def compute_candidate_weight(
    bandwidth: str, intent: str, context: CandidateContext
) -> CandidateWeight:
    """Combine bandwidth and intent into one capped explainable weight.

    Args:
        bandwidth: Session bandwidth label.
        intent: Session intent label.
        context: The candidate's signals.

    Returns:
        The candidate's final weight plus the exact factors and reasons used.

    Raises:
        ValueError: If bandwidth or intent is invalid.
    """
    if intent not in ALL_INTENTS:
        raise ValueError(f"Invalid intent: {intent}")
    if intent == INTENT_RANDOM:
        raise ValueError("Random intent bypasses contextual weighting")

    bandwidth_part, bandwidth_reasons = bandwidth_factor(bandwidth, context.effort_minutes)
    intent_part, intent_reasons = intent_factor(intent, context)
    combined = bandwidth_part * intent_part
    final = round(min(FINAL_WEIGHT_CAP, max(FINAL_WEIGHT_FLOOR, combined)), 6)
    return CandidateWeight(
        thread_id=context.thread_id,
        final_weight=final,
        bandwidth_factor=round(bandwidth_part, 6),
        intent_factor=round(intent_part, 6),
        reasons=tuple((*bandwidth_reasons, *intent_reasons)),
    )


def compute_contextual_weights(
    bandwidth: str, intent: str, contexts: Sequence[CandidateContext]
) -> ContextualWeighting:
    """Weight every candidate inside the bounded pool, or bypass explicitly.

    Args:
        bandwidth: Session bandwidth label.
        intent: Session intent label.
        contexts: Signals for each candidate in the bounded die pool.

    Returns:
        A ``ContextualWeighting`` whose candidate order mirrors the input
        order. Random intent returns an explicit bypass record with no
        per-candidate weights.

    Raises:
        ValueError: If bandwidth or intent is invalid.
    """
    if bandwidth not in ALL_BANDWIDTHS:
        raise ValueError(f"Invalid bandwidth: {bandwidth}")
    if intent not in ALL_INTENTS:
        raise ValueError(f"Invalid intent: {intent}")

    if intent == INTENT_RANDOM:
        return ContextualWeighting(
            mode=WEIGHTING_MODE_BYPASSED,
            intent=intent,
            bandwidth=bandwidth,
            contextual_bypass=True,
            candidates=(),
        )

    weighted = tuple(compute_candidate_weight(bandwidth, intent, ctx) for ctx in contexts)
    return ContextualWeighting(
        mode=WEIGHTING_MODE_WEIGHTED,
        intent=intent,
        bandwidth=bandwidth,
        contextual_bypass=False,
        candidates=weighted,
    )


def choose_candidate(weights: Sequence[float], rng: random.Random) -> int:
    """Select an index by weighted roulette among the given candidates only.

    Args:
        weights: Positive per-candidate weights; order mirrors the pool.
        rng: Seeded or system RNG used for the draw.

    Returns:
        The selected index, guaranteed to be inside the provided bounds.
    """
    count = len(weights)
    if count == 0:
        raise ValueError("Cannot choose from an empty candidate list")
    total = sum(weights)
    if total <= 0:
        return rng.randrange(count)
    threshold = rng.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if threshold < cumulative:
            return index
    return count - 1


def build_recommendation_context(
    *,
    bandwidth: str,
    intent: str,
    intent_source: str,
    intent_confidence: float,
    die_size: int,
    weighting: ContextualWeighting,
    selected_thread_id: int | None,
) -> dict[str, object]:
    """Serialize the exact recommendation context used for one roll.

    Args:
        bandwidth: Session bandwidth label used at decision time.
        intent: Session intent used at decision time.
        intent_source: Where the intent came from (e.g. ``request``).
        intent_confidence: Confidence attached to the active intent.
        die_size: Die size bounding the candidate pool.
        weighting: The weighting result produced for this roll.
        selected_thread_id: Thread actually returned to the reader.

    Returns:
        JSON-ready dict carrying the schema version, active mode, explicit
        bypass/neutrality markers, and the compact per-candidate breakdown.
        Stored weights equal the weights passed to the chooser.
    """
    payload: dict[str, object] = {
        "schema_version": RECOMMENDATION_CONTEXT_VERSION,
        "bandwidth": bandwidth,
        "intent": weighting.intent,
        "intent_source": intent_source,
        "intent_confidence": round(float(intent_confidence), 6),
        "contextual_bypass": weighting.contextual_bypass,
        "mode": weighting.mode,
        "die_size": int(die_size),
        "selected_thread_id": selected_thread_id,
    }
    if weighting.contextual_bypass:
        payload["bypass_reason"] = REASON_INTENT_RANDOM_BYPASS
        payload["candidates"] = []
        return payload

    payload["candidates"] = [
        {
            "thread_id": candidate.thread_id,
            "final_weight": candidate.final_weight,
            "bandwidth_factor": candidate.bandwidth_factor,
            "intent_factor": candidate.intent_factor,
            "reasons": list(candidate.reasons),
        }
        for candidate in weighting.candidates
    ]
    return payload


def context_to_json(context: dict[str, object]) -> str:
    """Render a persisted recommendation context deterministically.

    Args:
        context: Payload built by :func:`build_recommendation_context`.

    Returns:
        Deterministic JSON string suitable for storage and diffing.
    """
    return json.dumps(context, sort_keys=True, separators=(",", ":"))
