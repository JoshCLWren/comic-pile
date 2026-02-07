"""Snooze API endpoint."""

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.session as session_module

from app.api.session import build_ladder_path
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


async def get_active_thread_info(
    session_id: int, db: AsyncSession
) -> tuple[int | None, ActiveThreadInfo | None]:
    """Get the most recently rolled thread info for the session.

    Args:
        session_id: The session ID to query.
        db: Database session.

    Returns:
        Tuple of (thread_id, ActiveThreadInfo or None).
    """
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id.is_not(None))
        .order_by(Event.timestamp.desc())
    )
    event = result.scalars().first()

    if not event or not event.selected_thread_id:
        return None, None

    thread = await db.get(Thread, event.selected_thread_id)
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


async def build_session_response(session: SessionModel, db: AsyncSession) -> SessionResponse:
    """Build a SessionResponse from a session model.

    Args:
        session: The session model.
        db: Database session.

    Returns:
        A SessionResponse with all required fields populated.
    """
    _, active_thread = await get_active_thread_info(session.id, db)

    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
    )
    snapshot_count = result.scalar() or 0

    snoozed_ids = session.snoozed_thread_ids or []
    snoozed_threads: list[SnoozedThreadInfo] = []
    for thread_id in snoozed_ids:
        thread = await db.get(Thread, thread_id)
        if thread:
            snoozed_threads.append(SnoozedThreadInfo(id=thread.id, title=thread.title))

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=await build_ladder_path(session.id, db),
        active_thread=active_thread,
        current_die=await get_current_die(session.id, db),
        last_rolled_result=active_thread.last_rolled_result if active_thread else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
        snoozed_thread_ids=snoozed_ids,
        snoozed_threads=snoozed_threads,
    )


@router.post("/", response_model=SessionResponse)
@limiter.limit("30/minute")
async def snooze_thread(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Snooze the pending thread and step the die up.

    This endpoint:
    1. Gets the current session (must exist with a pending_thread_id)
    2. Adds the pending_thread_id to snoozed_thread_ids
    3. Steps the die UP (wider pool) using dice ladder logic
    4. Records a "snooze" event
    5. Clears pending_thread_id
    6. Returns the updated session

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse containing the updated session with snoozed_thread_ids,
        cleared pending_thread_id, and current die state.

    Raises:
        HTTPException: If no active session exists or no pending thread to snooze.
    """
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc())
    )
    current_session = result.scalars().first()

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
    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    logger.info(f"Snooze: pending_thread_id={pending_thread_id}, snoozed_ids before={snoozed_ids}")
    if pending_thread_id not in snoozed_ids:
        snoozed_ids.append(pending_thread_id)
        current_session.snoozed_thread_ids = snoozed_ids
        logger.info(f"Snooze: added to snoozed list, snoozed_ids after={snoozed_ids}")
    else:
        logger.info(f"Snooze: thread {pending_thread_id} already in snoozed list")

    # Step die UP (wider pool)
    current_die = await get_current_die(current_session_id, db)
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

    await db.commit()

    if clear_cache:
        clear_cache()

    await db.refresh(current_session)
    logger.info(
        f"Snooze: after commit and refresh, snoozed_thread_ids={current_session.snoozed_thread_ids}"
    )

    return await build_session_response(current_session, db)


@router.post("/{thread_id}/unsnooze", response_model=SessionResponse)
@limiter.limit("30/minute")
async def unsnooze_thread(
    thread_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Remove thread from snoozed list.

    Args:
        thread_id: The thread ID to remove from snoozed list.
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse containing the updated session with snoozed_thread_ids.

    Raises:
        HTTPException: If no active session exists.
    """
    _ = request
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .where(SessionModel.ended_at.is_(None))
        .order_by(SessionModel.started_at.desc())
    )
    current_session = result.scalars().first()

    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session",
        )

    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    if thread_id in snoozed_ids:
        snoozed_ids.remove(thread_id)
        current_session.snoozed_thread_ids = snoozed_ids

        # Record unsnooze event
        event = Event(
            type="unsnooze",
            session_id=current_session.id,
            thread_id=thread_id,
        )
        db.add(event)

        await db.commit()

    if clear_cache:
        clear_cache()

    await db.refresh(current_session)
    return await build_session_response(current_session, db)
