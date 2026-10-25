"""Query construction for reading-effort derivation.

The reading-effort service owns classification thresholds, aggregation, and
estimate precedence. This repository owns every SQL read those calculations
need: linked roll-to-rate observations, confirmed issue identity metadata, and
confirmed thread/series identity metadata.

All functions are read-only. Callers (the reading-effort service) own the
transaction boundary and the domain calculations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Event,
    ExternalIdentity,
    Issue,
    IssueExternalIdentityMapping,
    Thread,
    ThreadExternalSeriesMapping,
)


@dataclass(frozen=True, slots=True)
class LinkedRollRateRow:
    """One roll event linked to the rate event it produced.

    Attributes:
        roll_event_id: The originating roll event id.
        rate_event_id: The linked rate event id.
        session_id: Reading-session id carried by the rate event.
        thread_id: Thread read by the linked events.
        issue_id: Issue read by the rate event, when tracked.
        roll_timestamp: Timestamp recorded on the roll event.
        rate_timestamp: Timestamp recorded on the rate event.
    """

    roll_event_id: int
    rate_event_id: int
    session_id: int | None
    thread_id: int
    issue_id: int | None
    roll_timestamp: datetime | None
    rate_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class PublicationMetadataRow:
    """Confirmed external identity metadata for one issue or thread.

    Attributes:
        target_id: Issue id (issue projection) or thread id (series projection).
        metadata_json: Stored Comic Vine metadata, when present.
    """

    target_id: int
    metadata_json: dict[str, object] | None


async def fetch_linked_roll_rate_rows(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[LinkedRollRateRow]:
    """Return linked roll-to-rate observations for one reader.

    Only explicitly linked events count: the rate event's
    ``source_roll_event_id`` must reference a roll event that selected the same
    thread. No event-order heuristic is used.

    Args:
        db: Async database session.
        user_id: Owner of the reading history.

    Returns:
        Observations in deterministic rate-event id order.
    """
    roll_event = aliased(Event)
    statement = (
        select(roll_event, Event)
        .join(roll_event, Event.source_roll_event_id == roll_event.id)
        .join(Thread, Event.thread_id == Thread.id)
        .where(Event.type == "rate")
        .where(roll_event.type == "roll")
        .where(roll_event.selected_thread_id == Event.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Event.id)
    )
    rows = (await db.execute(statement)).all()
    results: list[LinkedRollRateRow] = []
    for roll_row, rate_row in rows:
        # Extract attributes while the row objects are still bound to avoid
        # potential MissingGreenlet expiration in future call patterns.
        roll_event_id = int(roll_row.id)
        rate_event_id = int(rate_row.id)
        session_id = rate_row.session_id
        thread_id = rate_row.thread_id
        issue_id = rate_row.issue_id
        roll_timestamp = roll_row.timestamp
        rate_timestamp = rate_row.timestamp
        results.append(
            LinkedRollRateRow(
                roll_event_id=roll_event_id,
                rate_event_id=rate_event_id,
                session_id=session_id,
                thread_id=thread_id if thread_id is not None else -1,
                issue_id=issue_id,
                roll_timestamp=roll_timestamp,
                rate_timestamp=rate_timestamp,
            )
        )
    return results


async def fetch_confirmed_issue_publication_metadata(
    db: AsyncSession,
    *,
    issue_ids: Sequence[int],
    user_id: int | None = None,
) -> list[PublicationMetadataRow]:
    """Return confirmed issue-identity metadata for the requested issues.

    Args:
        db: Async database session.
        issue_ids: Issue ids whose confirmed identity metadata should be read.
        user_id: Restrict candidate metadata to this owner when provided.

    Returns:
        Metadata rows ordered by mapping id so callers can apply the first
        confirmed, year-bearing mapping deterministically.
    """
    if not issue_ids:
        return []
    statement = (
        select(IssueExternalIdentityMapping.issue_id, ExternalIdentity.metadata_json)
        .join(
            ExternalIdentity,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(IssueExternalIdentityMapping.issue_id.in_(list(issue_ids)))
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .order_by(IssueExternalIdentityMapping.id)
    )
    if user_id is not None:
        statement = statement.join(Issue, Issue.id == IssueExternalIdentityMapping.issue_id).join(
            Thread, Thread.id == Issue.thread_id,
        ).where(Thread.user_id == user_id)
    rows = (await db.execute(statement)).all()
    return [
        PublicationMetadataRow(
            target_id=int(issue_id),
            metadata_json=metadata_json if isinstance(metadata_json, dict) else None,
        )
        for issue_id, metadata_json in rows
    ]


async def fetch_confirmed_thread_publication_metadata(
    db: AsyncSession,
    *,
    thread_ids: Sequence[int],
    user_id: int | None = None,
) -> list[PublicationMetadataRow]:
    """Return confirmed thread/series identity metadata for the requested threads.

    Args:
        db: Async database session.
        thread_ids: Thread ids whose confirmed series metadata should be read.
        user_id: Restrict candidate metadata to this owner when provided.

    Returns:
        Metadata rows ordered by mapping id so callers can apply the first
        confirmed, year-bearing mapping deterministically.
    """
    if not thread_ids:
        return []
    statement = (
        select(ThreadExternalSeriesMapping.thread_id, ExternalIdentity.metadata_json)
        .join(
            ExternalIdentity,
            ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id,
        )
        .where(ThreadExternalSeriesMapping.thread_id.in_(list(thread_ids)))
        .where(ThreadExternalSeriesMapping.status == "confirmed")
        .order_by(ThreadExternalSeriesMapping.id)
    )
    if user_id is not None:
        statement = statement.join(
            Thread, Thread.id == ThreadExternalSeriesMapping.thread_id,
        ).where(Thread.user_id == user_id)
    rows = (await db.execute(statement)).all()
    return [
        PublicationMetadataRow(
            target_id=int(thread_id),
            metadata_json=metadata_json if isinstance(metadata_json, dict) else None,
        )
        for thread_id, metadata_json in rows
    ]
