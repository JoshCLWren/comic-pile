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

from collections import defaultdict
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
from app.services.comicvine_taste import extract_taste_features
from app.services.taste_inference import (
    RatingEvidence,
    SignalMetrics,
    compute_signal_metrics,
)

_NEUTRAL_BASELINE = 3.0


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


def _iter_features(features: dict[str, object]) -> list[tuple[str, str, str]]:
    """Yield ``(signal_type, external_key, display_name)`` for extracted features.

    Args:
        features: Output of :func:`app.services.comicvine_taste.extract_taste_features`.

    Returns:
        One tuple per distinct normalized feature (creators, characters,
        teams, publisher, and publication era).
    """
    emitted: list[tuple[str, str, str]] = []

    creators = features.get("creators")
    if isinstance(creators, list):
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            creator_id = creator.get("id")
            name = creator.get("name")
            if creator_id is None or not name:
                continue
            role = creator.get("role")
            key = f"creator:{role}:{creator_id}" if role else f"creator:{creator_id}"
            emitted.append(("creator", key, str(name)))

    characters = features.get("characters")
    if isinstance(characters, list):
        for character in characters:
            if not isinstance(character, dict):
                continue
            character_id = character.get("id")
            name = character.get("name")
            if character_id is None or not name:
                continue
            emitted.append(("character", f"character:{character_id}", str(name)))

    teams = features.get("teams")
    if isinstance(teams, list):
        for team in teams:
            if not isinstance(team, dict):
                continue
            team_id = team.get("id")
            name = team.get("name")
            if team_id is None or not name:
                continue
            emitted.append(("team", f"team:{team_id}", str(name)))

    publisher = features.get("publisher")
    if isinstance(publisher, dict):
        publisher_id = publisher.get("id")
        name = publisher.get("name")
        if publisher_id is not None and name:
            emitted.append(("publisher", f"publisher:{publisher_id}", str(name)))

    era = features.get("publication_era")
    if era:
        emitted.append(("era", f"era:{era}", str(era)))

    return emitted


async def _baseline_rating(db: AsyncSession, user_id: int) -> float:
    """Return the reader's mean thread rating, or the neutral baseline.

    Args:
        db: Async database session.
        user_id: Owning user id.

    Returns:
        Mean ``last_rating`` across the user's threads, or ``_NEUTRAL_BASELINE``
        when none exist.
    """
    result = await db.execute(
        select(Thread.last_rating).where(
            Thread.user_id == user_id,
            Thread.last_rating.is_not(None),
        )
    )
    ratings = [row[0] for row in result.all() if row[0] is not None]
    if not ratings:
        return _NEUTRAL_BASELINE
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
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
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
) -> list[SignalMetrics]:
    """Recompute and persist every inferred taste signal for one reader.

    The reader's baseline is their mean thread rating. For every thread they
    own, each confirmed issue contributes one reading-history item keyed by the
    thread so evidence diversity reflects distinct threads/runs. Confirmed
    verdicts on existing rows are preserved untouched.

    Args:
        db: Async database session.
        user_id: Owning user id.
        now: Timestamp for observation bookkeeping; defaults to ``datetime.now(UTC)``.

    Returns:
        The recomputed signal metrics (also persisted via the repository).
    """
    now = now or datetime.now(UTC)

    baseline = await _baseline_rating(db, user_id)

    result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    threads = list(result.scalars().all())

    grouped: dict[tuple[str, str], list[RatingEvidence]] = defaultdict(list)
    display_names: dict[tuple[str, str], str] = {}
    seen: set[tuple[str, str, int | None, int | None]] = set()

    for thread in threads:
        if thread.last_rating is None:
            continue
        issue_metadata_list = await _confirmed_issue_metadata(db, thread.id)
        series_metadata = await _confirmed_series_metadata(db, thread.id)

        for issue_id, issue_metadata in issue_metadata_list:
            features = extract_taste_features(issue_metadata, series_metadata)

            dedupe_key_base = (thread.id, issue_id)
            for signal_type, external_key, display_name in _iter_features(features):
                dedupe = (signal_type, external_key, *dedupe_key_base)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                display_names[(signal_type, external_key)] = display_name
                grouped[(signal_type, external_key)].append(
                    RatingEvidence(
                        rating=thread.last_rating,
                        thread_id=thread.id,
                        issue_key=f"t{thread.id}-i{issue_id}",
                    )
                )

    metrics_list: list[SignalMetrics] = []
    for (signal_type, external_key), evidence in grouped.items():
        if not evidence:
            continue
        metrics = compute_signal_metrics(evidence, baseline=baseline)
        display_name = display_names[(signal_type, external_key)]
        await taste_signal_repository.apply_inferred_signal(
            db,
            user_id=user_id,
            signal_type=signal_type,
            external_key=external_key,
            display_name=display_name,
            metrics=metrics,
            now=now,
        )
        metrics_list.append(metrics)

    return metrics_list


__all__ = ["recompute_user_taste_signals"]
