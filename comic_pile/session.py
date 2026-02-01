"""Session management functions."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_session_settings
from app.models import Event, Snapshot, Thread, Session
from app.models import Session as SessionModel


logger = logging.getLogger(__name__)
_session_creation_lock = asyncio.Lock()


def _session_gap_hours() -> int:
    """Get session gap hours from config."""
    return get_session_settings().session_gap_hours


def _start_die() -> int:
    """Get starting die from config."""
    return get_session_settings().start_die


async def is_active(started_at: datetime, ended_at: datetime | None, _db: AsyncSession) -> bool:
    """Check if session was within configured gap hours."""
    cutoff_time = datetime.now(UTC) - timedelta(hours=_session_gap_hours())
    session_time = started_at
    if session_time.tzinfo is None:
        session_time = session_time.replace(tzinfo=UTC)
    return session_time >= cutoff_time and ended_at is None


async def should_start_new(db: AsyncSession, user_id: int) -> bool:
    """Check if no active session in configured gap hours."""
    cutoff_time = datetime.now(UTC) - timedelta(hours=_session_gap_hours())
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == user_id)
        .where(SessionModel.started_at >= cutoff_time)
        .where(SessionModel.ended_at.is_(None))
    )
    recent_sessions = result.scalars().all()

    return len(recent_sessions) == 0


async def create_session_start_snapshot(db: AsyncSession, session: SessionModel) -> None:
    """Create a snapshot of all states at session start."""
    result = await db.execute(select(Thread).where(Thread.user_id == session.user_id))
    threads = result.scalars().all()

    thread_states = {}
    for thread in threads:
        thread_states[thread.id] = {
            "title": thread.title,
            "format": thread.format,
            "issues_remaining": thread.issues_remaining,
            "last_rating": thread.last_rating,
            "last_activity_at": thread.last_activity_at.isoformat()
            if thread.last_activity_at
            else None,
            "queue_position": thread.queue_position,
            "status": thread.status,
            "review_url": thread.review_url,
            "last_review_at": thread.last_review_at.isoformat() if thread.last_review_at else None,
            "notes": thread.notes,
            "is_test": thread.is_test,
            "created_at": thread.created_at.isoformat(),
            "user_id": thread.user_id,
        }

    session_state = {
        "start_die": session.start_die,
        "manual_die": session.manual_die,
    }

    snapshot = Snapshot(
        session_id=session.id,
        event_id=None,
        thread_states=thread_states,
        description="Session start",
    )
    snapshot.session_state = session_state
    db.add(snapshot)
    await db.commit()


async def get_or_create(db: AsyncSession, user_id: int) -> SessionModel:
    """Get active session or create new one."""
    from app.models import User

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            session_gap_hours = _session_gap_hours()
            start_die = _start_die()

            user = await db.get(User, user_id)
            if not user:
                user = User(id=user_id, username="default_user")
                db.add(user)
                await db.commit()
                await db.refresh(user)

            cutoff_time = datetime.now(UTC) - timedelta(hours=session_gap_hours)
            result = await db.execute(
                select(Session)
                .where(Session.user_id == user_id)
                .where(Session.ended_at.is_(None))
                .where(Session.started_at >= cutoff_time)
                .order_by(Session.started_at.desc(), Session.id.desc())
            )
            active_session = result.scalars().first()

            if active_session:
                return active_session

            async with _session_creation_lock:
                try:
                    await db.execute(text("SELECT pg_advisory_xact_lock(12345)"))
                except Exception as e:
                    logger.warning(
                        f"Advisory lock failed: {e}. "
                        "Continuing with asyncio.Lock protection only. "
                        "This may increase risk of race conditions in multi-instance deployments."
                    )

                result = await db.execute(
                    select(Session)
                    .where(Session.user_id == user_id)
                    .where(Session.ended_at.is_(None))
                    .where(Session.started_at >= cutoff_time)
                    .order_by(Session.started_at.desc(), Session.id.desc())
                )
                active_session = result.scalars().first()

                if active_session:
                    return active_session

                new_session = Session(start_die=start_die, user_id=user_id)
                db.add(new_session)
                await db.commit()
                await db.refresh(new_session)

                await create_session_start_snapshot(db, new_session)

                return new_session
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                await db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise RuntimeError(
                        f"Failed to get_or_create session after {max_retries} retries"
                    ) from e
                delay = initial_delay * (2 ** (retries - 1))
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to get_or_create session after {max_retries} retries")


async def end_session(session_id: int, db: AsyncSession) -> None:
    """Mark session as ended."""
    session = await db.get(SessionModel, session_id)
    if session:
        session.ended_at = datetime.now(UTC)
        await db.commit()


async def get_current_die(session_id: int, db: AsyncSession) -> int:
    """Get current die size based on manual selection or last rating event."""
    start_die = _start_die()
    session = await db.get(SessionModel, session_id)

    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "rate")
        .where(Event.die_after.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    last_rate_event = result.scalars().first()

    if last_rate_event:
        die_after = last_rate_event.die_after
        return die_after if die_after is not None else start_die

    if session and session.manual_die:
        return session.manual_die

    return session.start_die if session else start_die
