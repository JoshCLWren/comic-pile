"""Taste Bank inference: derive cautious taste signals from reading history.

Compares feature-level reading behavior against the user's own baseline
rating behavior and produces inferred affinity and confidence suitable for
deciding whether a pattern is worth prompting the user about.

Explicit user verdicts (confirmed, sometimes, rejected) are never overwritten
by recalculation. Rejected signals are never re-inferred as confirmed.

Implements the acceptance criteria from issue #1745:
- Strong repeated above-baseline evidence creates/updates inferred signals.
- One or two isolated issues remain low-confidence.
- Evidence diversity increases confidence relative to a single-run cluster.
- Rejected/confirmed/sometimes verdicts survive recomputation.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models.taste_evidence import TasteEvidence
from app.models.taste_signal import TasteSignal
from app.services.comicvine_taste_features import extract_taste_features

logger = logging.getLogger(__name__)

MAX_BASELINE_EVENTS = 200
MIN_EVIDENCE_FOR_INFERENCE = 1
MIN_CONFIDENCE_TO_PERSIST = 0.05
INFERRED_AFFINITY_CAP = 0.95


@dataclass(frozen=True, slots=True)
class _FeatureObservationGroup:
    """Aggregated observations for one (user, signal_type, external_key) pair.

    Attributes:
        signal_type: Category of the taste feature.
        stable_key: Normalized stable identifier for the feature.
        display_name: Human-readable name for UI display.
        role: For creator features, the primary role when available.
        ratings: Observed rating values in chronological order.
        thread_ids: Thread that produced each observation.
        session_ids: Reading session that produced each observation.
        event_ids: Rating event behind each observation.
        issue_ids: Rated issue behind each observation.
        observed_ats: Event timestamps in chronological order.
    """

    signal_type: str
    stable_key: str
    display_name: str
    role: str | None
    ratings: tuple[float, ...] = field(default_factory=tuple)
    thread_ids: tuple[int, ...] = field(default_factory=tuple)
    session_ids: tuple[int | None, ...] = field(default_factory=tuple)
    event_ids: tuple[int, ...] = field(default_factory=tuple)
    issue_ids: tuple[int, ...] = field(default_factory=tuple)
    observed_ats: tuple[datetime, ...] = field(default_factory=tuple)

    @property
    def evidence_count(self) -> int:
        """Total number of observations backing this group."""
        return len(self.ratings)

    @property
    def distinct_threads_count(self) -> int:
        """Number of distinct threads contributing evidence."""
        return len(set(self.thread_ids))

    @property
    def distinct_runs_count(self) -> int:
        """Number of distinct reading sessions contributing evidence."""
        return len({sid for sid in self.session_ids if sid is not None})

    @property
    def feature_mean_rating(self) -> float:
        """Mean rating across all observations for this feature."""
        if not self.ratings:
            return 0.0
        return sum(self.ratings) / len(self.ratings)


def _compute_baseline_stats(ratings: Sequence[float]) -> tuple[float, float]:
    """Compute baseline mean and standard deviation from user rating history.

    Args:
        ratings: Sequence of all observed ratings for the user.

    Returns:
        (baseline_mean, baseline_std) tuple. Returns (0.0, 1.0) when fewer
        than 2 ratings are available.
    """
    if not ratings:
        return 0.0, 1.0

    n = len(ratings)
    mean = sum(ratings) / n

    if n < 2:
        return mean, 1.0

    variance = sum((r - mean) ** 2 for r in ratings) / n
    std = variance**0.5

    if std < 0.01:
        return mean, 1.0

    return mean, std


async def _fetch_user_rated_event_rows(
    db: AsyncSession,
    user_id: int,
    limit: int = MAX_BASELINE_EVENTS,
) -> list[dict[str, object]]:
    """Fetch the most recent rating events with their threading context.

    Events are ordered chronologically ascending in the returned list so the
    final observation carries the latest timestamp.

    Args:
        db: Async database session.
        user_id: User whose rating events to fetch.
        limit: Maximum number of events to fetch for baseline calculation.

    Returns:
        List of dicts with keys: event_id, rating, thread_id, issue_id,
        session_id, timestamp.
    """
    result = await db.execute(
        select(
            Event.id,
            Event.rating,
            Event.thread_id,
            Event.issue_id,
            Event.session_id,
            Event.timestamp,
        )
        .join(Thread, Thread.id == Event.thread_id)
        .where(
            Thread.user_id == user_id,
            Event.type == "rate",
            Event.rating.is_not(None),
        )
        .order_by(Event.timestamp.desc())
        .limit(limit)
    )

    rows: list[dict[str, object]] = []
    for row in result.mappings():
        issue_id = row["issue_id"]
        session_id = row["session_id"]
        rows.append(
            {
                "event_id": int(row["id"]),
                "rating": float(row["rating"]),
                "thread_id": int(row["thread_id"]),
                "issue_id": int(issue_id) if issue_id is not None else None,
                "session_id": int(session_id) if session_id is not None else None,
                "timestamp": row["timestamp"],
            }
        )
    rows.reverse()
    return rows


async def _fetch_confirmed_identity_metadata(
    db: AsyncSession,
    issue_ids: Sequence[int],
) -> dict[int, dict[str, object]]:
    """Fetch confirmed ComicVine metadata for a list of issue IDs.

    Args:
        db: Async database session.
        issue_ids: Issue IDs to look up confirmed ComicVine identities for.

    Returns:
        Map of issue_id -> metadata_json dict for issues with confirmed
        ComicVine mappings. Issues without confirmed mappings are omitted.
    """
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

    if not issue_ids:
        return {}

    result = await db.execute(
        select(
            IssueExternalIdentityMapping.issue_id,
            ExternalIdentity.metadata_json,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(
            IssueExternalIdentityMapping.issue_id.in_(issue_ids),
            IssueExternalIdentityMapping.status == "confirmed",
            ExternalIdentity.provider == "comicvine",
        )
    )

    metadata_map: dict[int, dict[str, object]] = {}
    for row in result.mappings():
        issue_id = int(row["issue_id"])
        metadata = row["metadata_json"]
        if isinstance(metadata, dict):
            metadata_map[issue_id] = metadata
    return metadata_map


async def _fetch_existing_taste_signals(
    db: AsyncSession,
    user_id: int,
) -> dict[tuple[str, str], TasteSignal]:
    """Fetch all existing taste signals for a user.

    Args:
        db: Async database session.
        user_id: User whose signals to fetch.

    Returns:
        Map of (signal_type, external_key) -> TasteSignal.
    """
    result = await db.execute(select(TasteSignal).where(TasteSignal.user_id == user_id))
    signals: dict[tuple[str, str], TasteSignal] = {}
    for signal in result.scalars():
        signals[(signal.signal_type, signal.external_key)] = signal
    return signals


def _group_observations(
    user_id: int,
    event_rows: Sequence[dict[str, object]],
    metadata_map: dict[int, dict[str, object]],
) -> dict[tuple[str, str], _FeatureObservationGroup]:
    """Group rating events by taste feature key.

    For each rated issue with confirmed ComicVine metadata, extracts taste
    features and associates the rating with each feature.

    Args:
        user_id: User ID for the observations.
        event_rows: Raw event rows from _fetch_user_rated_event_rows.
        metadata_map: Map of issue_id -> metadata_json.

    Returns:
        Map of (signal_type, stable_key) -> _FeatureObservationGroup.
    """
    groups: dict[tuple[str, str], _FeatureObservationGroup] = {}

    for row in event_rows:
        raw_issue_id = row["issue_id"]
        if not isinstance(raw_issue_id, int) or raw_issue_id not in metadata_map:
            continue

        features = extract_taste_features(metadata_map[raw_issue_id])
        if not features:
            continue

        rating = float(row["rating"])
        thread_id = int(row["thread_id"])
        raw_session_id = row["session_id"]
        session_id = int(raw_session_id) if isinstance(raw_session_id, int) else None
        event_id = int(row["event_id"])
        timestamp = row["timestamp"]

        for feature in features:
            key = (feature.signal_type, feature.stable_key)
            group = groups.get(key)
            if group is None:
                groups[key] = _FeatureObservationGroup(
                    signal_type=feature.signal_type,
                    stable_key=feature.stable_key,
                    display_name=feature.display_name,
                    role=feature.role,
                    ratings=(rating,),
                    thread_ids=(thread_id,),
                    session_ids=(session_id,),
                    event_ids=(event_id,),
                    issue_ids=(raw_issue_id,),
                    observed_ats=(timestamp,),
                )
            else:
                groups[key] = _FeatureObservationGroup(
                    signal_type=group.signal_type,
                    stable_key=group.stable_key,
                    display_name=group.display_name,
                    role=group.role,
                    ratings=group.ratings + (rating,),
                    thread_ids=group.thread_ids + (thread_id,),
                    session_ids=group.session_ids + (session_id,),
                    event_ids=group.event_ids + (event_id,),
                    issue_ids=group.issue_ids + (raw_issue_id,),
                    observed_ats=group.observed_ats + (timestamp,),
                )

    return groups


def _compute_inferred_values(
    group: _FeatureObservationGroup,
    baseline_mean: float,
) -> tuple[float, float]:
    """Compute inferred affinity and confidence from aggregated observations.

    Inference rules:
    - Positive delta from baseline -> positive affinity (aligned).
    - Negative delta -> negative affinity (opposed).
    - Confidence grows logarithmically with evidence count, capped at 0.95.
    - Diversity across distinct threads and sessions adds a small bonus.
    - One or two observations remain very low-confidence.

    Args:
        group: Aggregated observations for this feature.
        baseline_mean: User's overall mean rating.

    Returns:
        (inferred_affinity, confidence) tuple.
    """
    feature_mean = group.feature_mean_rating
    affinity_delta = feature_mean - baseline_mean

    inferred_affinity = round(affinity_delta / 2.0, 4)

    if inferred_affinity > INFERRED_AFFINITY_CAP:
        inferred_affinity = INFERRED_AFFINITY_CAP
    if inferred_affinity < -INFERRED_AFFINITY_CAP:
        inferred_affinity = -INFERRED_AFFINITY_CAP

    evidence_weight = math.log(max(group.evidence_count, 1) + 1) / math.log(11)

    diversity_bonus = 0.0
    if group.distinct_threads_count > 1:
        diversity_bonus += 0.05
    if group.distinct_runs_count > 1:
        diversity_bonus += 0.05

    confidence = MIN_CONFIDENCE_TO_PERSIST + 0.15 * evidence_weight + diversity_bonus
    confidence = min(INFERRED_AFFINITY_CAP, max(MIN_CONFIDENCE_TO_PERSIST, confidence))
    confidence = round(confidence, 4)

    return inferred_affinity, confidence


def _apply_inferred_signal(
    user_id: int,
    group: _FeatureObservationGroup,
    baseline_mean: float,
    existing_signal: TasteSignal | None,
) -> TasteSignal:
    """Apply inferred values onto an existing signal or build a new one.

    Existing ORM instances are mutated in place so SQLAlchemy updates the
    persisted row instead of attempting to insert a duplicate identity.
    Explicit user verdicts are never overwritten: confirmed signals keep a
    non-negative affinity, rejected signals keep a non-positive affinity,
    and neither may lose previously earned confidence.

    Args:
        user_id: User ID owning the signal.
        group: Aggregated observations for this feature.
        baseline_mean: User's overall mean rating.
        existing_signal: Persisted TasteSignal to update, or None.

    Returns:
        The TasteSignal instance carrying the inferred state.
    """
    inferred_affinity, confidence = _compute_inferred_values(group, baseline_mean)
    last_observed = group.observed_ats[-1] if group.observed_ats else datetime.now()

    if existing_signal is None:
        return TasteSignal(
            user_id=user_id,
            signal_type=group.signal_type,
            external_key=group.stable_key,
            display_name=group.display_name,
            affinity_estimate=inferred_affinity,
            evidence_count=group.evidence_count,
            distinct_thread_count=group.distinct_threads_count,
            confidence=confidence,
            user_verdict=None,
            first_observed_at=last_observed,
            last_observed_at=last_observed,
        )

    verdict = existing_signal.user_verdict
    prior_confidence = existing_signal.confidence or 0.0

    if verdict == "confirmed":
        inferred_affinity = max(inferred_affinity, 0.0)
        confidence = max(confidence, prior_confidence)
    elif verdict == "rejected":
        inferred_affinity = min(inferred_affinity, 0.0)
        confidence = max(confidence, prior_confidence)

    first_observed = existing_signal.first_observed_at
    if first_observed is None:
        first_observed = last_observed
    elif last_observed < first_observed:
        first_observed = last_observed

    existing_signal.display_name = group.display_name
    existing_signal.affinity_estimate = inferred_affinity
    existing_signal.evidence_count = group.evidence_count
    existing_signal.distinct_thread_count = group.distinct_threads_count
    existing_signal.confidence = confidence
    existing_signal.first_observed_at = first_observed
    existing_signal.last_observed_at = (
        last_observed
        if existing_signal.last_observed_at is None
        else max(existing_signal.last_observed_at, last_observed)
    )
    return existing_signal


async def infer_taste_bank(db: AsyncSession, user_id: int) -> list[TasteSignal]:
    """Rebuild inferred Taste Bank signals for a user from reading history.

    Full recomputation pass: reads the user's most recent rating events,
    computes baseline statistics, extracts ComicVine taste features, groups
    observations by feature, computes inferred affinity and confidence, and
    persists updated TasteSignal rows. Existing TasteEvidence rows are
    replaced wholesale so derived state stays rebuildable from history.

    Inferred-only signals whose features no longer appear in rated history
    are deleted. Signals carrying an explicit user verdict are never deleted.

    Args:
        db: Async database session.
        user_id: User whose taste bank to rebuild.

    Returns:
        List of TasteSignal instances reflecting the current inferred state.
    """
    event_rows = await _fetch_user_rated_event_rows(db, user_id)

    if not event_rows:
        return []

    rated_issue_ids = [
        int(row["issue_id"]) for row in event_rows if isinstance(row["issue_id"], int)
    ]
    metadata_map = await _fetch_confirmed_identity_metadata(db, rated_issue_ids)

    all_ratings = [float(row["rating"]) for row in event_rows]
    baseline_mean, _ = _compute_baseline_stats(all_ratings)

    observation_groups = _group_observations(user_id, event_rows, metadata_map)

    if not observation_groups:
        return []

    existing_signals = await _fetch_existing_taste_signals(db, user_id)

    inferred_signals: list[TasteSignal] = []
    for (signal_type, stable_key), group in sorted(observation_groups.items()):
        if group.evidence_count < MIN_EVIDENCE_FOR_INFERENCE:
            continue

        signal = _apply_inferred_signal(
            user_id=user_id,
            group=group,
            baseline_mean=baseline_mean,
            existing_signal=existing_signals.get((signal_type, stable_key)),
        )
        if (signal.signal_type, signal.external_key) not in existing_signals:
            db.add(signal)
        inferred_signals.append(signal)

    persisted_keys = {(s.signal_type, s.external_key) for s in inferred_signals}
    stale_existing = [
        existing_signals[key]
        for key in set(existing_signals) - persisted_keys
        if existing_signals[key].user_verdict is None
    ]
    for stale_signal in stale_existing:
        await db.delete(stale_signal)

    await db.execute(delete(TasteEvidence).where(TasteEvidence.user_id == user_id))
    await db.flush()

    resolved_map = {(s.signal_type, s.external_key): s for s in inferred_signals}
    for (signal_type, stable_key), group in observation_groups.items():
        resolved = resolved_map.get((signal_type, stable_key))
        if resolved is None or resolved.id is None:
            continue

        for i, event_id in enumerate(group.event_ids):
            db.add(
                TasteEvidence(
                    taste_signal_id=resolved.id,
                    user_id=user_id,
                    signal_type=signal_type,
                    external_key=stable_key,
                    event_id=event_id,
                    thread_id=group.thread_ids[i],
                    issue_id=group.issue_ids[i],
                    observed_rating=group.ratings[i],
                    observed_at=group.observed_ats[i],
                )
            )

    logger.info(
        "Rebuilt taste bank for user %s: %s signals, %s removed",
        user_id,
        len(inferred_signals),
        len(stale_existing),
    )
    return inferred_signals


async def rebuild_user_taste_bank(db: AsyncSession, user_id: int) -> list[TasteSignal]:
    """Public entry point to rebuild a user's complete taste bank from history.

    Combines infer_taste_bank with appropriate transaction handling.
    Source evidence (raw events) is never modified; only derived TasteSignal
    and TasteEvidence rows change.

    Args:
        db: Async database session.
        user_id: User whose taste bank to rebuild.

    Returns:
        List of TasteSignal instances reflecting the current inferred state.
    """
    return await infer_taste_bank(db, user_id)
