"""Snooze API endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session_response import (
    build_ladder_path,
    build_session_response,
)
from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.thread import normalize_format_value
from app.models.user import User
from app.schemas import ActiveThreadInfo, SessionResponse
from app.schemas.session import (
    SnoozeCorrectionInfo,
    SnoozedThreadInfo,
)
from comic_pile.bandwidth_correction import (
    classify_candidate_effort,
    compute_snooze_correction,
)
from comic_pile.dice_ladder import step_up

logger = logging.getLogger(__name__)

router = APIRouter()


async def _find_source_roll_event(
    db: AsyncSession,
    session_id: int,
    thread_id: int,
) -> int | None:
    """Find the originating roll event for a given thread in this session.

    Args:
        db: Database session.
        session_id: Current reading session ID.
        thread_id: Thread that was rolled/snoozed.

    Returns:
        The ID of the most recent roll event selecting this thread, or None.
    """
    result = await db.execute(
        select(Event.id)
        .where(Event.session_id == session_id)
        .where(Event.type == "roll")
        .where(Event.selected_thread_id == thread_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


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
    4. Computes a structured bandwidth correction from the snooze evidence
    5. Applies the correction to ephemeral session bandwidth state
    6. Records a "snooze" event
    7. Clears pending_thread_id
    8. Returns the updated session with correction guidance

    The snoozed thread's durable queue position is NOT changed (issue #1721).
    Rating remains the authority for long-term promotion/demotion behavior.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse containing the updated session with snoozed_thread_ids,
        cleared pending_thread_id, current die state, bandwidth state, and
        structured correction guidance.

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

    # Combined query: fetch all die-changing events and latest roll event in one shot.
    # die-changing events -> current die + ladder path
    # roll events -> active thread info
    events_result = await db.execute(
        select(Event)
        .where(Event.session_id == current_session_id)
        .where(Event.type.in_(("rate", "snooze", "undo", "roll")))
        .order_by(Event.timestamp.desc(), Event.id.desc())
    )
    all_events = events_result.scalars().all()

    # Current die: latest rate/snooze/undo event with die_after, or session start_die.
    current_die = current_session.manual_die
    if current_die is None:
        for evt in all_events:
            if evt.type in ("rate", "snooze", "undo") and evt.die_after is not None:
                current_die = evt.die_after
                break
        if current_die is None:
            current_die = current_session.start_die

    new_die = step_up(current_die)

    # Ladder path: build from pre-fetched events instead of re-querying.
    die_events = [
        evt
        for evt in reversed(all_events)
        if evt.type in ("rate", "snooze", "undo") and evt.die_after is not None
    ]
    ladder_path = str(current_session.start_die)
    if die_events:
        ladder_path = " → ".join(
            [str(current_session.start_die)] + [str(evt.die_after) for evt in die_events]
        )

    # Active thread: use pending_thread_id from the already-loaded session.
    pre_active_thread = None
    if pending_thread_id is not None:
        active_thread = await db.get(Thread, pending_thread_id)
        if active_thread:
            # Find the roll event result for this thread from pre-fetched events.
            roll_result = None
            for evt in all_events:
                if evt.type == "roll" and evt.selected_thread_id == pending_thread_id:
                    roll_result = evt.result
                    break
            pre_active_thread = ActiveThreadInfo(
                id=active_thread.id,
                title=active_thread.title,
                format=normalize_format_value(active_thread.format),
                issues_remaining=active_thread.issues_remaining,
                queue_position=active_thread.queue_position,
                last_rolled_result=roll_result,
            )

    # Snooze must not mutate durable queue state: the thread keeps its exact
    # queue position and returns to the pool when session snooze state expires.

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

    # Compute bandwidth correction from snooze evidence (pure, side-effect-free)
    recent_snooze_result = await db.execute(
        select(Event)
        .where(Event.session_id == current_session_id)
        .where(Event.type == "snooze")
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(10)
    )
    recent_snoozes = list(recent_snooze_result.scalars().all())
    consecutive_snoozes = len(recent_snoozes) + 1  # +1 for the current snooze

    # Determine last snooze direction relative to current bandwidth
    last_snooze_direction: str | None = None
    current_bw = current_session.active_bandwidth or "balanced"
    if recent_snoozes:
        # Use the most recent previous snooze's die step as a proxy for direction
        prev_die = recent_snoozes[0].die or 6
        prev_die_after = recent_snoozes[0].die_after or 8
        if prev_die_after > prev_die:
            last_snooze_direction = "heavier"
        elif prev_die_after < prev_die:
            last_snooze_direction = "lighter"

    # Classify the snoozed candidate's effort
    candidate_effort = classify_candidate_effort(
        effort_source=None,  # No effort model yet; defaults to balanced
        effort_minutes=None,
    )

    correction_result = compute_snooze_correction(
        current_bandwidth=current_bw,
        current_confidence=current_session.bandwidth_confidence or 0.5,
        predicted_bandwidth=current_session.predicted_bandwidth or current_bw,
        candidate_effort_level=candidate_effort,
        consecutive_snoozes=consecutive_snoozes,
        last_snooze_direction=last_snooze_direction,
    )

    # Extract pre-correction values before mutating session state
    confidence_before = current_session.bandwidth_confidence or 0.5

    # Apply correction to session state (#1724)
    current_session.active_bandwidth = correction_result.active_bandwidth
    current_session.bandwidth_confidence = correction_result.active_confidence
    current_session.bandwidth_source = "snooze"
    if current_session.predicted_bandwidth is None:
        current_session.predicted_bandwidth = current_bw

    # Extract correction values for response
    pre_correction = SnoozeCorrectionInfo(
        bandwidth_changed=correction_result.bandwidth_changed,
        active_bandwidth=correction_result.active_bandwidth,
        active_confidence=correction_result.active_confidence,
        predicted_bandwidth=correction_result.predicted_bandwidth,
        reason_code=correction_result.reason_code,
        suggest_clarification=correction_result.suggest_clarification,
    )

    # Record before/after bandwidth and reason codes in event context
    snooze_context: dict[str, object] = {
        "bandwidth_before": current_bw,
        "bandwidth_after": correction_result.active_bandwidth,
        "confidence_before": confidence_before,
        "confidence_after": correction_result.active_confidence,
        "bandwidth_source": "snooze",
        "reason_code": correction_result.reason_code,
        "consecutive_snoozes": consecutive_snoozes,
        "suggest_clarification": correction_result.suggest_clarification,
    }

    event = Event(
        type="snooze",
        session_id=current_session_id,
        thread_id=pending_thread_id,
        die=current_die,
        die_after=new_die,
        context=snooze_context,
        source_roll_event_id=await _find_source_roll_event(
            db, current_session_id, pending_thread_id
        ),
    )
    db.add(event)

    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None

    # Snapshot count: pre-compute before commit.
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == current_session_id)
    )
    pre_snapshot_count = result.scalar() or 0

    # Pre-fetch snoozed thread info before commit to avoid expired session reads.
    pre_snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    pre_snoozed_threads: list[SnoozedThreadInfo] = []
    if pre_snoozed_ids:
        snooze_result = await db.execute(select(Thread).where(Thread.id.in_(pre_snoozed_ids)))
        threads_by_id = {t.id: t for t in snooze_result.scalars().all()}
        pre_snoozed_threads = [
            SnoozedThreadInfo(id=sid, title=threads_by_id[sid].title)
            for sid in pre_snoozed_ids
            if sid in threads_by_id
        ]

    await db.commit()

    await invalidate_user_view(current_user.id)

    return await build_session_response(
        current_session,
        db,
        current_die=new_die,
        active_thread_id=pre_active_thread.id if pre_active_thread else None,
        active_thread_info=pre_active_thread,
        ladder_path=ladder_path,
        snapshot_count=pre_snapshot_count,
        snoozed_threads=pre_snoozed_threads,
        snoozed_thread_ids=pre_snoozed_ids,
        correction=pre_correction,
    )


@router.post("/{thread_id}/unsnooze", response_model=SessionResponse)
@limiter.limit("30/minute")
async def unsnooze_thread(
    thread_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Remove thread from snoozed list."""
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

    if thread_id not in snoozed_ids:
        return await build_session_response(current_session, db)

    snoozed_ids.remove(thread_id)
    current_session.snoozed_thread_ids = snoozed_ids

    event = Event(
        type="unsnooze",
        session_id=current_session.id,
        thread_id=thread_id,
    )
    db.add(event)

    pre_ladder_path = await build_ladder_path(current_session.id, db, session=current_session)
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == current_session.id)
    )
    pre_snapshot_count = result.scalar() or 0

    # Pre-fetch snoozed thread info before commit to avoid expired session reads.
    pre_snoozed_ids = list(snoozed_ids)
    pre_snoozed_threads: list[SnoozedThreadInfo] = []
    if pre_snoozed_ids:
        snooze_result = await db.execute(select(Thread).where(Thread.id.in_(pre_snoozed_ids)))
        threads_by_id = {t.id: t for t in snooze_result.scalars().all()}
        pre_snoozed_threads = [
            SnoozedThreadInfo(id=sid, title=threads_by_id[sid].title)
            for sid in pre_snoozed_ids
            if sid in threads_by_id
        ]

    await db.commit()

    await invalidate_user_view(current_user.id)

    return await build_session_response(
        current_session,
        db,
        ladder_path=pre_ladder_path,
        snapshot_count=pre_snapshot_count,
        snoozed_threads=pre_snoozed_threads,
        snoozed_thread_ids=pre_snoozed_ids,
    )
