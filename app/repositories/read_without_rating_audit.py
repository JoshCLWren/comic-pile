"""Evidence queries for the read-without-rating audit (issue #3175).

Every SQLAlchemy query used by the read-without-rating audit lives here so
services stay free of query construction and routers stay free of persistence
(router-layering contract). All queries are user-scoped with no per-issue
fan-out: one bounded batch of queries serves the whole audit population
regardless of how many read-without-rating rows exist.

Evidence model:
- Effective ratings use the exact #2028 semantics (latest ``rate`` event per
  owned issue wins) owned by :mod:`app.repositories.creator_summary`; this
  module never re-derives them so the audit count cannot drift from the
  creator comparison count.
- The only in-library "known historical rating" signal that can fail to
  become an effective rating is a thread-level ``rate`` event: it carries a
  rating for a thread but ``issue_id IS NULL``, so no owned issue gains an
  effective rating from it.
- Identity evidence comes from issue external-identity mappings
  (``confirmed``/``candidate``/``unresolved``/``rejected``).
- Edition/duplicate evidence comes from two owned read issues confirmed against
  the same external issue identity. Issue numbers are unique only within a
  thread and every series restarts at 1, so a shared number alone is not
  conflict evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread


@dataclass
class ThreadHistoricalRating:
    """One thread-level historical ``rate`` event carrying a rating.

    Attributes:
        event_id: Primary key of the source ``rate`` event.
        thread_id: Thread the historical rating was recorded against.
        rating: Recorded rating value.
        recorded_at: Timestamp of the source event.
    """

    event_id: int
    thread_id: int
    rating: float
    recorded_at: datetime | None


@dataclass
class ReadWithoutRatingSignals:
    """Batched audit evidence for one user's read-without-rating population.

    Attributes:
        thread_historical_ratings: Thread id to that thread's thread-level
            historical ratings (``rate`` events with a rating but no
            ``issue_id``), oldest first.
        mapping_statuses: Issue id to the distinct mapping statuses observed
            for that issue (subset of ``confirmed``/``candidate``/
            ``unresolved``/``rejected``). Issues with no mapping row are
            absent.
        duplicate_issue_ids: Issue id to the sorted ids of other read issues
            in the user's library sharing the same normalized issue number.
            Issues with no cross-thread collision are absent.
    """

    thread_historical_ratings: dict[int, list[ThreadHistoricalRating]] = field(
        default_factory=dict
    )
    mapping_statuses: dict[int, list[str]] = field(default_factory=dict)
    duplicate_issue_ids: dict[int, list[int]] = field(default_factory=dict)


@dataclass
class OwnedIssueIdentity:
    """Local identity for one owned issue.

    Attributes:
        issue_id: Local ComicPile issue id.
        issue_number: Display issue number within its thread.
        thread_id: Owning thread id.
        thread_title: Owning thread title.
    """

    issue_id: int
    issue_number: str
    thread_id: int
    thread_title: str


async def load_owned_issue_identities(
    db: AsyncSession,
    user_id: int,
    issue_ids: Sequence[int],
) -> dict[int, OwnedIssueIdentity]:
    """Load local identities for the requested user issues.

    Args:
        db: Async database session.
        user_id: Owner whose issues scope the lookup.
        issue_ids: Issue ids whose identities are requested. Empty input
            returns an empty mapping without querying.

    Returns:
        Mapping of issue id to its local identity. Requested ids outside
        the user's library are absent.
    """
    unique_ids = list(dict.fromkeys(issue_ids))
    if not unique_ids:
        return {}
    result = await db.execute(
        select(Issue.id, Issue.issue_number, Issue.thread_id, Thread.title)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(unique_ids))
        .where(Thread.user_id == user_id)
    )
    return {
        int(issue_id): OwnedIssueIdentity(
            issue_id=int(issue_id),
            issue_number=str(issue_number),
            thread_id=int(thread_id),
            thread_title=str(thread_title),
        )
        for issue_id, issue_number, thread_id, thread_title in result.all()
    }


async def load_read_without_rating_signals(
    db: AsyncSession,
    user_id: int,
    issue_ids: Sequence[int],
) -> ReadWithoutRatingSignals:
    """Load batched audit evidence for the given read-without-rating issues.

    Args:
        db: Async database session.
        user_id: Owner of the library being audited.
        issue_ids: Read-without-rating issue ids to gather evidence for.
            Empty input returns empty signals without querying.

    Returns:
        Batched thread-level historical ratings, mapping statuses, and
        cross-thread duplicate collisions for the requested issues.
    """
    unique_ids = list(dict.fromkeys(issue_ids))
    if not unique_ids:
        return ReadWithoutRatingSignals()

    thread_ids = await _load_owner_thread_ids(db, user_id, unique_ids)
    historical = await _load_thread_historical_ratings(db, user_id, thread_ids)
    statuses = await _load_mapping_statuses(db, unique_ids)
    duplicates = await _load_duplicate_issue_ids(db, user_id, unique_ids)
    return ReadWithoutRatingSignals(
        thread_historical_ratings=historical,
        mapping_statuses=statuses,
        duplicate_issue_ids=duplicates,
    )


async def _load_owner_thread_ids(
    db: AsyncSession,
    user_id: int,
    issue_ids: list[int],
) -> list[int]:
    """Return distinct thread ids owning the requested user issues.

    Args:
        db: Async database session.
        user_id: Owner whose threads scope the lookup.
        issue_ids: Issue ids whose owning threads are requested.

    Returns:
        Sorted thread ids for the user's requested issues.
    """
    result = await db.execute(
        select(Issue.thread_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(issue_ids))
        .where(Thread.user_id == user_id)
        .distinct()
    )
    return sorted(int(thread_id) for thread_id in result.scalars().all())


async def _load_thread_historical_ratings(
    db: AsyncSession,
    user_id: int,
    thread_ids: list[int],
) -> dict[int, list[ThreadHistoricalRating]]:
    """Load thread-level historical ratings for the given threads.

    A thread-level historical rating is a ``rate`` event with a non-null
    rating and ``issue_id IS NULL``: a known rating that can never become an
    effective issue rating on its own.

    Args:
        db: Async database session.
        user_id: Owner whose threads scope the lookup.
        thread_ids: Threads whose historical ratings are requested.

    Returns:
        Mapping of thread id to that thread's historical ratings, oldest
        event first.
    """
    historical: dict[int, list[ThreadHistoricalRating]] = {}
    if not thread_ids:
        return historical
    result = await db.execute(
        select(Event.id, Event.thread_id, Event.rating, Event.timestamp)
        .join(Thread, Thread.id == Event.thread_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.rating.is_not(None))
        .where(Event.issue_id.is_(None))
        .where(Event.thread_id.in_(thread_ids))
        .order_by(Event.thread_id, Event.timestamp.asc(), Event.id.asc())
    )
    for event_id, thread_id, rating, recorded_at in result.all():
        historical.setdefault(int(thread_id), []).append(
            ThreadHistoricalRating(
                event_id=int(event_id),
                thread_id=int(thread_id),
                rating=float(rating),
                recorded_at=recorded_at,
            )
        )
    return historical


async def _load_mapping_statuses(
    db: AsyncSession,
    issue_ids: list[int],
) -> dict[int, list[str]]:
    """Load distinct identity-mapping statuses per requested issue.

    Args:
        db: Async database session.
        issue_ids: Issues whose mapping statuses are requested.

    Returns:
        Mapping of issue id to its sorted distinct mapping statuses.
        Issues with no mapping row are absent.
    """
    result = await db.execute(
        select(
            IssueExternalIdentityMapping.issue_id,
            IssueExternalIdentityMapping.status,
        )
        .where(IssueExternalIdentityMapping.issue_id.in_(issue_ids))
        .distinct()
    )
    grouped: dict[int, set[str]] = {}
    for issue_id, status in result.all():
        grouped.setdefault(int(issue_id), set()).add(str(status))
    return {issue_id: sorted(statuses) for issue_id, statuses in grouped.items()}


async def _load_duplicate_issue_ids(
    db: AsyncSession,
    user_id: int,
    issue_ids: Sequence[int],
) -> dict[int, list[int]]:
    """Find true edition/duplicate conflicts among the requested issues.

    Two owned read issues conflict when both are confirmed against the *same*
    external issue identity: the library then holds two copies of one work, so
    a historical rating cannot be attributed to either copy alone.

    A shared normalized issue number is deliberately **not** treated as
    conflict evidence. ``uq_issue_thread_number`` makes the number unique only
    *within* a thread, and ComicPile numbers every series from 1, so virtually
    every issue number collides across unrelated threads. Keying conflicts on
    the number alone would classify nearly the whole library as an edition
    conflict and suppress every repair.

    Args:
        db: Async database session.
        user_id: Owner whose library scopes the lookup.
        issue_ids: Read-without-rating issue ids to check for conflicts.

    Returns:
        Mapping of issue id to the sorted ids of *other* read issues in the
        user's library confirmed against a shared external identity. Issues
        with no conflict are absent.
    """
    wanted = {int(issue_id) for issue_id in issue_ids}
    if not wanted:
        return {}

    requested = await db.execute(
        select(
            IssueExternalIdentityMapping.issue_id,
            IssueExternalIdentityMapping.external_identity_id,
        )
        .where(IssueExternalIdentityMapping.issue_id.in_(wanted))
        .where(IssueExternalIdentityMapping.status == "confirmed")
    )
    issue_identities: dict[int, set[int]] = {}
    for issue_id, external_identity_id in requested.all():
        issue_identities.setdefault(int(issue_id), set()).add(int(external_identity_id))
    shared_identities: set[int] = set()
    for identities in issue_identities.values():
        shared_identities |= identities
    if not shared_identities:
        return {}

    shared = await db.execute(
        select(
            IssueExternalIdentityMapping.issue_id,
            IssueExternalIdentityMapping.external_identity_id,
        )
        .join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Issue.status == "read")
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .where(IssueExternalIdentityMapping.external_identity_id.in_(shared_identities))
    )
    by_identity: dict[int, set[int]] = {}
    for issue_id, external_identity_id in shared.all():
        by_identity.setdefault(int(external_identity_id), set()).add(int(issue_id))

    duplicates: dict[int, list[int]] = {}
    for issue_id, identities in issue_identities.items():
        others: set[int] = set()
        for identity_id in identities:
            others |= by_identity.get(identity_id, set())
        others.discard(issue_id)
        if others:
            duplicates[issue_id] = sorted(others)
    return duplicates


async def count_effective_ratings(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Count the user's owned issues carrying a latest effective rating.

    Uses the same latest-wins ``rate`` semantics as the creator comparison so
    pre/post repair reconciliation cannot drift from the surfaced counts.

    Args:
        db: Async database session.
        user_id: Owner whose effective ratings are counted.

    Returns:
        Number of owned issues with a latest effective ``rate`` event.
    """
    result = await db.execute(
        select(func.count(func.distinct(Event.issue_id)))
        .select_from(Event)
        .join(Issue, Issue.id == Event.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.issue_id.is_not(None))
        .where(Event.rating.is_not(None))
    )
    return int(result.scalar_one())


async def load_repair_event_issue_ids(
    db: AsyncSession,
    issue_ids: Sequence[int],
    repair_source: str,
) -> set[int]:
    """Return requested issues already carrying an audit-repair event.

    The provenance check runs in Python over the fetched ``context``
    documents so no database-specific JSON operator enters the query.

    Args:
        db: Async database session.
        issue_ids: Issue ids to check for prior repair events. Empty input
            returns an empty set without querying.
        repair_source: Provenance marker stored under the ``source`` key of
            repair-event ``context`` documents.

    Returns:
        Subset of the requested issue ids that already carry a repair
        ``rate`` event from the given source.
    """
    unique_ids = list(dict.fromkeys(issue_ids))
    if not unique_ids:
        return set()
    result = await db.execute(
        select(Event.issue_id, Event.context)
        .where(Event.type == "rate")
        .where(Event.issue_id.in_(unique_ids))
    )
    repaired: set[int] = set()
    for issue_id, context in result.all():
        if isinstance(context, dict) and context.get("source") == repair_source:
            repaired.add(int(issue_id))
    return repaired


__all__ = [
    "OwnedIssueIdentity",
    "ReadWithoutRatingSignals",
    "ThreadHistoricalRating",
    "count_effective_ratings",
    "load_owned_issue_identities",
    "load_read_without_rating_signals",
    "load_repair_event_issue_ids",
]
