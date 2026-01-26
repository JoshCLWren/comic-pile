"""Snooze API endpoint."""

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.api.session as session_module

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import ActiveThreadInfo, SessionResponse
from app.schemas.session import SnoozedThreadInfo
from comic_pile.dice_ladder import step_up
from comic_pile.session import get_current_die

logger = logging.getLogger(__name__)

router = APIRouter()

clear_cache = None

# Disable session cache to prevent issues in tests
if os.getenv("TEST") or os.getenv("DISABLE_SESSION_CACHE"):
    if hasattr(session_module, "get_current_session_cached"):
        session_module.get_current_session_cached = None


def build_ladder_path(session_id: int, db: Session) -> str:
    """Build narrative summary of dice ladder from session events."""
    session = db.get(SessionModel, session_id)
    if not session:
        return ""

    events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type == "rate")
            .order_by(Event.timestamp)
        )
        .scalars()
        .all()
    )

    if not events:
        return str(session.start_die)

    path = [session.start_die]
    for event in events:
        if event.die_after:
            path.append(event.die_after)

    return " → ".join(str(d) for d in path)


def get_active_thread_info(
    session_id: int, db: Session
) -> tuple[int | None, ActiveThreadInfo | None]:
    """Get the most recently rolled thread info for the session.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        Tuple of (thread_id, ActiveThreadInfo or None).
    """
    event = (
        db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type == "roll")
            .where(Event.selected_thread_id.is_not(None))
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if not event or not event.selected_thread_id:
        return None, None

    thread = db.get(Thread, event.selected_thread_id)
    if not thread:
        return event.selected_thread_id, None

    return event.selected_thread_id, ActiveThreadInfo(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        queue_position=thread.queue_position,
        last_rolled_result=event.result,
    )


def build_session_response(session: SessionModel, db: Session) -> SessionResponse:
    """Build a SessionResponse from a session model.

    Args:
        session: The session model.
        db: Database session.

    Returns:
        A SessionResponse with all required fields populated.
    """
    _, active_thread = get_active_thread_info(session.id, db)

    snapshot_count = (
        db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
        ).scalar()
        or 0
    )

    snoozed_ids = session.snoozed_thread_ids or []
    snoozed_threads: list[SnoozedThreadInfo] = []
    for thread_id in snoozed_ids:
        thread = db.get(Thread, thread_id)
        if thread:
            snoozed_threads.append(SnoozedThreadInfo(id=thread.id, title=thread.title))

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=build_ladder_path(session.id, db),
        active_thread=active_thread,
        current_die=get_current_die(session.id, db),
        last_rolled_result=active_thread.last_rolled_result if active_thread else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
        snoozed_thread_ids=snoozed_ids,
        snoozed_threads=snoozed_threads,
    )


@router.post("/", response_model=SessionResponse)
@limiter.limit("30/minute")
def snooze_thread(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Snooze the pending thread and step the die up.

    This endpoint:
    1. Gets the current session (must exist with a pending_thread_id)
    2. Adds the pending_thread_id to snoozed_thread_ids
    3. Steps the die UP (wider pool) using dice ladder logic
    4. Records a "snooze" event
    5. Clears pending_thread_id
    6. Returns the updated session
    """
    current_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.user_id == current_user.id)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .first()
    )

    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session. Please roll the dice first.",
        )

    if not current_session.pending_thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending thread to snooze. Please roll the dice first.",
        )

    pending_thread_id = current_session.pending_thread_id
    current_session_id = current_session.id

    # Add to snoozed_thread_ids list
    snoozed_ids = current_session.snoozed_thread_ids or []
    logger.info(f"Snooze: pending_thread_id={pending_thread_id}, snoozed_ids before={snoozed_ids}")
    if pending_thread_id not in snoozed_ids:
        snoozed_ids.append(pending_thread_id)
        current_session.snoozed_thread_ids = snoozed_ids
        logger.info(f"Snooze: added to snoozed list, snoozed_ids after={snoozed_ids}")
    else:
        logger.info(f"Snooze: thread {pending_thread_id} already in snoozed list")

    # Step die UP (wider pool)
    current_die = get_current_die(current_session_id, db)
    new_die = step_up(current_die)
    current_session.manual_die = new_die

    # Record snooze event
    event = Event(
        type="snooze",
        session_id=current_session_id,
        thread_id=pending_thread_id,
        die=current_die,
        die_after=new_die,
    )
    db.add(event)

    # Clear pending_thread_id
    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None

    db.commit()

    if clear_cache:
        clear_cache()

    db.refresh(current_session)
    logger.info(
        f"Snooze: after commit and refresh, snoozed_thread_ids={current_session.snoozed_thread_ids}"
    )

    return build_session_response(current_session, db)
