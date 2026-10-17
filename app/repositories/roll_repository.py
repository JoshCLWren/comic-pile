"""Roll query construction and persistence.

All SQLAlchemy access for roll-related model families lives here.
Functions return ORM models or plain tuples/dicts; callers
(services) own transaction boundaries.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Text, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reading_eligibility_queries import (
    candidate_predicate,
    blocked_predicate,
    frontier_expression,
)
from app.services.reading_eligibility_service import ReadingEligibilitySnapshot

from app.models import (
    DependencyGroup,
    DependencyGroupMembership,
    Event,
    Issue,
    ReadingSession,
    Snapshot,
    Thread,
)
from app.models.recommendation_context import RecommendationContext as RecContextModel
from app.schemas.roll import RollRecoveryInfo


async def fetch_session_for_roll(
    db: AsyncSession, user_id: int,
) -> ReadingSession | None:
    """Return the active session for a user.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active (non-ended) session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_session_by_id(
    db: AsyncSession, session_id: int,
) -> ReadingSession | None:
    """Return a session by primary key.

    Args:
        db: Database session.
        session_id: Primary key of the session.

    Returns:
        The session, or None when it does not exist.
    """
    return await db.get(ReadingSession, session_id)


async def fetch_thread_by_id(
    db: AsyncSession, thread_id: int, user_id: int, *, for_update: bool = False
) -> Thread | None:
    """Find a thread by ID scoped to its owner.

    Args:
        db: Database session.
        thread_id: Primary key of the thread.
        user_id: Owner that must own the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread, or None when absent or foreign.
    """
    query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def fetch_issue_by_id(
    db: AsyncSession, issue_id: int,
) -> Issue | None:
    """Return an issue by primary key.

    Args:
        db: Database session.
        issue_id: Primary key of the issue.

    Returns:
        The issue, or None when it does not exist.
    """
    return await db.get(Issue, issue_id)


async def fetch_session_events(
    db: AsyncSession, session_id: int,
) -> list[Event]:
    """Return all events for a session in chronological order.

    Args:
        db: Database session.
        session_id: Session whose events are fetched.

    Returns:
        Events ordered by timestamp.
    """
    result = await db.execute(
        select(Event).where(Event.session_id == session_id).order_by(Event.timestamp)
    )
    return list(result.scalars().all())


async def fetch_bounded_roll_pool_rows(
    db: AsyncSession,
    user_id: int,
    current_die: int,
    snoozed_ids: list[int] | None = None,
    skipped_ids: list[int] | None = None,
) -> list[tuple[Thread, int, str | None]]:
    """Return the bounded roll-candidate pool for a user.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        current_die: Current die size; caps pool size.
        snoozed_ids: Thread IDs to exclude.
        skipped_ids: Thread IDs to exclude.

    Returns:
        List of ``(Thread, unread_count, next_issue_number)`` tuples.
    """
    from comic_pile.queue import get_bounded_roll_pool_rows

    return await get_bounded_roll_pool_rows(
        user_id, db, current_die, snoozed_ids, skipped_ids
    )


async def insert_event(db: AsyncSession, event: Event) -> None:
    """Persist an Event row.

    Args:
        db: Database session.
        event: Event instance to add.
    """
    db.add(event)


async def insert_recommendation_context(
    db: AsyncSession, context: RecContextModel
) -> None:
    """Persist a RecommendationContext row.

    Args:
        db: Database session.
        context: RecommendationContext instance to add.
    """
    db.add(context)


async def update_session_pending_thread(
    db: AsyncSession,
    session_id: int,
    thread_id: int | None,
    now: datetime,
) -> None:
    """Set or clear the pending thread on a session.

    Args:
        db: Database session.
        session_id: Session to update.
        thread_id: Thread ID to set as pending, or None to clear.
        now: Timestamp for the update.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.id == session_id)
        .values(
            pending_thread_id=thread_id,
            pending_thread_updated_at=now,
        )
    )


async def clear_session_pending(db: AsyncSession, session_id: int, now: datetime) -> None:
    """Clear the pending thread on a session.

    Args:
        db: Database session.
        session_id: Session to update.
        now: Timestamp for the update.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.id == session_id)
        .values(pending_thread_id=None, pending_thread_updated_at=now)
    )


async def update_session_skipped(
    db: AsyncSession,
    session_id: int,
    skipped_ids: list[int],
) -> None:
    """Update the skipped thread list on a session.

    Args:
        db: Database session.
        session_id: Session to update.
        skipped_ids: New list of skipped thread IDs.
    """
    await db.execute(
        update(ReadingSession)
        .where(ReadingSession.id == session_id)
        .values(skipped_thread_ids=skipped_ids)
    )


async def fetch_session_for_unskip(
    db: AsyncSession, user_id: int,
) -> ReadingSession | None:
    """Return the active session for unskip operations.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_bootstrap_pool_rows(
    db: AsyncSession,
    user_id: int,
    die_size: int,
    excluded_ids: Sequence[int],
    *,
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> list[Row[int, str, str, int | None, str, Sequence[str]]]:
    """Return the bounded roll-pool rows with their route labels.

    Issue #3375: route labels stay inside the single pool statement as a
    correlated aggregate, so the query count never scales with pool size or
    membership count.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        die_size: Current die size bounding the pool.
        excluded_ids: Thread IDs excluded from the pool in any scope.

        eligibility: Validated live result, or None for legacy execution.

    Returns:
        Rows of (id, title, format, issue_id, issue_number, route_labels).
    """
    frontier = frontier_expression(eligibility)
    route_labels_subq = (
        select(
            func.array_agg(func.distinct(DependencyGroup.name)),
        )
        .select_from(DependencyGroupMembership)
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .where(
            or_(
                DependencyGroupMembership.thread_id == Thread.id,
                DependencyGroupMembership.issue_id == frontier,
            ),
            DependencyGroup.user_id == user_id,
        )
        .correlate(Thread)
        .scalar_subquery()
        .cast(ARRAY(Text))
    )

    pool_query = (
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            frontier.label("issue_id"),
            Issue.issue_number,
            route_labels_subq.label("route_labels"),
        )
        .outerjoin(Issue, Issue.id == frontier)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(candidate_predicate(eligibility))
        .order_by(Thread.queue_position)
        .limit(die_size)
    )
    if excluded_ids:
        pool_query = pool_query.where(Thread.id.not_in(excluded_ids))

    result = await db.execute(pool_query)
    return list(result.all())


async def fetch_bootstrap_excluded_thread_rows(
    db: AsyncSession,
    user_id: int,
    thread_ids: Sequence[int],
) -> list[Row[int, str, str, datetime | None]]:
    """Return id/title/format for every snoozed and skipped series at once.

    Issue #3375: snoozed and skipped summaries are two answers to the same
    question, so they are answered by one read instead of one read each.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        thread_ids: Snoozed and skipped thread IDs, or empty when neither.

    Returns:
        Rows of (id, title, format), or an empty list when nothing is excluded.
    """
    if not thread_ids:
        return []

    result = await db.execute(
        select(Thread.id, Thread.title, Thread.format, Thread.last_activity_at)
        .where(Thread.user_id == user_id)
        .where(Thread.id.in_(thread_ids))
    )
    return list(result.all())


async def fetch_bootstrap_blocked_rows(
    db: AsyncSession,
    user_id: int,
    limit: int,
    *,
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> list[Row[int, str, str, int, datetime | None]]:
    """Return the blocked summary rows plus the unbounded blocked total.

    Issue #3375: the blocked count and the blocked rows are the same filtered
    set, so a windowed count rides along on the rows instead of being counted
    by a second statement. The window is evaluated before ``LIMIT``, so
    ``blocked_total`` is the true total even when the row list is truncated.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        limit: Maximum number of blocked rows to return.

        eligibility: Validated live result, or None for legacy execution.

    Returns:
        Rows of (id, title, format, blocked_total).
    """
    result = await db.execute(
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            func.count().over().label("blocked_total"),
            Thread.last_activity_at,
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(blocked_predicate(eligibility))
        .order_by(Thread.queue_position)
        .limit(limit)
    )
    return list(result.all())


async def fetch_bootstrap_stale_rows(
    db: AsyncSession,
    user_id: int,
    stale_cutoff: datetime,
    excluded_ids: Sequence[int],
    *,
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> list[Row[int, str, str, datetime | None, int]]:
    """Return every stale candidate row plus the unbounded stale total.

    Issue #3375: the stale count, the stale candidate IDs, and the chosen
    stale row are one filtered set. Reading the candidate rows once and
    carrying a windowed count removes two of the three statements.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        stale_cutoff: Activity strictly older than this instant is stale.
        excluded_ids: Thread IDs excluded from staleness in any scope.

        eligibility: Validated live result, or None for legacy execution.

    Returns:
        Rows of (id, title, format, last_activity_at, stale_total).
    """
    effective_activity = func.coalesce(Thread.last_activity_at, Thread.created_at)
    stale_query = (
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.last_activity_at,
            func.count().over().label("stale_total"),
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(candidate_predicate(eligibility))
        .where(effective_activity < stale_cutoff)
    )
    if excluded_ids:
        stale_query = stale_query.where(Thread.id.not_in(excluded_ids))

    result = await db.execute(stale_query)
    return list(result.all())


async def fetch_bootstrap_library_rows(
    db: AsyncSession,
    user_id: int,
    *,
    eligibility: ReadingEligibilitySnapshot | None = None,
) -> list[Row[int, str, str, int, bool, str]]:
    """Return active and completed series for exclusion transparency.

    Issue #3375: both statuses are read by the same scan, so one statement
    answers them and the caller partitions on ``status``.

    Args:
        db: Database session.
        user_id: Owner of the threads.

        eligibility: Validated live result, or None for legacy execution.

    Returns:
        Rows of (id, title, format, queue_position, is_blocked, status).
    """
    result = await db.execute(
        select(
            Thread.id,
            Thread.title,
            Thread.format,
            Thread.queue_position,
            (Thread.is_blocked if eligibility is None else blocked_predicate(eligibility)).label(
                "is_blocked"
            ),
            Thread.status,
        )
        .where(Thread.user_id == user_id)
        .where(Thread.status.in_(("active", "completed")))
        .order_by(Thread.queue_position)
    )
    return list(result.all())


async def fetch_active_session(
    db: AsyncSession, user_id: int,
) -> ReadingSession | None:
    """Return the active session for a user.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active session, or None when none exists.
    """
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_current_die_for_session(
    db: AsyncSession, session_id: int,
) -> int:
    """Return the current die size for a session.

    Args:
        db: Database session.
        session_id: Session ID.

    Returns:
        The current die size.
    """
    from comic_pile.reading_session import get_current_die_for_session as _get_die
    from app.models import ReadingSession
    session = await db.get(ReadingSession, session_id)
    if session is None:
        return 1
    return await _get_die(session, db)


async def count_snapshots(db: AsyncSession, session_id: int) -> int:
    """Count snapshots for a session.

    Args:
        db: Database session.
        session_id: Session whose snapshots are counted.

    Returns:
        Number of snapshots (0 when none exist).
    """
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
    )
    return result.scalar() or 0


async def fetch_bootstrap_recovery_data(
    db: AsyncSession,
    user_id: int,
    pending_thread_id: int | None,
    pending_thread_title: str | None,
) -> RollRecoveryInfo | None:
    """Fetch recovery data for the bootstrap endpoint.

    Args:
        db: Async database session.
        user_id: Authenticated owner of the session.
        pending_thread_id: Current pending thread ID.
        pending_thread_title: Title of the pending thread.

    Returns:
        RollRecoveryInfo when the pending roll is blocked, otherwise None.
    """
    from app.roll_recovery import build_roll_recovery

    return await build_roll_recovery(
        db,
        user_id=user_id,
        pending_thread_id=pending_thread_id,
        pending_thread_title=pending_thread_title,
    )


async def fetch_recommendation_explanation(
    db: AsyncSession, event_id: int, user_id: int,
) -> tuple[Event | None, ReadingSession | None]:
    """Fetch event and session for recommendation explanation.

    Args:
        db: Database session.
        event_id: Event ID to look up.
        user_id: Owner of the session that generated the event.

    Returns:
        Tuple of (Event, Session) or (None, None) when not found.
    """
    result = await db.execute(
        select(Event, ReadingSession)
        .join(ReadingSession, Event.session_id == ReadingSession.id)
        .where(Event.id == event_id)
    )
    row = result.one_or_none()
    if row is None:
        return None, None
    event, session = row
    if session.user_id != user_id:
        return None, None
    if event.type != "roll":
        return None, None
    return event, session
