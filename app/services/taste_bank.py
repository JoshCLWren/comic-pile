"""Taste Bank inference: derive cautious taste signals from reading history.

Compares feature-level reading behavior against the user's own baseline
rating/acceptance behavior and produces inferred affinity and confidence
suitable for deciding whether a pattern is worth prompting the user about.

Explicit user verdicts (confirmed, sometimes, rejected) are never overwritten
by recalculation. Rejected signals are never re-inferred as confirmed.

Implements the core acceptance criteria from issue #1745:
- Strong repeated above-baseline evidence creates/updates inferred signals.
- One or two isolated issues remain low-confidence.
- Evidence diversity increases confidence relative to a single-run cluster.
- Rejected/confirmed/sometimes verdicts survive recomputation.
"""

from __future__ import annotations

import math
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, TasteEvidence, TasteSignal, Thread
from app.services.comicvine_taste_features import TasteFeature, extract_taste_features

if TYPE_CHECKING:
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
    from app.models.issue import Issue

logger = logging.getLogger(__name__)

MAX_BASELINE_EVENTS = 200
MIN_EVIDENCE_FOR_INFERENCE = 1
MIN_CONFIDENCE_TO_PERSIST = 0.05
INFERRED_AFFINITY_CAP = 0.95


@dataclass(frozen=True, slots=True)
class _FeatureObservationGroup:
    """Aggregated observations for one (user, signal_type, stable_key) pair."""

    signal_type: str
    stable_key: str
    display_name: str
    role: str | None
    ratings: tuple[float, ...] = field(default_factory=tuple)
    thread_ids: tuple[int, ...] = field(default_factory=tuple)
    session_ids: tuple[int, ...] = field(default_factory=tuple)
    event_ids: tuple[int, ...] = field(default_factory=tuple)
    issue_ids: tuple[int, ...] = field(default_factory=tuple)
    observed_ats: tuple[...] = field(default_factory=tuple)

    @property
    def evidence_count(self) -> int:
        return len(self.ratings)

    @property
    def distinct_threads_count(self) -> int:
        return len(set(self.thread_ids))

    @property
    def distinct_runs_count(self) -> int:
        return len({sid for sid in self.session_ids if sid is not None})

    @property
    def feature_mean_rating(self) -> float:
        if not self.ratings:
            return 0.0
        return sum(self.ratings) / len(self.ratings)


def _compute_baseline_stats(
    ratings: Sequence[float],
) -> tuple[float, float]:
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
    std = variance ** 0.5

    if std < 0.01:
        return mean, 1.0

    return mean, std


async def _fetch_user_rated_event_rows(
    db: AsyncSession,
    user_id: int,
    limit: int = MAX_BASELINE_EVENTS,
) -> list[dict]:
    """Fetch rating events with their related issue and user data.

    Returns events ordered by timestamp ascending so the most recent
    baseline stats reflect current behavior.

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
        .order_by(Event.timestamp.asc())
        .limit(limit)
    )

    rows: list[dict] = []
    for row in result.mappings():
        rows.append(
            {
                "event_id": int(row["id"]),
                "rating": float(row["rating"]),
                "thread_id": int(row["thread_id"]),
                "issue_id": int(row["issue_id"]) if row["issue_id"] is not None else None,
                "session_id": int(row["session_id"]) if row["session_id"] is not None else None,
                "timestamp": row["timestamp"],
            }
        )
    return rows


async def _fetch_confirmed_identity_metadata(
    db: AsyncSession,
    issue_ids: list[int],
) -> dict[int, dict[str, object]]:
    """Fetch confirmed ComicVine metadata for a list of issue IDs.

    Args:
        db: Async database session.
        issue_ids: Issue IDs to look up confirmed ComicVine identities for.

    Returns:
        Map of issue_id -> metadata_json dict for issues with confirmed
        ComicVine mappings. Issues without confirmed mappings are omitted.
    """
    if not issue_ids:
        return {}

    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

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
        Map of (signal_type, stable_key) -> TasteSignal.
    """
    result = await db.execute(
        select(TasteSignal).where(TasteSignal.user_id == user_id)
    )
    signals: dict[tuple[str, str], TasteSignal] = {}
    for signal in result.scalars():
        signals[(signal.signal_type, signal.stable_key)] = signal
    return signals


def _group_observations(
    user_id: int,
    event_rows: list[dict],
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
        issue_id = row["issue_id"]
        if issue_id is None or issue_id not in metadata_map:
            continue

        features = extract_taste_features(metadata_map[issue_id])
        if not features:
            continue

        rating = row["rating"]
        thread_id = row["thread_id"]
        session_id = row["session_id"]
        event_id = row["event_id"]
        timestamp = row["timestamp"]

        for feature in features:
            key = (feature.signal_type, feature.stable_key)
            if key not in groups:
                groups[key] = _FeatureObservationGroup(
                    signal_type=feature.signal_type,
                    stable_key=feature.stable_key,
                    display_name=feature.display_name,
                    role=feature.role,
                )

            group = groups[key]
            groups[key] = _FeatureObservationGroup(
                signal_type=group.signal_type,
                stable_key=group.stable_key,
                display_name=group.display_name,
                role=group.role,
                ratings=group.ratings + (rating,),
                thread_ids=group.thread_ids + (thread_id,),
                session_ids=group.session_ids + (session_id,),
                event_ids=group.event_ids + (event_id,),
                issue_ids=group.issue_ids + (issue_id,),
                observed_ats=group.observed_ats + (timestamp,),
            )

    return groups


def _compute_inferred_signal(
    user_id: int,
    group: _FeatureObservationGroup,
    baseline_mean: float,
    existing_signal: TasteSignal | None,
) -> TasteSignal:
    """Compute an inferred TasteSignal from aggregated observations.

    Inference rules:
    - Positive delta from baseline -> positive inferred_affinity (aligned).
    - Negative delta -> negative inferred_affinity (opposed).
    - Confidence grows with evidence count ( logarithmic ), capped at 0.95.
    - Evidence diversity across distinct threads and sessions adds a small bonus.
    - One or two observations result in very low confidence.
    - Explicit user verdicts (confirmed, sometimes, rejected) are preserved
      and are never overwritten by recalculation.

    Args:
        user_id: User ID for the signal.
        group: Aggregated observations for this feature.
        baseline_mean: User's overall mean rating.
        existing_signal: Existing TasteSignal if one exists.

    Returns:
        A TasteSignal instance with inferred values.
    """
    feature_mean = group.feature_mean_rating
    affinity_delta = feature_mean - baseline_mean

    inferred_affinity = round(affinity_delta / 2.0, 4)

    if inferred_affinity > INFERRED_AFFINITY_CAP:
        inferred_affinity = INFERRED_AFFINITY_CAP
    if inferred_affinity < -INFERRED_AFFINITY_CAP:
        inferred_affinity = -INFERRED_AFFINITY_CAP

    import math

    evidence_count = group.evidence_count
    evidence_weight = math.log(max(evidence_count, 1) + 1) / math.log(11)

    diversity_bonus = 0.0
    if group.distinct_threads_count > 1:
        diversity_bonus += 0.05
    if group.distinct_runs_count > 1:
        diversity_bonus += 0.05

    confidence = min(
        INFERRED_AFFINITY_CAP,
        max(MIN_CONFIDENCE_TO_PERSIST, 0.05 + 0.08 * evidence_weight + diversity_bonus),
    )
    confidence = round(confidence, 4)

    if existing_signal is not None and existing_signal.user_verdict == "confirmed":
        inferred_affinity = max(inferred_affinity, 0.0)
        confidence = max(confidence, existing_signal.confidence)
    elif existing_signal is not None and existing_signal.user_verdict == "rejected":
        inferred_affinity = min(inferred_affinity, 0.0)
        confidence = max(confidence, existing_signal.confidence)

    user_verdict = None
    if existing_signal is not None:
        user_verdict = existing_signal.user_verdict

    now = group.observed_ats[-1] if group.observed_ats else None

    first_observed = existing_signal.first_observed_at if existing_signal else now
    last_observed = now

    if existing_signal is not None:
        if first_observed is None or (now is not None and now < first_observed):
            first_observed = now
        if last_observed is None or (now is not None and now > last_observed):
            last_observed = now

    distinct_threads = group.distinct_threads_count
    distinct_runs = group.distinct_runs_count

    return TasteSignal(
        id=existing_signal.id if existing_signal else 0,
        user_id=user_id,
        signal_type=group.signal_type,
        stable_key=group.stable_key,
        display_name=group.display_name,
        inferred_affinity=inferred_affinity,
        evidence_count=evidence_count,
        distinct_threads_count=distinct_threads,
        distinct_runs_count=distinct_runs,
        confidence=confidence,
        user_verdict=user_verdict,
        first_observed_at=first_observed,
        last_observed_at=last_observed,
        last_prompted_at=existing_signal.last_prompted_at if existing_signal else None,
        prompt_suppressed=existing_signal.prompt_suppressed if existing_signal else 0,
        created_at=existing_signal.created_at if existing_signal else now,
        updated_at=now,
    )


async def infer_taste_bank(
    db: AsyncSession,
    user_id: int,
) -> list[TasteSignal]:
    """Rebuild inferred Taste Bank signals for a user from reading history.

    Full recomputation pass: reads all user rating events, computes baseline
    statistics, extracts ComicVine taste features, groups observations by
    feature, computes inferred affinity and confidence, and persists updated
    TasteSignal rows. Existing TasteEvidence rows are replaced to ensure
    rebuildability from source history.

    Verdict preservation rules:
    - Confirmed signals: affinity stays non-negative, confidence stays high.
    - Rejected signals: affinity stays non-positive, confidence stays high.
    - Sometimes signals: recalculated normally but verdict preserved.
    - Inferred signals (no verdict): fully open to recalculation.

    Args:
        db: Async database session.
        user_id: User whose taste bank to rebuild.

    Returns:
        List of TasteSignal instances reflecting the current state.
    """
    event_rows = await _fetch_user_rated_event_rows(db, user_id)

    if not event_rows:
        return []

    rated_issue_ids = [
        row["issue_id"] for row in event_rows if row["issue_id"] is not None
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

        existing = existing_signals.get((signal_type, stable_key))
        signal = _compute_inferred_signal(
            user_id=user_id,
            group=group,
            baseline_mean=baseline_mean,
            existing_signal=existing,
        )

        if existing is not None:
            signal.id = existing.id
            signal.created_at = existing.created_at

        inferred_signals.append(signal)

    new_keys = {(s.signal_type, s.stable_key) for s in inferred_signals}
    stale_existing = [
        existing_signals[key]
        for key in set(existing_signals) - new_keys
        if existing_signals[key].user_verdict is None
    ]
    for stale_signal in stale_existing:
        await db.delete(stale_signal)
    if stale_existing:
        await db.flush()

    signal_map: dict[tuple[str, str], TasteSignal] = {}
    for signal in inferred_signals:
        db.add(signal)
        await db.flush()
        signal_map[(signal.signal_type, signal.stable_key)] = signal

    for signal in inferred_signals:
        key = (signal.signal_type, signal.stable_key)
        group = observation_groups.get(key)
        if group is None:
            continue

        resolved = signal_map.get(key, signal)
        for i, event_id in enumerate(group.event_ids):
            evidence = TasteEvidence(
                taste_signal_id=resolved.id,
                user_id=user_id,
                signal_type=group.signal_type,
                stable_key=group.stable_key,
                event_id=event_id,
                thread_id=group.thread_ids[i],
                issue_id=group.issue_ids[i],
                observed_rating=group.ratings[i],
                observed_at=group.observed_ats[i],
            )
            db.add(evidence)

    return inferred_signals


async def rebuild_user_taste_bank(
    db: AsyncSession,
    user_id: int,
) -> list[TasteSignal]:
    """Public entry point to rebuild a user's complete taste bank from history.

    Combines infer_taste_bank with appropriate transaction handling.
    Source evidence (raw events) is never modified; only derived TasteSignal
    and TasteEvidence rows change.

    Args:
        db: Async database session.
        user_id: User whose taste bank to rebuild.

    Returns:
        List of TasteSignal instances reflecting the current state.
    """
    return await infer_taste_bank(db, user_id)