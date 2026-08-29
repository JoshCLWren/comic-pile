"""Recompute inferred Taste Bank signals from a reader's history (issue #1745).

This service ties the pure calculation in :mod:`app.services.taste_inference`
to the durable ``taste_signals`` table. It reads the reader's own ratings and
their confirmed ComicVine issue metadata, derives a baseline, computes inferred
signals for every feature, and persists them through the verdict-preserving
repository helper.

It deliberately performs no ranking or UI work: it only refreshes derived state
that the discovery and verdict layers consume elsewhere.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.repositories import taste_signal as taste_signal_repository
from app.services.taste_inference import (
    DEFAULT_INFERENCE_CONFIG,
    FeatureResult,
    InferenceConfig,
    recompute_from_reading_history,
)


def _series_metadata_for_thread(
    series_identities: list[ExternalIdentity],
) -> dict[str, object] | None:
    """Pick the metadata dict for a thread's confirmed series, if any.

    Args:
        series_identities: Confirmed series ExternalIdentity rows for a thread.

    Returns:
        The first series ``metadata_json``, or ``None`` when unavailable.
    """
    for identity in series_identities:
        metadata = identity.metadata_json
        if isinstance(metadata, dict) and metadata:
            return metadata
    return None


async def _baseline_rating(db: AsyncSession, user_id: int) -> float:
    """Return the reader's mean thread rating, or the neutral baseline.

    Args:
        db: Async database session.
        user_id: Owning user id.

    Returns:
        Mean ``last_rating`` across the user's threads, or
        :attr:`InferenceConfig.neutral_rating_baseline` when none exist.
    """
    result = await db.execute(
        select(Thread.last_rating).where(
            Thread.user_id == user_id,
            Thread.last_rating.is_not(None),
        )
    )
    ratings = [row[0] for row in result.all() if row[0] is not None]
    if not ratings:
        return DEFAULT_INFERENCE_CONFIG.neutral_rating_baseline
    return sum(ratings) / len(ratings)


async def _confirmed_issue_metadata(
    db: AsyncSession, thread_id: int
) -> list[tuple[int, dict[str, object]]]:
    """Return ``(issue_id, metadata)`` for a thread's confirmed issues.

    Args:
        db: Async database session.
        thread_id: Thread whose issues are inspected.

    Returns:
        One pair per issue in the thread that has a confirmed external identity
        mapping, carrying its ``metadata_json``.
    """
    result = await db.execute(
        select(Issue.id, ExternalIdentity.metadata_json)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .where(Issue.thread_id == thread_id)
        .where(IssueExternalIdentityMapping.status == "confirmed")
    )
    pairs = []
    for issue_id, metadata in result.all():
        if isinstance(metadata, dict):
            pairs.append((issue_id, metadata))
    return pairs


async def _confirmed_series_metadata(
    db: AsyncSession, thread_id: int
) -> dict[str, object] | None:
    """Return confirmed series metadata for a thread, if present.

    Args:
        db: Async database session.
        thread_id: Thread whose series mapping is inspected.

    Returns:
        The first confirmed series ``metadata_json``, or ``None``.
    """
    result = await db.execute(
        select(ExternalIdentity)
        .join(
            ThreadExternalSeriesMapping,
            ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(ThreadExternalSeriesMapping.thread_id == thread_id)
        .where(ThreadExternalSeriesMapping.status == "confirmed")
    )
    series_rows = list(result.scalars().all())
    return _series_metadata_for_thread(series_rows)


async def recompute_user_taste_signals(
    db: AsyncSession,
    user_id: int,
    now: datetime | None = None,
    config: InferenceConfig | None = None,
) -> list[FeatureResult]:
    """Recompute and persist every inferred taste signal for one reader.

    The reader's baseline is their mean thread rating. For every thread they
    own, each confirmed issue contributes one reading-history item keyed by the
    thread so evidence diversity reflects distinct threads/runs. Confirmed
    verdicts on existing rows are preserved untouched.

    Args:
        db: Async database session.
        user_id: Owning user id.
        now: Timestamp for observation bookkeeping; defaults to ``datetime.now(UTC)``.
        config: Tuning constants; defaults to :data:`DEFAULT_INFERENCE_CONFIG`.

    Returns:
        The recomputed feature results (also persisted via the repository).
    """
    config = config or DEFAULT_INFERENCE_CONFIG
    now = now or datetime.now(UTC)

    baseline = await _baseline_rating(db, user_id)

    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    threads = list(result.scalars().all())

    rated_items: list[dict[str, object]] = []
    for thread in threads:
        if thread.last_rating is None:
            continue
        issue_metadata_list = await _confirmed_issue_metadata(db, thread.id)
        series_metadata = await _confirmed_series_metadata(db, thread.id)
        for issue_id, issue_metadata in issue_metadata_list:
            rated_items.append(
                {
                    "thread_id": thread.id,
                    "issue_id": issue_id,
                    "rating": thread.last_rating,
                    "accepted": None,
                    "issue_metadata": issue_metadata,
                    "volume_metadata": series_metadata,
                }
            )

    results = recompute_from_reading_history(baseline, rated_items, config)

    for feature in results:
        await taste_signal_repository.apply_inferred_signal(
            db,
            user_id=user_id,
            signal_type=feature.signal_type,
            external_key=feature.external_key,
            display_name=feature.display_name,
            inferred=feature.inferred,
            now=now,
        )

    return results


__all__ = ["recompute_user_taste_signals"]
