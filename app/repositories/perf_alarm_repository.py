"""Query construction for durable performance-alarm counters.

All SQLAlchemy access for the ``PerfAlarmCounter`` / ``PerfAlarmIncident``
model family lives here. Callers own transaction boundaries.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.perf_alarm import PerfAlarmCounter, PerfAlarmIncident

FILING_CLAIM_TTL = timedelta(minutes=5)
COMMENT_MIN_INTERVAL = timedelta(hours=1)


async def increment_daily_hit(
    db: AsyncSession,
    *,
    fingerprint: str,
    utc_day: date,
) -> int:
    """Atomically increment the warm over-budget hit count for one UTC day.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
        utc_day: UTC calendar day of the hit.

    Returns:
        The hit count after this increment.
    """
    result = await db.execute(
        pg_insert(PerfAlarmCounter)
        .values(fingerprint=fingerprint, utc_day=utc_day, hit_count=1)
        .on_conflict_do_update(
            index_elements=[
                PerfAlarmCounter.fingerprint,
                PerfAlarmCounter.utc_day,
            ],
            set_={"hit_count": PerfAlarmCounter.hit_count + 1},
        )
        .returning(PerfAlarmCounter.hit_count)
    )
    return int(result.scalar_one())


async def reset_daily_hits(db: AsyncSession, *, fingerprint: str) -> None:
    """Drop daily hit rows so a closed-issue regression must reach N again.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
    """
    await db.execute(
        delete(PerfAlarmCounter).where(PerfAlarmCounter.fingerprint == fingerprint)
    )


async def get_open_issue(db: AsyncSession, *, fingerprint: str) -> int | None:
    """Return the stored open GitHub issue number, if any.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.

    Returns:
        Open issue number, or None.
    """
    result = await db.execute(
        select(PerfAlarmIncident.open_issue_number).where(
            PerfAlarmIncident.fingerprint == fingerprint
        )
    )
    return result.scalar_one_or_none()


async def get_closed_issue(db: AsyncSession, *, fingerprint: str) -> int | None:
    """Return the stored last-closed GitHub issue number, if any.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.

    Returns:
        Last closed issue number, or None.
    """
    result = await db.execute(
        select(PerfAlarmIncident.last_closed_issue_number).where(
            PerfAlarmIncident.fingerprint == fingerprint
        )
    )
    return result.scalar_one_or_none()


async def mark_open(
    db: AsyncSession,
    *,
    fingerprint: str,
    issue_number: int,
) -> None:
    """Record an open incident and clear any filing claim.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
        issue_number: GitHub issue number that is open.
    """
    await db.execute(
        pg_insert(PerfAlarmIncident)
        .values(
            fingerprint=fingerprint,
            open_issue_number=issue_number,
            filing_claimed_at=None,
        )
        .on_conflict_do_update(
            index_elements=[PerfAlarmIncident.fingerprint],
            set_={
                "open_issue_number": issue_number,
                "filing_claimed_at": None,
            },
        )
    )


async def mark_closed(
    db: AsyncSession,
    *,
    fingerprint: str,
    issue_number: int,
) -> None:
    """Record that the fingerprint's issue closed and reset daily hits.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
        issue_number: GitHub issue number that closed.
    """
    await db.execute(
        pg_insert(PerfAlarmIncident)
        .values(
            fingerprint=fingerprint,
            open_issue_number=None,
            last_closed_issue_number=issue_number,
            filing_claimed_at=None,
        )
        .on_conflict_do_update(
            index_elements=[PerfAlarmIncident.fingerprint],
            set_={
                "open_issue_number": None,
                "last_closed_issue_number": issue_number,
                "filing_claimed_at": None,
            },
        )
    )
    await reset_daily_hits(db, fingerprint=fingerprint)


async def try_claim_filing(
    db: AsyncSession,
    *,
    fingerprint: str,
    now: datetime | None = None,
) -> bool:
    """Atomically claim the right to file a new issue for a fingerprint.

    Succeeds when no open issue is stored and no unexpired filing claim
    exists. Concurrent callers lose the race and must not create a second
    issue.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
        now: Clock override for tests.

    Returns:
        True when this caller holds the filing claim.
    """
    current = now if now is not None else datetime.now(UTC)
    stale = current - FILING_CLAIM_TTL
    result = await db.execute(
        pg_insert(PerfAlarmIncident)
        .values(
            fingerprint=fingerprint,
            filing_claimed_at=current,
        )
        .on_conflict_do_update(
            index_elements=[PerfAlarmIncident.fingerprint],
            set_={"filing_claimed_at": current},
            where=(
                PerfAlarmIncident.open_issue_number.is_(None)
                & (
                    PerfAlarmIncident.filing_claimed_at.is_(None)
                    | (PerfAlarmIncident.filing_claimed_at < stale)
                )
            ),
        )
        .returning(PerfAlarmIncident.fingerprint)
    )
    return result.scalar_one_or_none() is not None


async def clear_filing_claim(db: AsyncSession, *, fingerprint: str) -> None:
    """Release a filing claim after a failed GitHub create.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
    """
    incident = await db.get(PerfAlarmIncident, fingerprint)
    if incident is None:
        return
    incident.filing_claimed_at = None


async def try_claim_comment(
    db: AsyncSession,
    *,
    fingerprint: str,
    now: datetime | None = None,
) -> bool:
    """Atomically claim the right to post one comment this hour.

    Args:
        db: Database session.
        fingerprint: Deterministic performance signature hash.
        now: Clock override for tests.

    Returns:
        True when this caller may post a comment.
    """
    current = now if now is not None else datetime.now(UTC)
    stale = current - COMMENT_MIN_INTERVAL
    result = await db.execute(
        pg_insert(PerfAlarmIncident)
        .values(
            fingerprint=fingerprint,
            last_comment_at=current,
        )
        .on_conflict_do_update(
            index_elements=[PerfAlarmIncident.fingerprint],
            set_={"last_comment_at": current},
            where=(
                PerfAlarmIncident.last_comment_at.is_(None)
                | (PerfAlarmIncident.last_comment_at <= stale)
            ),
        )
        .returning(PerfAlarmIncident.fingerprint)
    )
    return result.scalar_one_or_none() is not None
