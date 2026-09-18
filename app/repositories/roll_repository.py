"""Roll query construction and persistence.

All SQLAlchemy access for roll-related model families lives here.
Functions return ORM models or plain tuples/dicts; callers
(services) own transaction boundaries.
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Session, Snapshot, Thread
from app.models.recommendation_context import RecommendationContext as RecContextModel
from app.schemas.roll import RollRecoveryInfo


async def fetch_session_for_roll(
    db: AsyncSession, user_id: int,
) -> Session | None:
    """Return the active session for a user.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active (non-ended) session, or None when none exists.
    """
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id)
        .where(Session.ended_at.is_(None))
        .order_by(Session.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_session_by_id(
    db: AsyncSession, session_id: int,
) -> Session | None:
    """Return a session by primary key.

    Args:
        db: Database session.
        session_id: Primary key of the session.

    Returns:
        The session, or None when it does not exist.
    """
    return await db.get(Session, session_id)


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
        update(Session)
        .where(Session.id == session_id)
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
        update(Session)
        .where(Session.id == session_id)
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
        update(Session)
        .where(Session.id == session_id)
        .values(skipped_thread_ids=skipped_ids)
    )


async def fetch_session_for_unskip(
    db: AsyncSession, user_id: int,
) -> Session | None:
    """Return the active session for unskip operations.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active session, or None when none exists.
    """
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id)
        .where(Session.ended_at.is_(None))
        .order_by(Session.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_bootstrap_pool_data(
    db: AsyncSession,
    user_id: int,
    die_size: int,
    snoozed_ids: list[int] | None = None,
    skipped_ids: list[int] | None = None,
) -> dict[str, object]:
    """Fetch all pool-related data for the bootstrap endpoint.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        die_size: Current die size for pool boundary.
        snoozed_ids: Thread IDs currently snoozed.
        skipped_ids: Thread IDs currently skipped.

    Returns:
        Dictionary with pool_rows, snoozed_threads, skipped_threads,
        blocked_count, blocked_threads, stale_thread_count, stale_thread.
    """
    from sqlalchemy import Text
    from sqlalchemy.dialects.postgresql import ARRAY

    from app.models import DependencyGroup, DependencyGroupMembership, Issue, Snapshot, Thread

    route_labels_subq = (
        select(
            func.array_agg(func.distinct(DependencyGroup.name)),
        )
        .select_from(DependencyGroupMembership)
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .where(
            or_(
                DependencyGroupMembership.thread_id == Thread.id,
                DependencyGroupMembership.issue_id == Thread.next_unread_issue_id,
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
            Thread.next_unread_issue_id.label("issue_id"),
            Issue.issue_number,
            route_labels_subq.label("route_labels"),
        )
        .outerjoin(Issue, Issue.id == Thread.next_unread_issue_id)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
        .where(Thread.is_blocked.is_(False))
        .order_by(Thread.queue_position)
        .limit(die_size)
    )
    if snoozed_ids:
        pool_query = pool_query.where(Thread.id.not_in(snoozed_ids))
    if skipped_ids:
        pool_query = pool_query.where(Thread.id.not_in(skipped_ids))

    pool_result = await db.execute(pool_query)
    pool_rows = pool_result.all()

    roll_pool = [
        {
            "id": row.id,
            "title": row.title,
            "format": row.format,
            "issue_id": row.issue_id,
            "issue_number": row.issue_number,
            "route_labels": list(row.route_labels or []),
        }
        for row in pool_rows
    ]

    snoozed_threads: list[dict[str, object]] = []
    if snoozed_ids:
        snoozed_result = await db.execute(
            select(Thread.id, Thread.title, Thread.format)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(snoozed_ids))
        )
        snoozed_threads = [
            {"id": row.id, "title": row.title, "format": row.format}
            for row in snoozed_result.all()
        ]

    skipped_threads: list[dict[str, object]] = []
    if skipped_ids:
        skipped_result = await db.execute(
            select(Thread.id, Thread.title, Thread.format)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(skipped_ids))
        )
        skipped_threads = [
            {"id": row.id, "title": row.title, "format": row.format}
            for row in skipped_result.all()
        ]

    blocked_count_result = await db.execute(
        select(func.count())
        .select_from(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(True))
    )
    blocked_count = blocked_count_result.scalar() or 0

    blocked_result = await db.execute(
        select(Thread.id, Thread.title, Thread.format)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(True))
        .order_by(Thread.queue_position)
        .limit(20)
    )
    blocked_threads = [
        {"id": row.id, "title": row.title, "format": row.format}
        for row in blocked_result.all()
    ]

    stale_cutoff = datetime.now(UTC) - __import__("datetime").timedelta(days=7)
    effective_activity = func.coalesce(Thread.last_activity_at, Thread.created_at)
    stale_base = (
        select(func.count())
        .select_from(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where(effective_activity < stale_cutoff)
    )
    if snoozed_ids:
        stale_base = stale_base.where(Thread.id.not_in(snoozed_ids))
    stale_count_result = await db.execute(stale_base)
    stale_thread_count = stale_count_result.scalar() or 0

    stale_thread = None
    if stale_thread_count > 0:
        stale_ids_query = (
            select(Thread.id)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.is_blocked.is_(False))
            .where(effective_activity < stale_cutoff)
        )
        if snoozed_ids:
            stale_ids_query = stale_ids_query.where(Thread.id.not_in(snoozed_ids))
        stale_ids_result = await db.execute(stale_ids_query)
        stale_ids = [row[0] for row in stale_ids_result.all()]
        if stale_ids:
            import random
            chosen_id = random.choice(stale_ids)
            stale_detail_result = await db.execute(
                select(Thread.id, Thread.title, Thread.format, Thread.last_activity_at)
                .where(Thread.id == chosen_id)
            )
            stale_row = stale_detail_result.first()
            if stale_row:
                stale_thread = {
                    "id": stale_row.id,
                    "title": stale_row.title,
                    "format": stale_row.format,
                    "last_activity_at": stale_row.last_activity_at.isoformat()
                    if stale_row.last_activity_at
                    else None,
                }

    active_session = await fetch_active_session(db, user_id)
    session_id = active_session.id if active_session else -1
    snapshot_count_result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
    )
    snapshot_count = snapshot_count_result.scalar() or 0

    return {
        "roll_pool": roll_pool,
        "snoozed_threads": snoozed_threads,
        "skipped_threads": skipped_threads,
        "blocked_count": blocked_count,
        "blocked_threads": blocked_threads,
        "stale_thread_count": stale_thread_count,
        "stale_thread": stale_thread,
        "snapshot_count": snapshot_count,
    }


async def fetch_active_session(
    db: AsyncSession, user_id: int,
) -> Session | None:
    """Return the active session for a user.

    Args:
        db: Database session.
        user_id: Owner of the session.

    Returns:
        The active session, or None when none exists.
    """
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id)
        .where(Session.ended_at.is_(None))
        .order_by(Session.started_at.desc())
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
    from comic_pile.session import get_current_die_for_session as _get_die
    from app.models import Session as SessionModel
    session = await db.get(SessionModel, session_id)
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


async def fetch_stale_threads_for_bootstrap(
    db: AsyncSession,
    user_id: int,
    cutoff_date: datetime,
    snoozed_ids: list[int] | None = None,
) -> list[Thread]:
    """Fetch stale threads for bootstrap.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        cutoff_date: Threads last read before this instant are stale.
        snoozed_ids: Thread IDs currently snoozed; excluded from results.

    Returns:
        Stale threads ordered oldest activity first.
    """
    query = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    if snoozed_ids:
        query = query.where(Thread.id.not_in(snoozed_ids))
    result = await db.execute(query)
    return list(result.scalars().all())


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
) -> tuple[Event | None, Session | None]:
    """Fetch event and session for recommendation explanation.

    Args:
        db: Database session.
        event_id: Event ID to look up.
        user_id: Owner of the session that generated the event.

    Returns:
        Tuple of (Event, Session) or (None, None) when not found.
    """
    result = await db.execute(
        select(Event, Session)
        .join(Session, Event.session_id == Session.id)
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
