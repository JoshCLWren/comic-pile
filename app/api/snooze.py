"""Snooze API endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import build_ladder_path
from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import ActiveThreadInfo, SessionResponse
from app.schemas.session import (
    SnoozeCorrectionInfo,
    SnoozedThreadInfo,
    build_session_bandwidth_state,
    build_session_intent_state,
)
from comic_pile.bandwidth_correction import (
    classify_candidate_effort,
    compute_snooze_correction,
)
from comic_pile.dice_ladder import step_up
from comic_pile.session import get_current_die_for_session

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


async def build_session_response(
    session: SessionModel,
    db: AsyncSession,
    *,
    current_die: int | None = None,
    active_thread_id: int | None = None,
    active_thread_info: ActiveThreadInfo | None = None,
    ladder_path: str | None = None,
    snapshot_count: int | None = None,
    snoozed_threads: list[SnoozedThreadInfo] | None = None,
    snoozed_thread_ids: list[int] | None = None,
    correction: SnoozeCorrectionInfo | None = None,
) -> SessionResponse:
    """Build a SessionResponse from a session model.

    When pre-loaded values are provided, avoids redundant database queries.
    Callers that already computed die, active thread, or ladder path should
    pass them in to reduce round trips.

    Args:
        session: The session model.
        db: Database session.
        current_die: Pre-computed current die value (skips get_current_die query).
        active_thread_id: Pre-fetched active thread ID (skips event lookup).
        active_thread_info: Pre-fetched active thread info (skips thread lookup).
        ladder_path: Pre-computed ladder path string (skips event re-read).
        snapshot_count: Pre-computed snapshot count (skips COUNT query).
        snoozed_threads: Pre-fetched snoozed thread info (skips snoozed thread query).
        snoozed_thread_ids: Pre-fetched snoozed thread IDs (avoids expired session read).
        correction: Structured correction result from the most recent Snooze.

    Returns:
        A SessionResponse with all required fields populated.
    """
    if active_thread_id is not None and active_thread_info is None:
        thread = await db.get(Thread, active_thread_id)
        if thread:
            active_thread_info = ActiveThreadInfo(
                id=thread.id,
                title=thread.title,
                format=thread.format,
                issues_remaining=thread.issues_remaining,
                queue_position=thread.queue_position,
                last_rolled_result=None,
            )

    if snapshot_count is None:
        result = await db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
        )
        snapshot_count = result.scalar() or 0

    if snoozed_threads is not None and snoozed_thread_ids is not None:
        resolved_ids = snoozed_thread_ids
    else:
        snoozed_ids = session.snoozed_thread_ids or []
        resolved_ids = [sid for sid in snoozed_ids if isinstance(sid, int)]
        snoozed_threads = []
        if resolved_ids:
            result = await db.execute(select(Thread).where(Thread.id.in_(resolved_ids)))
            threads_by_id = {thread.id: thread for thread in result.scalars().all()}
            snoozed_threads = [
                SnoozedThreadInfo(id=thread_id, title=threads_by_id[thread_id].title)
                for thread_id in resolved_ids
                if thread_id in threads_by_id
            ]

    if current_die is None:
        current_die = await get_current_die_for_session(session, db)
    if ladder_path is None:
        ladder_path = await build_ladder_path(session.id, db)

    return SessionResponse(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        start_die=session.start_die,
        manual_die=session.manual_die,
        user_id=session.user_id,
        ladder_path=ladder_path,
        active_thread=active_thread_info,
        current_die=current_die,
        last_rolled_result=active_thread_info.last_rolled_result if active_thread_info else None,
        has_restore_point=snapshot_count > 0,
        snapshot_count=snapshot_count,
        snoozed_thread_ids=resolved_ids,
        snoozed_threads=snoozed_threads,
        pending_thread_id=session.pending_thread_id,
        timezone=session.timezone,
        reading_bandwidth=session.reading_bandwidth,
        reading_intent=session.reading_intent,
        reading_mode_source=session.reading_mode_source,
        reading_mode_suggested=session.reading_mode_suggested,
        bandwidth=build_session_bandwidth_state(
            predicted_bandwidth=session.predicted_bandwidth,
            active_bandwidth=session.active_bandwidth,
            confidence=session.bandwidth_confidence,
            source=session.bandwidth_source,
            mode_version=session.bandwidth_version,
        ),
        intent=build_session_intent_state(
            predicted_intent=session.predicted_intent,
            active_intent=session.active_intent,
            confidence=session.intent_confidence,
            source=session.intent_source,
            mode_version=session.intent_version,
        ),
        correction=correction,
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
                format=active_thread.format,
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
