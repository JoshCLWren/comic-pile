"""Durable ComicVine issue metadata repair query construction and persistence.

All SQLAlchemy access for ``ComicVineMetadataRefreshRequest`` lives here. The
service layer owns retry policy, provider calls, and state transitions; this
module only claims due work atomically and persists the resulting state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comicvine_metadata_refresh import ComicVineMetadataRefreshRequest


@dataclass(frozen=True, slots=True)
class ClaimedRefreshRequest:
    """One durable repair request atomically claimed by a worker."""

    request_id: int
    external_identity_id: int
    attempts: int


def _due_predicate(now: datetime):
    """Build the cross-instance due-work predicate.

    Args:
        now: Current timezone-aware UTC timestamp.

    Returns:
        SQLAlchemy predicate selecting claimable requests.
    """
    return or_(
        and_(
            ComicVineMetadataRefreshRequest.state.in_(("pending", "deferred")),
            ComicVineMetadataRefreshRequest.next_attempt_at <= now,
        ),
        and_(
            ComicVineMetadataRefreshRequest.state == "running",
            or_(
                ComicVineMetadataRefreshRequest.lease_expires_at.is_(None),
                ComicVineMetadataRefreshRequest.lease_expires_at <= now,
            ),
        ),
    )


async def get_request(
    db: AsyncSession,
    external_identity_id: int,
) -> ComicVineMetadataRefreshRequest | None:
    """Read the durable request for one confirmed external identity.

    Args:
        db: Async database session.
        external_identity_id: ``external_identities.id`` key for the request.

    Returns:
        The stored request, or ``None`` when no request exists.
    """
    result = await db.execute(
        select(ComicVineMetadataRefreshRequest).where(
            ComicVineMetadataRefreshRequest.external_identity_id == external_identity_id
        )
    )
    return result.scalar_one_or_none()


async def enqueue_request(
    db: AsyncSession,
    *,
    external_identity_id: int,
    now: datetime,
    terminal_reset_before: datetime,
) -> tuple[ComicVineMetadataRefreshRequest, bool]:
    """Idempotently create or reopen one durable repair request.

    The unique identity constraint plus ``ON CONFLICT DO NOTHING`` makes
    concurrent page loads and serverless instances converge on one row. A
    terminal request is reopened only when its completed metadata has reached
    the provider freshness window, or when a failed retry cycle's cooldown has
    elapsed.

    Args:
        db: Async database session.
        external_identity_id: ``external_identities.id`` key for the request.
        now: Current timezone-aware UTC timestamp.
        terminal_reset_before: Terminal requests completed before this timestamp
            may be reopened because their metadata is stale again.

    Returns:
        Tuple of the stored request and whether this call created or reopened it.
    """
    inserted = await db.execute(
        pg_insert(ComicVineMetadataRefreshRequest)
        .values(
            external_identity_id=external_identity_id,
            state="pending",
            attempts=0,
            next_attempt_at=now,
            lease_expires_at=None,
            last_error=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_comicvine_metadata_refresh_identity")
        .returning(ComicVineMetadataRefreshRequest.id)
    )
    requested = inserted.scalar_one_or_none() is not None

    if not requested:
        reopened = await db.execute(
            update(ComicVineMetadataRefreshRequest)
            .where(
                ComicVineMetadataRefreshRequest.external_identity_id == external_identity_id,
                or_(
                    and_(
                        ComicVineMetadataRefreshRequest.state.in_(("completed", "no_credits")),
                        or_(
                            ComicVineMetadataRefreshRequest.completed_at.is_(None),
                            ComicVineMetadataRefreshRequest.completed_at
                            <= terminal_reset_before,
                        ),
                    ),
                    and_(
                        ComicVineMetadataRefreshRequest.state == "failed",
                        ComicVineMetadataRefreshRequest.next_attempt_at <= now,
                    ),
                ),
            )
            .values(
                state="pending",
                attempts=0,
                next_attempt_at=now,
                lease_expires_at=None,
                last_error=None,
                completed_at=None,
                updated_at=now,
            )
            .returning(ComicVineMetadataRefreshRequest.id)
        )
        requested = reopened.scalar_one_or_none() is not None

    request = await get_request(db, external_identity_id)
    if request is None:  # pragma: no cover - the insert above always creates it
        raise RuntimeError("durable ComicVine metadata refresh request was not persisted")
    return request, requested


async def claim_due_requests(
    db: AsyncSession,
    *,
    now: datetime,
    limit: int,
    lease_seconds: float,
) -> list[ClaimedRefreshRequest]:
    """Atomically claim due requests for one worker.

    ``FOR UPDATE SKIP LOCKED`` inside the candidate subquery lets concurrent
    serverless instances claim disjoint work without a thundering herd. A stale
    ``running`` lease is reclaimable so a discarded serverless invocation does
    not strand a request forever.

    Args:
        db: Async database session.
        now: Current timezone-aware UTC timestamp.
        limit: Maximum requests to claim.
        lease_seconds: How long the claim is valid before another worker may
            reclaim it.

    Returns:
        Claimed requests in deterministic due order.
    """
    candidate_ids = (
        select(ComicVineMetadataRefreshRequest.id)
        .where(_due_predicate(now))
        .order_by(
            ComicVineMetadataRefreshRequest.next_attempt_at,
            ComicVineMetadataRefreshRequest.id,
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = await db.execute(
        update(ComicVineMetadataRefreshRequest)
        .where(ComicVineMetadataRefreshRequest.id.in_(candidate_ids))
        .values(
            state="running",
            attempts=ComicVineMetadataRefreshRequest.attempts + 1,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        .returning(
            ComicVineMetadataRefreshRequest.id,
            ComicVineMetadataRefreshRequest.external_identity_id,
            ComicVineMetadataRefreshRequest.attempts,
        )
    )
    return [
        ClaimedRefreshRequest(
            request_id=int(row.id),
            external_identity_id=int(row.external_identity_id),
            attempts=int(row.attempts),
        )
        for row in claimed.all()
    ]


async def mark_completed(
    db: AsyncSession,
    *,
    request_id: int,
    state: str,
    now: datetime,
) -> None:
    """Persist a successful deep hydration outcome.

    Args:
        db: Async database session.
        request_id: Durable request primary key.
        state: ``completed`` when creator credits exist, otherwise ``no_credits``.
        now: Current timezone-aware UTC timestamp.
    """
    await db.execute(
        update(ComicVineMetadataRefreshRequest)
        .where(ComicVineMetadataRefreshRequest.id == request_id)
        .values(
            state=state,
            lease_expires_at=None,
            next_attempt_at=now,
            last_error=None,
            completed_at=now,
            updated_at=now,
        )
    )


async def mark_deferred(
    db: AsyncSession,
    *,
    request_id: int,
    next_attempt_at: datetime,
    now: datetime,
    last_error: str,
) -> None:
    """Persist a bounded retry deferral.

    Args:
        db: Async database session.
        request_id: Durable request primary key.
        next_attempt_at: Earliest time another worker may retry.
        now: Current timezone-aware UTC timestamp.
        last_error: Secret-free bounded failure classification.
    """
    await db.execute(
        update(ComicVineMetadataRefreshRequest)
        .where(ComicVineMetadataRefreshRequest.id == request_id)
        .values(
            state="deferred",
            lease_expires_at=None,
            next_attempt_at=next_attempt_at,
            last_error=last_error[:200],
            updated_at=now,
        )
    )


async def mark_failed(
    db: AsyncSession,
    *,
    request_id: int,
    next_attempt_at: datetime,
    now: datetime,
    last_error: str,
) -> None:
    """Persist an exhausted retry cycle that a later read may reopen.

    Args:
        db: Async database session.
        request_id: Durable request primary key.
        next_attempt_at: Earliest time a read may reopen the request.
        now: Current timezone-aware UTC timestamp.
        last_error: Secret-free bounded failure classification.
    """
    await db.execute(
        update(ComicVineMetadataRefreshRequest)
        .where(ComicVineMetadataRefreshRequest.id == request_id)
        .values(
            state="failed",
            lease_expires_at=None,
            next_attempt_at=next_attempt_at,
            last_error=last_error[:200],
            updated_at=now,
        )
    )
