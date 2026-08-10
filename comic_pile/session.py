"""Session management functions."""

import asyncio
from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_session_settings
from app.models import Event, Issue, Session, Snapshot, Thread
from app.services.snapshot_contract import USES_ISSUE_TRACKING_KEY

logger = logging.getLogger(__name__)
_session_creation_lock = asyncio.Lock()


def _session_gap_hours() -> int:
    # TODO: Make session_gap_hours configurable in future.
    return get_session_settings().session_gap_hours


def _start_die() -> int:
    """Get starting die from config."""
    return get_session_settings().start_die


def _current_session_filter(user_id: int, cutoff_time: datetime):
    """Build the predicate for a session that should remain authoritative.

    A pending roll is active reading work. Its timestamp, rather than the original session start,
    keeps the session current while the reader is away from the app reading the selected comic.
    """
    return (
        (Session.user_id == user_id)
        & Session.ended_at.is_(None)
        & or_(
            Session.started_at >= cutoff_time,
            and_(
                Session.pending_thread_id.is_not(None),
                Session.pending_thread_updated_at >= cutoff_time,
            ),
        )
    )


def _as_utc(value: datetime) -> datetime:
    """Normalize persisted timestamps for deterministic comparisons."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _last_activity_at(session: Session, last_event_at: datetime | None) -> datetime:
    """Return the latest durable reading activity for a session."""
    candidates = [_as_utc(session.started_at)]
    if (
        session.pending_thread_updated_at is not None
        and (session.pending_thread_id is not None or session.pending_issue_id is not None)
    ):
        candidates.append(_as_utc(session.pending_thread_updated_at))
    if last_event_at is not None:
        candidates.append(_as_utc(last_event_at))
    return max(candidates)


async def resolve_current_session(db: AsyncSession, user_id: int) -> Session | None:
    """Resolve the authoritative unended session from durable recent activity."""
    cutoff_time = datetime.now(UTC) - timedelta(hours=_session_gap_hours())
    result = await db.execute(
        select(Session, func.max(Event.timestamp).label("last_event_at"))
        .outerjoin(Event, Event.session_id == Session.id)
        .where(Session.user_id == user_id)
        .where(Session.ended_at.is_(None))
        .group_by(Session.id)
    )

    candidates: list[tuple[bool, datetime, datetime, int, Session]] = []
    for session, last_event_at in result.all():
        activity_at = _last_activity_at(session, last_event_at)
        if activity_at < cutoff_time:
            continue
        has_pending_context = (
            session.pending_thread_id is not None or session.pending_issue_id is not None
        )
        candidates.append(
            (
                has_pending_context,
                activity_at,
                _as_utc(session.started_at),
                session.id or 0,
                session,
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[:4])[4]


async def is_active(
    started_at: datetime,
    ended_at: datetime | None,
    _db: AsyncSession,
) -> bool:
    """Check whether a session start is within the configured gap."""
    cutoff_time = datetime.now(UTC) - timedelta(hours=_session_gap_hours())
    session_time = _as_utc(started_at)
    return session_time >= cutoff_time and ended_at is None


async def should_start_new(db: AsyncSession, user_id: int) -> bool:
    """Check whether no authoritative current session exists."""
    return await resolve_current_session(db, user_id) is None


async def create_session_start_snapshot(db: AsyncSession, session: Session) -> None:
    """Create a consistent full-library checkpoint at session start."""
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == session.user_id)
        .with_for_update()
    )
    threads = result.scalars().all()
    thread_ids = [thread.id for thread in threads]

    issues_by_thread: dict[int, list[Issue]] = {}
    if thread_ids:
        issues_result = await db.execute(
            select(Issue)
            .where(Issue.thread_id.in_(thread_ids))
            .order_by(Issue.position),
        )
        for issue in issues_result.scalars().all():
            issues_by_thread.setdefault(issue.thread_id, []).append(issue)

    thread_states: dict[int, dict] = {}
    for thread in threads:
        uses_issue_tracking = thread.uses_issue_tracking()
        state = {
            "title": thread.title,
            "format": thread.format,
            "issues_remaining": thread.issues_remaining,
            "last_rating": thread.last_rating,
            "last_activity_at": thread.last_activity_at.isoformat()
            if thread.last_activity_at
            else None,
            "queue_position": thread.queue_position,
            "status": thread.status,
            "notes": thread.notes,
            "is_test": thread.is_test,
            "is_blocked": thread.is_blocked,
            "created_at": thread.created_at.isoformat(),
            "user_id": thread.user_id,
            USES_ISSUE_TRACKING_KEY: uses_issue_tracking,
        }

        if uses_issue_tracking:
            issues = issues_by_thread.get(thread.id, [])
            state["issue_states"] = [
                {
                    "id": issue.id,
                    "number": issue.issue_number,
                    "status": issue.status,
                    "read_at": issue.read_at.isoformat() if issue.read_at else None,
                    "position": issue.position,
                }
                for issue in issues
            ]
            state["total_issues"] = thread.total_issues
            state["next_unread_issue_id"] = thread.next_unread_issue_id
            state["reading_progress"] = thread.reading_progress
        else:
            state["issue_states"] = None
            state["total_issues"] = None
            state["next_unread_issue_id"] = None
            state["reading_progress"] = None

        thread_states[thread.id] = state

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states=thread_states,
        session_state={
            "start_die": session.start_die,
            "manual_die": session.manual_die,
            "current_die": session.start_die,
        },
        description="Session start",
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(session)


async def get_or_create(db: AsyncSession, user_id: int) -> Session:
    """Get the authoritative active session or create one race-safely."""
    from app.models import User

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            start_die = _start_die()

            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                user = User(id=user_id, username=f"user_{user_id}")
                db.add(user)
                await db.commit()

            active_session = await resolve_current_session(db, user_id)
            if active_session:
                return active_session

            async with _session_creation_lock:
                try:
                    await db.execute(
                        text("SELECT pg_advisory_xact_lock(:user_id)"),
                        {"user_id": user_id},
                    )
                except Exception as error:
                    logger.warning(
                        "Advisory lock failed: %s. Continuing with asyncio.Lock "
                        "protection only; multi-instance races are more likely.",
                        error,
                    )

                active_session = await resolve_current_session(db, user_id)
                if active_session:
                    return active_session

                new_session = Session(start_die=start_die, user_id=user_id)
                db.add(new_session)
                await create_session_start_snapshot(db, new_session)
                await db.commit()
                await db.refresh(new_session)
                logger.info(
                    "Resolved current reading session",
                    extra={
                        "user_id": user_id,
                        "session_id": new_session.id,
                        "session_resolution": "created",
                        "session_creation_reason": "no_recent_unended_session",
                    },
                )
                return new_session
        except OperationalError as error:
            if "deadlock" not in str(error).lower():
                raise
            await db.rollback()
            retries += 1
            if retries >= max_retries:
                raise RuntimeError(
                    f"Failed to get_or_create session after {max_retries} retries"
                ) from error
            await asyncio.sleep(initial_delay * (2 ** (retries - 1)))

    raise RuntimeError(f"Failed to get_or_create session after {max_retries} retries")


async def end_session(session_id: int, db: AsyncSession) -> None:
    """Mark a session as ended."""
    session_result = await db.execute(select(Session).where(Session.id == session_id))
    session = session_result.scalar_one_or_none()
    if session:
        session.ended_at = datetime.now(UTC)
        await db.commit()


async def get_current_die(session_id: int, db: AsyncSession) -> int:
    """Get the die from manual selection or the latest die-changing event."""
    start_die = _start_die()
    session_result = await db.execute(select(Session).where(Session.id == session_id))
    session = session_result.scalar_one_or_none()

    if session and session.manual_die:
        return session.manual_die

    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type.in_(("rate", "snooze", "undo")))
        .where(Event.die_after.is_not(None))
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    last_die_event = result.scalars().first()
    if last_die_event and last_die_event.die_after is not None:
        return last_die_event.die_after

    return session.start_die if session else start_die
