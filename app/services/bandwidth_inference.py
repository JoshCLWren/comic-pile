"""Pure bandwidth inference from comparable historical reading decisions.

Predicts ``light | balanced | deep`` with confidence from a reader's own
historical behavior.  The service is a pure function: no database access,
no I/O, no side effects.  Input is a list of historical observations
capturing accepted reading effort, snooze behavior, and session time-of-day.

Time of day is treated as a weak prior, not a hard rule.  Minimum evidence
thresholds prevent overconfident predictions from sparse history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.constants import BandwidthLevel


# ---------------------------------------------------------------------------
# Configuration constants — centralized and explainable
# ---------------------------------------------------------------------------

# Effort band boundaries in minutes.  Readings at or below LIGHT_MAX are
# classified as light; above DEEP_MIN as deep; the rest are balanced.
LIGHT_MAX_MINUTES: float = 10.0
DEEP_MIN_MINUTES: float = 20.0

# Minimum observations needed for a non-neutral prediction.
MIN_EFFORT_OBSERVATIONS: int = 3

# Confidence scaling: a perfectly aligned set of observations yields this
# confidence.  Confidence scales linearly with the fraction of observations
# supporting the predicted band, then attenuated by evidence sufficiency.
MAX_CONFIDENCE: float = 0.95

# Time-of-day prior weights — weak signal applied before effort evidence.
TIME_OF_DAY_PRIOR: dict[str, float] = {
    "morning": -0.10,  # mornings slightly favor lighter reads
    "afternoon": 0.00,  # neutral
    "evening": 0.05,  # evenings slightly favor deeper reads
    "night": 0.10,  # nights slightly favor deeper reads
}


class Daypart(StrEnum):
    """Time-of-day classification for session-local timestamps."""

    MORNING = "morning"  # 06:00 – 11:59
    AFTERNOON = "afternoon"  # 12:00 – 17:59
    EVENING = "evening"  # 18:00 – 22:59
    NIGHT = "night"  # 23:00 – 05:59


# ---------------------------------------------------------------------------
# Input / output data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HistoricalObservation:
    """One accepted reading decision from the reader's history.

    Attributes:
        effort_minutes: Estimated reading time in minutes for the accepted
            comic.  Derived from roll-to-rating decision latency in Phase 1.
        was_snoozed: Whether this comic was snoozed *before* being accepted
            (i.e., the reader initially deferred it).  ``True`` means the
            reader found it too heavy at first encounter.
        session_hour: Hour of the day (0-23) when the session started.
            Used as a weak prior.
        rating: Optional rating the reader gave after reading (1-5 scale).
            Higher ratings for heavy comics suggest comfort with depth.
    """

    effort_minutes: float
    was_snoozed: bool = False
    session_hour: int | None = None
    rating: float | None = None


@dataclass(frozen=True, slots=True)
class BandwidthEvidence:
    """Transparent reasoning behind a bandwidth prediction.

    Exposed for tests and future human-readable explanations.  Every field
    is informational — the prediction itself is in ``BandwidthPrediction``.

    Attributes:
        effort_observations: Number of effort observations used.
        mean_effort: Mean effort in minutes across observations.
        median_effort: Median effort in minutes across observations.
        light_fraction: Fraction of observations classified as light effort.
        deep_fraction: Fraction of observations classified as deep effort.
        snooze_rate: Fraction of observations that were snoozed before
            acceptance.
        snooze_heavy_rate: Fraction of snoozed observations that had deep
            effort — strong signal for bandwidth avoidance.
        daypart: Inferred daypart of the current session (if hour provided).
        daypart_prior: Numeric prior applied for the detected daypart.
        alignment_score: Fraction of observations whose effort band matches
            the predicted level.
        evidence_sufficiency: 0.0-1.0 score measuring how much evidence
            supports a non-neutral prediction.  Below 1.0 when evidence is
            sparse or contradictory.
        reasons: Ordered list of human-readable reason strings.
    """

    effort_observations: int = 0
    mean_effort: float = 0.0
    median_effort: float = 0.0
    light_fraction: float = 0.0
    deep_fraction: float = 0.0
    snooze_rate: float = 0.0
    snooze_heavy_rate: float = 0.0
    daypart: str | None = None
    daypart_prior: float = 0.0
    alignment_score: float = 0.0
    evidence_sufficiency: float = 0.0
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BandwidthPrediction:
    """Result of bandwidth inference.

    Attributes:
        level: Predicted bandwidth level.
        confidence: 0.0-1.0 confidence in the prediction.  Low confidence
            when evidence is sparse, contradictory, or neutral.
        source: Always ``"inferred"`` for this pure service.
        evidence: Transparent reasoning behind the prediction.
    """

    level: BandwidthLevel
    confidence: float
    source: str = "inferred"
    evidence: BandwidthEvidence = field(default_factory=BandwidthEvidence)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_effort(effort_minutes: float) -> BandwidthLevel:
    """Classify a single effort observation into a bandwidth band.

    Args:
        effort_minutes: Reading time in minutes.

    Returns:
        The effort band for this observation.
    """
    if effort_minutes <= LIGHT_MAX_MINUTES:
        return BandwidthLevel.LIGHT
    if effort_minutes >= DEEP_MIN_MINUTES:
        return BandwidthLevel.DEEP
    return BandwidthLevel.BALANCED


def _daypart_from_hour(hour: int) -> Daypart:
    """Map an hour (0-23) to a daypart.

    Args:
        hour: Hour of the day.

    Returns:
        The daypart classification.
    """
    if 6 <= hour <= 11:
        return Daypart.MORNING
    if 12 <= hour <= 17:
        return Daypart.AFTERNOON
    if 18 <= hour <= 22:
        return Daypart.EVENING
    return Daypart.NIGHT


def _median(values: list[float]) -> float:
    """Compute the median of a non-empty list.

    Args:
        values: Non-empty list of floats.

    Returns:
        The median value.
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


# ---------------------------------------------------------------------------
# Core inference
# ---------------------------------------------------------------------------


def infer_bandwidth(
    observations: tuple[HistoricalObservation, ...] | list[HistoricalObservation],
    *,
    session_hour: int | None = None,
) -> BandwidthPrediction:
    """Predict session bandwidth from comparable historical reading decisions.

    This is a pure function — no I/O, no database access.  For fixed input
    it always returns the same result.

    Args:
        observations: Historical reading decisions for the user.  Each
            observation should capture accepted reading effort, snooze
            behavior, and optionally session time-of-day.
        session_hour: Hour of the current session (0-23).  Used as a weak
            prior.  When ``None``, the time-of-day prior is omitted.

    Returns:
        A ``BandwidthPrediction`` with level, confidence, and evidence.
    """
    reasons: list[str] = []

    # --- insufficient history → safe neutral default ---
    effort_obs = [o for o in observations if o.effort_minutes > 0]
    if len(effort_obs) < MIN_EFFORT_OBSERVATIONS:
        reasons.append(
            f"Insufficient effort observations ({len(effort_obs)}/{MIN_EFFORT_OBSERVATIONS})"
        )
        evidence = BandwidthEvidence(
            effort_observations=len(effort_obs),
            reasons=tuple(reasons),
        )
        return BandwidthPrediction(
            level=BandwidthLevel.BALANCED,
            confidence=0.1,
            evidence=evidence,
        )

    # --- compute effort statistics ---
    effort_values = [o.effort_minutes for o in effort_obs]
    mean_effort = sum(effort_values) / len(effort_values)
    median_effort = _median(effort_values)

    effort_bands = [_classify_effort(e) for e in effort_values]
    light_count = effort_bands.count(BandwidthLevel.LIGHT)
    deep_count = effort_bands.count(BandwidthLevel.DEEP)
    balanced_count = effort_bands.count(BandwidthLevel.BALANCED)
    total = len(effort_bands)

    light_fraction = light_count / total
    deep_fraction = deep_count / total
    balanced_fraction = balanced_count / total

    reasons.append(
        f"Effort distribution: {light_count} light, {balanced_count} balanced, "
        f"{deep_count} deep out of {total} observations"
    )
    reasons.append(f"Mean effort: {mean_effort:.1f}m, median: {median_effort:.1f}m")

    # --- snooze analysis ---
    snooze_count = sum(1 for o in observations if o.was_snoozed)
    snooze_rate = snooze_count / len(observations) if observations else 0.0

    deep_snooze_count = sum(
        1 for o in observations if o.was_snoozed and o.effort_minutes >= DEEP_MIN_MINUTES
    )
    snooze_heavy_rate = deep_snooze_count / snooze_count if snooze_count > 0 else 0.0

    if snooze_count > 0:
        reasons.append(
            f"Snooze rate: {snooze_rate:.0%} ({snooze_count}/{len(observations)}), "
            f"heavy snooze rate: {snooze_heavy_rate:.0%}"
        )

    # --- time-of-day prior ---
    daypart_prior = 0.0
    daypart_label: str | None = None
    if session_hour is not None:
        daypart = _daypart_from_hour(session_hour)
        daypart_label = daypart.value
        daypart_prior = TIME_OF_DAY_PRIOR.get(daypart.value, 0.0)
        reasons.append(f"Daypart: {daypart_label}, prior: {daypart_prior:+.2f}")

    # --- compute raw scores for each band ---
    # Score each band by alignment with observed effort distribution,
    # modified by snooze patterns and time-of-day prior.
    raw_scores: dict[BandwidthLevel, float] = {}
    for level in BandwidthLevel:
        alignment = {
            BandwidthLevel.LIGHT: light_fraction,
            BandwidthLevel.BALANCED: balanced_fraction,
            BandwidthLevel.DEEP: deep_fraction,
        }[level]
        raw_scores[level] = alignment

    # Snooze penalty: snoozing heavy comics suggests the reader avoids deep
    # when overloaded.  Reduce deep score proportionally.
    if snooze_heavy_rate > 0:
        deep_penalty = snooze_heavy_rate * 0.3
        raw_scores[BandwidthLevel.DEEP] = max(0.0, raw_scores[BandwidthLevel.DEEP] - deep_penalty)
        reasons.append(f"Deep snooze penalty: -{deep_penalty:.3f}")

    # Time-of-day prior: shift scores by a small amount.
    if daypart_prior != 0.0:
        raw_scores[BandwidthLevel.LIGHT] += -abs(daypart_prior)
        raw_scores[BandwidthLevel.DEEP] += abs(daypart_prior)
        reasons.append(f"Daypart prior applied: {daypart_prior:+.2f}")

    # --- pick the winning band ---
    predicted_level = max(raw_scores, key=lambda lvl: raw_scores[lvl])
    top_score = raw_scores[predicted_level]
    tied_levels = {lvl for lvl, score in raw_scores.items() if abs(score - top_score) < 1e-9}
    light_deep_tie = {BandwidthLevel.LIGHT, BandwidthLevel.DEEP} <= tied_levels
    if light_deep_tie:
        # When light and deep evidence tie, neither extreme has support over
        # the other; the safe midpoint is the balanced prediction. Record the
        # contradiction explicitly so future explanations can show why.
        predicted_level = BandwidthLevel.BALANCED
        reasons.append(
            "Contradictory light/deep evidence tied; returning balanced as the safe midpoint"
        )

    # --- alignment score ---
    alignment_score = {
        BandwidthLevel.LIGHT: light_fraction,
        BandwidthLevel.BALANCED: balanced_fraction,
        BandwidthLevel.DEEP: deep_fraction,
    }[predicted_level]

    # --- evidence sufficiency ---
    # Scales from 0 to 1 based on how many observations we have relative to
    # the minimum threshold, capped at 1.0 once we have enough evidence.
    evidence_sufficiency = min(1.0, len(effort_obs) / (MIN_EFFORT_OBSERVATIONS * 2))

    # --- confidence ---
    # Base confidence is alignment_score scaled by evidence sufficiency.
    # Contradictory evidence (low alignment) reduces confidence further.
    base_confidence = alignment_score * evidence_sufficiency

    # Apply time-of-day prior as a small boost or reduction
    prior_boost = abs(daypart_prior) * 0.2 if daypart_prior != 0.0 else 0.0

    confidence = min(MAX_CONFIDENCE, base_confidence + prior_boost)

    # --- contradictions reduce confidence ---
    # If no single band has > 40% of observations, evidence is contradictory.
    max_fraction = max(light_fraction, balanced_fraction, deep_fraction)
    if max_fraction < 0.40:
        confidence *= 0.6
        reasons.append(
            f"Contradictory evidence (max band fraction {max_fraction:.0%}), confidence reduced"
        )
    elif light_deep_tie:
        # Genuinely contradictory: equal light and deep support with no
        # dominant band. Confidence is already low (balanced aligns with no
        # effort band); reduce it further to reflect the indecision.
        confidence *= 0.6
        reasons.append(
            "Contradictory light/deep evidence; confidence reduced to reflect indecision"
        )

    # --- build reason strings for the predicted level ---
    if predicted_level == BandwidthLevel.LIGHT:
        reasons.append(f"Predicted LIGHT: {light_fraction:.0%} of observations are light effort")
    elif predicted_level == BandwidthLevel.DEEP:
        reasons.append(f"Predicted DEEP: {deep_fraction:.0%} of observations are deep effort")
    else:
        reasons.append(
            f"Predicted BALANCED: no dominant effort band "
            f"(light={light_fraction:.0%}, deep={deep_fraction:.0%})"
        )

    confidence = round(confidence, 4)

    evidence = BandwidthEvidence(
        effort_observations=len(effort_obs),
        mean_effort=round(mean_effort, 2),
        median_effort=round(median_effort, 2),
        light_fraction=round(light_fraction, 4),
        deep_fraction=round(deep_fraction, 4),
        snooze_rate=round(snooze_rate, 4),
        snooze_heavy_rate=round(snooze_heavy_rate, 4),
        daypart=daypart_label,
        daypart_prior=round(daypart_prior, 4),
        alignment_score=round(alignment_score, 4),
        evidence_sufficiency=round(evidence_sufficiency, 4),
        reasons=tuple(reasons),
    )

    return BandwidthPrediction(
        level=predicted_level,
        confidence=confidence,
        evidence=evidence,
    )
