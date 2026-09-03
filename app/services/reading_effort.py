"""Read-only reading-effort derivation (Phase 1).

This module implements the trustworthy reading-effort pipeline used by the
Phase 1 acceptance regression (issue #1705):

1. Derive roll-to-rating decision latency from *explicitly linked* events
   (``events.source_roll_event_id``), never from event-order heuristics.
2. Classify each duration observation with conservative, centralized,
   documented bounds and explainable reason codes.
3. Aggregate valid observations into robust (median-based) per-issue and
   per-thread effort estimates with sample counts and confidence.
4. Fall back to a coarse ComicVine publication-era prior when observed
   history is missing or too sparse. Observed history always takes
   precedence over the era prior.

This module is strictly observational. Nothing here changes Roll selection
probabilities, session mode, Snooze behavior, queue ordering, or UI. Raw
event history is never rewritten or deleted; filtering happens only in the
derived model.

Recommendation-context snapshot contract
----------------------------------------

Roll events may persist a ``recommendation_context`` JSON payload recording
the effort estimate that existed at decision time.

Version 1:

``{"context_version": 1, "selected_candidate": {...effort fields...}}``

Version 2 (issue #1718):

``{"context_version": 2, "selected_candidate": {...}, "candidate_weights": [...], "selected_weight": ..., "bandwidth": ..., "bandwidth_source": ..., "bandwidth_confidence": ..., "random_bypass": ..., "balanced_neutrality": ...}``

``candidate_weights`` is bounded to the die pool (max 100 entries) and holds
``{"candidate_id": int, "weight": float, "reasons": [str]}`` per bounded
candidate in pool order. Compact bandwidth/effort reason codes (e.g.
``bandwidth_light_favors_low_effort``, ``bandwidth_deep_permits_high_effort``,
``effort_unknown_neutral``) are stored per candidate; the selected
candidate's final weight and active bandwidth/source/confidence are also
captured. Pure-random and balanced legacy paths set ``random_bypass`` and
``balanced_neutrality`` explicitly. Readers must tolerate historical rows
with a NULL/missing payload, missing v2 keys, or unknown versions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Event,
    ExternalIdentity,
    IssueExternalIdentityMapping,
    Thread,
    ThreadExternalSeriesMapping,
)

# --- Centralized, documented thresholds -----------------------------------
#
# Minimum plausible duration for one linked roll -> rate reading. Anything
# shorter is instant-marking noise (rating without actually reading).
MIN_VALID_READ_SECONDS: Final[float] = 60.0
# Maximum plausible duration for one linked roll -> rate reading. Anything
# longer is treated as an abandoned tab or forgotten session, not effort.
MAX_VALID_READ_SECONDS: Final[float] = 6.0 * 60.0 * 60.0
# Documented minimum sample count before an observed estimate is trusted.
# A single observation is a median of one and must not masquerade as a
# trusted estimate; sparse data falls back instead of inventing certainty.
MIN_OBSERVED_SAMPLES: Final[int] = 2

# --- Effort bands (minutes) -------------------------------------------------
#
# Bands mirror the product vocabulary from the parent roadmap: a typical
# read under LIGHT_MAX_MINUTES is "light", at or above DEEP_MIN_MINUTES is
# "deep", everything between is "balanced".
LIGHT_MAX_MINUTES: Final[float] = 12.0
DEEP_MIN_MINUTES: Final[float] = 18.0

# --- Confidence -------------------------------------------------------------
#
# Observed confidence grows slowly with sample count and is capped well
# below certainty. Era priors are deliberately low-confidence.
BASE_OBSERVED_CONFIDENCE: Final[float] = 0.5
CONFIDENCE_PER_EXTRA_SAMPLE: Final[float] = 0.1
MAX_OBSERVED_CONFIDENCE: Final[float] = 0.95
ERA_PRIOR_CONFIDENCE: Final[float] = 0.25
UNKNOWN_CONFIDENCE: Final[float] = 0.0

# --- Publication-era priors -------------------------------------------------
#
# Coarse, documented buckets. Era is a weak fallback only; it never
# overrides observed user-specific effort. Years are inclusive bounds where
# ``None`` means "no bound on that side".
_ERA_PRIOR_MAX_YEAR: Final[int] = 1969
_ERA_PRIOR_MIN_MODERN_YEAR: Final[int] = 2000
ERA_PRIOR_CLASSIC_MINUTES: Final[float] = 10.0
ERA_PRIOR_TRANSITION_MINUTES: Final[float] = 14.0
ERA_PRIOR_MODERN_MINUTES: Final[float] = 17.0

_YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"(19|20)\d{2}")

RECOMMENDATION_CONTEXT_VERSION: Final[int] = 2
RECOMMENDATION_CONTEXT_VERSION_KEY: Final[str] = "context_version"
RECOMMENDATION_CONTEXT_CANDIDATE_KEY: Final[str] = "selected_candidate"
RECOMMENDATION_CONTEXT_CANDIDATE_WEIGHTS_KEY: Final[str] = "candidate_weights"
RECOMMENDATION_CONTEXT_SELECTED_WEIGHT_KEY: Final[str] = "selected_weight"
RECOMMENDATION_CONTEXT_BANDWIDTH_KEY: Final[str] = "bandwidth"
RECOMMENDATION_CONTEXT_BANDWIDTH_SOURCE_KEY: Final[str] = "bandwidth_source"
RECOMMENDATION_CONTEXT_BANDWIDTH_CONFIDENCE_KEY: Final[str] = "bandwidth_confidence"
RECOMMENDATION_CONTEXT_RANDOM_BYPASS_KEY: Final[str] = "random_bypass"
RECOMMENDATION_CONTEXT_BALANCED_NEUTRALITY_KEY: Final[str] = "balanced_neutrality"
RECOMMENDATION_CONTEXT_ALGORITHM_VERSION_KEY: Final[str] = "algorithm_version"
RECOMMENDATION_CONTEXT_CONTROL_MODE_KEY: Final[str] = "control_mode"


class EstimateSource(StrEnum):
    """Where a reading-effort estimate came from, ordered by precedence."""

    OBSERVED_ISSUE = "observed_issue"
    OBSERVED_THREAD = "observed_thread"
    ERA_PRIOR = "era_prior"
    UNKNOWN = "unknown"


class ExclusionReason(StrEnum):
    """Documented reason codes for excluded duration observations."""

    MISSING_LINK = "unlinked"
    NON_POSITIVE = "non_positive"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"


@dataclass(frozen=True)
class DurationObservation:
    """One linked roll -> rate duration observation."""

    roll_event_id: int
    rate_event_id: int
    session_id: int | None
    thread_id: int
    issue_id: int | None
    elapsed_seconds: float | None


@dataclass(frozen=True)
class ClassifiedObservation:
    """A duration observation plus its validity verdict and reason code."""

    observation: DurationObservation
    valid: bool
    reason_code: ExclusionReason | None


@dataclass(frozen=True)
class EffortEstimate:
    """Robust reading-effort estimate with provenance."""

    minutes: float | None
    band: str
    source: EstimateSource
    confidence: float
    sample_count: int


def neutral_estimate() -> EffortEstimate:
    """Return the safe neutral estimate used when nothing can be derived.

    Returns:
        An unknown-source estimate with no minutes and zero confidence.
    """
    return EffortEstimate(
        minutes=None,
        band="unknown",
        source=EstimateSource.UNKNOWN,
        confidence=UNKNOWN_CONFIDENCE,
        sample_count=0,
    )


def classify_observation(elapsed_seconds: float | None) -> tuple[bool, ExclusionReason | None]:
    """Classify one elapsed-duration observation against documented bounds.

    Args:
        elapsed_seconds: Derived roll-to-rate latency in seconds, or None
            when the observation has no usable link/timestamps.

    Returns:
        Tuple of (valid, reason_code). ``reason_code`` is None exactly when
        the observation is valid.
    """
    if elapsed_seconds is None:
        return False, ExclusionReason.MISSING_LINK
    if elapsed_seconds <= 0:
        return False, ExclusionReason.NON_POSITIVE
    if elapsed_seconds < MIN_VALID_READ_SECONDS:
        return False, ExclusionReason.TOO_SHORT
    if elapsed_seconds > MAX_VALID_READ_SECONDS:
        return False, ExclusionReason.TOO_LONG
    return True, None


def median(values: Sequence[float]) -> float | None:
    """Compute the deterministic median of a sequence of values.

    Args:
        values: Numeric values; may be empty.

    Returns:
        The median. For an even count this is the mean of the two middle
        values. Returns None for an empty sequence.
    """
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def observed_confidence(sample_count: int) -> float:
    """Compute documented confidence for an observed estimate.

    Args:
        sample_count: Number of valid observations behind the estimate.

    Returns:
        Confidence in ``[0, MAX_OBSERVED_CONFIDENCE]``.
    """
    if sample_count < MIN_OBSERVED_SAMPLES:
        return UNKNOWN_CONFIDENCE
    extra = sample_count - MIN_OBSERVED_SAMPLES
    return min(
        MAX_OBSERVED_CONFIDENCE,
        BASE_OBSERVED_CONFIDENCE + CONFIDENCE_PER_EXTRA_SAMPLE * extra,
    )


def resolve_effort_band(minutes: float | None) -> str:
    """Map an effort estimate in minutes to its documented band.

    Args:
        minutes: Estimated minutes, or None when unknown.

    Returns:
        One of ``light``, ``balanced``, ``deep``, or ``unknown``.
    """
    if minutes is None:
        return "unknown"
    if minutes < LIGHT_MAX_MINUTES:
        return "light"
    if minutes >= DEEP_MIN_MINUTES:
        return "deep"
    return "balanced"


@dataclass(frozen=True)
class EffortAggregate:
    """Median effort for one grouping with its sample count."""

    minutes: float | None
    sample_count: int


def aggregate_observations(
    observations: Sequence[ClassifiedObservation],
) -> tuple[dict[tuple[int, int], EffortAggregate], dict[int, EffortAggregate]]:
    """Aggregate valid observations into per-issue and per-thread medians.

    Args:
        observations: Classified observations; invalid ones are ignored.

    Returns:
        Tuple of ``(by_issue, by_thread)``. ``by_issue`` is keyed by
        ``(thread_id, issue_id)`` for observations that carry an issue;
        ``by_thread`` is keyed by ``thread_id``.
    """
    by_issue_values: dict[tuple[int, int], list[float]] = {}
    by_thread_values: dict[int, list[float]] = {}
    for classified in observations:
        if not classified.valid:
            continue
        observation = classified.observation
        if observation.elapsed_seconds is None:
            continue
        minutes = observation.elapsed_seconds / 60.0
        by_thread_values.setdefault(observation.thread_id, []).append(minutes)
        if observation.issue_id is not None:
            key = (observation.thread_id, observation.issue_id)
            by_issue_values.setdefault(key, []).append(minutes)

    by_issue = {
        key: EffortAggregate(minutes=median(values), sample_count=len(values))
        for key, values in by_issue_values.items()
    }
    by_thread = {
        thread_id: EffortAggregate(minutes=median(values), sample_count=len(values))
        for thread_id, values in by_thread_values.items()
    }
    return by_issue, by_thread


def publication_year_from_metadata(metadata: dict[str, object] | None) -> int | None:
    """Extract a publication year from confirmed external metadata.

    Args:
        metadata: Provider metadata JSON (e.g. ComicVine ``cover_date`` or
            ``store_date`` fields).

    Returns:
        The first plausible publication year found, or None when the
        metadata is missing or ambiguous.
    """
    if not metadata:
        return None
    for field in ("cover_date", "store_date"):
        value = metadata.get(field)
        if not isinstance(value, str):
            continue
        match = _YEAR_PATTERN.search(value)
        if match:
            return int(match.group(0))
    return None


def era_prior_minutes(publication_year: int | None) -> float | None:
    """Map a publication year to its documented coarse era prior.

    Args:
        publication_year: Confirmed publication year, or None.

    Returns:
        The era prior in minutes, or None when no bucket applies.
    """
    if publication_year is None:
        return None
    if publication_year <= _ERA_PRIOR_MAX_YEAR:
        return ERA_PRIOR_CLASSIC_MINUTES
    if publication_year < _ERA_PRIOR_MIN_MODERN_YEAR:
        return ERA_PRIOR_TRANSITION_MINUTES
    return ERA_PRIOR_MODERN_MINUTES


def resolve_effort_estimate(
    issue_aggregate: EffortAggregate | None,
    thread_aggregate: EffortAggregate | None,
    era_minutes: float | None,
) -> EffortEstimate:
    """Resolve the final estimate with documented precedence.

    Precedence: sufficient observed issue history, then sufficient observed
    thread history, then the publication-era prior, then unknown. Sparse
    history never invents certainty.

    Args:
        issue_aggregate: Median aggregate for the exact issue, if any.
        thread_aggregate: Median aggregate for the thread, if any.
        era_minutes: Era prior in minutes, if a confirmed bucket applied.

    Returns:
        The resolved EffortEstimate.
    """
    if issue_aggregate is not None and issue_aggregate.sample_count >= MIN_OBSERVED_SAMPLES:
        return EffortEstimate(
            minutes=issue_aggregate.minutes,
            band=resolve_effort_band(issue_aggregate.minutes),
            source=EstimateSource.OBSERVED_ISSUE,
            confidence=observed_confidence(issue_aggregate.sample_count),
            sample_count=issue_aggregate.sample_count,
        )
    if thread_aggregate is not None and thread_aggregate.sample_count >= MIN_OBSERVED_SAMPLES:
        return EffortEstimate(
            minutes=thread_aggregate.minutes,
            band=resolve_effort_band(thread_aggregate.minutes),
            source=EstimateSource.OBSERVED_THREAD,
            confidence=observed_confidence(thread_aggregate.sample_count),
            sample_count=thread_aggregate.sample_count,
        )
    if era_minutes is not None:
        return EffortEstimate(
            minutes=era_minutes,
            band=resolve_effort_band(era_minutes),
            source=EstimateSource.ERA_PRIOR,
            confidence=ERA_PRIOR_CONFIDENCE,
            sample_count=0,
        )
    return neutral_estimate()


async def collect_classified_observations(
    db: AsyncSession, user_id: int
) -> list[ClassifiedObservation]:
    """Collect linked roll -> rate duration observations for one user.

    Only explicitly linked pairs (``events.source_roll_event_id``) are
    considered. Legacy unlinked rate events are tolerated and simply never
    produce observations; links are never fabricated.

    Args:
        db: Async database session.
        user_id: Owner of the reading history.

    Returns:
        Classified observations in deterministic (rate id) order.
    """
    roll_event = aliased(Event)
    stmt = (
        select(roll_event, Event)
        .join(roll_event, Event.source_roll_event_id == roll_event.id)
        .join(Thread, Event.thread_id == Thread.id)
        .where(Event.type == "rate")
        .where(roll_event.type == "roll")
        .where(roll_event.selected_thread_id == Event.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Event.id)
    )
    result = await db.execute(stmt)
    rows = result.all()

    observations: list[ClassifiedObservation] = []
    for roll_row, rate_row in rows:
        roll_timestamp: datetime | None = roll_row.timestamp
        rate_timestamp: datetime | None = rate_row.timestamp
        elapsed: float | None = None
        if roll_timestamp is not None and rate_timestamp is not None:
            elapsed = (rate_timestamp - roll_timestamp).total_seconds()
        observation = DurationObservation(
            roll_event_id=roll_row.id,
            rate_event_id=rate_row.id,
            session_id=rate_row.session_id,
            thread_id=rate_row.thread_id if rate_row.thread_id is not None else -1,
            issue_id=rate_row.issue_id,
            elapsed_seconds=elapsed,
        )
        valid, reason = classify_observation(observation.elapsed_seconds)
        observations.append(ClassifiedObservation(observation, valid, reason))
    return observations


async def resolve_publication_year(
    db: AsyncSession, *, thread_id: int, issue_id: int | None
) -> int | None:
    """Resolve a publication year from confirmed external identity metadata.

    Prefers the confirmed ComicVine identity for the exact issue, then falls
    back to a confirmed series identity for the thread. Ambiguous or missing
    metadata resolves to None rather than guessing.

    Args:
        db: Async database session.
        thread_id: Thread whose series metadata may be consulted.
        issue_id: Exact issue to prefer, if known.

    Returns:
        Publication year, or None when no confirmed metadata exists.
    """
    if issue_id is not None:
        result = await db.execute(
            select(ExternalIdentity.metadata_json)
            .join(
                IssueExternalIdentityMapping,
                IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
            )
            .where(IssueExternalIdentityMapping.issue_id == issue_id)
            .where(IssueExternalIdentityMapping.status == "confirmed")
            .order_by(IssueExternalIdentityMapping.id)
        )
        for (metadata_json,) in result.all():
            year = publication_year_from_metadata(
                metadata_json if isinstance(metadata_json, dict) else None
            )
            if year is not None:
                return year

    result = await db.execute(
        select(ExternalIdentity.metadata_json)
        .join(
            ThreadExternalSeriesMapping,
            ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(ThreadExternalSeriesMapping.thread_id == thread_id)
        .where(ThreadExternalSeriesMapping.status == "confirmed")
        .order_by(ThreadExternalSeriesMapping.id)
    )
    for (metadata_json,) in result.all():
        year = publication_year_from_metadata(
            metadata_json if isinstance(metadata_json, dict) else None
        )
        if year is not None:
            return year
    return None


async def compute_effort_estimate(
    db: AsyncSession, *, user_id: int, thread_id: int, issue_id: int | None
) -> EffortEstimate:
    """Compute the reading-effort estimate for one candidate read.

    Read-only. Combines observed history (issue first, then thread) with the
    publication-era fallback using documented precedence.

    Args:
        db: Async database session.
        user_id: Owner of the reading history.
        thread_id: Candidate thread.
        issue_id: Candidate next unread issue, if tracked.

    Returns:
        The resolved EffortEstimate; never raises for missing data.
    """
    observations = await collect_classified_observations(db, user_id)
    by_issue, by_thread = aggregate_observations(observations)
    issue_aggregate = by_issue.get((thread_id, issue_id)) if issue_id is not None else None
    thread_aggregate = by_thread.get(thread_id)
    publication_year = await resolve_publication_year(db, thread_id=thread_id, issue_id=issue_id)
    era_minutes = era_prior_minutes(publication_year)
    return resolve_effort_estimate(issue_aggregate, thread_aggregate, era_minutes)


def build_recommendation_context(
    estimate: EffortEstimate,
    *,
    thread_id: int,
    issue_id: int | None,
    issue_number: str | None,
    candidate_weights: Sequence[dict[str, object]] | None = None,
    bandwidth: str | None = None,
    bandwidth_source: str | None = None,
    bandwidth_confidence: float | None = None,
    random_bypass: bool | None = None,
    balanced_neutrality: bool | None = None,
    selected_weight: float | None = None,
    algorithm_version: str | None = None,
    control_mode: str | None = None,
) -> dict[str, object]:
    """Build the versioned decision-time recommendation-context payload.

    Version 2 extends the original selected-candidate snapshot so every
    contextually weighted roll can be explained from persisted decision-time
    data alone:

    - ``candidate_weights``: bounded per-candidate list aligned to the die pool
      (``candidate_id``, final ``weight``, compact bandwidth/effort ``reasons``)
      in pool order. Payload is bounded to the die pool; no full metadata is
      dumped.
    - ``selected_weight``: final chooser weight of the selected candidate.
    - ``bandwidth``/``bandwidth_source``/``bandwidth_confidence``: active
      bandwidth state at decision time.
    - ``random_bypass``/``balanced_neutrality``: explicit flags for
      pure-random and legacy control paths.

    Older ``context_version: 1`` payloads remain readable: readers must treat
    absent v2 keys as neutral/unknown.

    Args:
        estimate: The resolved effort estimate for the selected candidate.
        thread_id: Selected thread id.
        issue_id: Selected next unread issue id, if any.
        issue_number: Selected issue number, if any.
        candidate_weights: Bounded per-candidate weight breakdown in pool order,
            or None when unavailable (e.g. historical rows).
        bandwidth: Active bandwidth label at decision time.
        bandwidth_source: How bandwidth was determined.
        bandwidth_confidence: Confidence in bandwidth.
        random_bypass: Whether contextual weighting was bypassed.
        balanced_neutrality: Whether the draw was explicitly neutral.
        selected_weight: Final weight of the selected candidate.
        algorithm_version: Canonical algorithm version identifier at decision time.
        control_mode: Active control mode (``contextual`` or ``legacy``) at decision time.

    Returns:
        JSON-serializable context dict tagged with
        ``RECOMMENDATION_CONTEXT_VERSION`` (currently 2).
    """
    candidate: dict[str, object] = {
        "thread_id": thread_id,
        "issue_id": issue_id,
        "issue_number": issue_number,
        "effort_minutes": round(estimate.minutes, 2) if estimate.minutes is not None else None,
        "effort_band": estimate.band,
        "effort_source": estimate.source.value,
        "effort_confidence": round(estimate.confidence, 3),
        "effort_sample_count": estimate.sample_count,
    }
    payload: dict[str, object] = {
        RECOMMENDATION_CONTEXT_VERSION_KEY: RECOMMENDATION_CONTEXT_VERSION,
        RECOMMENDATION_CONTEXT_CANDIDATE_KEY: candidate,
    }
    # Version 2 extensions are always present on new writes so every roll can
    # be explained from persisted context alone. Absent values are written as
    # explicit None/bool rather than omitted, keeping the shape stable.
    if candidate_weights is not None:
        # Defensive copy and bounded-size guarantee: callers already bound to
        # die pool; we slice to 100 as an extra guard against payload growth.
        bounded = list(candidate_weights)[:100]
        payload[RECOMMENDATION_CONTEXT_CANDIDATE_WEIGHTS_KEY] = bounded
    else:
        payload[RECOMMENDATION_CONTEXT_CANDIDATE_WEIGHTS_KEY] = None
    if selected_weight is not None:
        payload[RECOMMENDATION_CONTEXT_SELECTED_WEIGHT_KEY] = round(float(selected_weight), 4)
    else:
        payload[RECOMMENDATION_CONTEXT_SELECTED_WEIGHT_KEY] = None
    payload[RECOMMENDATION_CONTEXT_BANDWIDTH_KEY] = bandwidth
    payload[RECOMMENDATION_CONTEXT_BANDWIDTH_SOURCE_KEY] = bandwidth_source
    if bandwidth_confidence is not None:
        payload[RECOMMENDATION_CONTEXT_BANDWIDTH_CONFIDENCE_KEY] = round(
            float(bandwidth_confidence), 3
        )
    else:
        payload[RECOMMENDATION_CONTEXT_BANDWIDTH_CONFIDENCE_KEY] = None
    payload[RECOMMENDATION_CONTEXT_RANDOM_BYPASS_KEY] = bool(random_bypass)
    payload[RECOMMENDATION_CONTEXT_BALANCED_NEUTRALITY_KEY] = bool(balanced_neutrality)
    payload[RECOMMENDATION_CONTEXT_ALGORITHM_VERSION_KEY] = algorithm_version
    payload[RECOMMENDATION_CONTEXT_CONTROL_MODE_KEY] = control_mode
    return payload
