"""Roll API routes."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, ReadingSession, Snapshot, Thread
from app.models.user import User
from app.services.recommendation_explanation import RecommendationExplanationProjection
from app.services.roll_service import RollService
from app.services.session_response import (
    build_ladder_path,
    build_session_response,
)
from app.schemas import (
    ExplainableFactorResponse,
    OverrideRequest,
    RecommendationExplanationResponse,
    RollResponse,
    SessionResponse,
)
from app.schemas.session import (
    SnoozedThreadInfo,
    build_session_bandwidth_state,
    build_session_intent_state,
)
from comic_pile.reading_session import get_current_die_for_session, get_or_create

router = APIRouter(tags=["roll"])



@router.post("/dismiss-pending", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_pending_roll(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear any pending thread for the current session.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
    """
    from app.services.roll_service import RollService
    service = RollService(db)
    await service.execute_dismiss_pending(current_user.id)


@router.post("/skip", response_model=RollResponse)
@limiter.limit("30/minute")
async def skip_roll(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Skip the current pending roll and advance to another eligible thread.

    The skipped thread is not marked read, its read_at and ratings remain
    unchanged, and dependencies are not rewritten. The skip applies only to
    the current roll/session by excluding the pending thread from the
    immediate candidate pool; a later session may roll it again. Blocked and
    otherwise ineligible threads remain excluded via the standard pool rules.

    Args:
        request: FastAPI request for rate limiting.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        RollResponse for the newly selected thread.

    Raises:
        HTTPException: 409 when no pending roll exists, 400 when no
            alternative threads are available.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)

    skipped_thread_id = current_session.pending_thread_id
    if skipped_thread_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending roll to skip. Roll first.",
        )

    service = RollService(db)
    current_die, artifacts = await service.prepare_selection(
        current_session=current_session,
        user_id=user_id,
        extra_excluded_ids=[skipped_thread_id],
        selection_method_override="skip",
        empty_pool_detail="No alternative threads available to skip to",
    )

    # Record the skipped thread as a SKIPPED event so the session timeline and
    # narrative summary reflect the skip (issue #3706). It must be saved
    # BEFORE the replacement roll event below: readers resolve the latest
    # action by (timestamp, id), so a later skip event would hide the new
    # pending comic's rolled result and would attribute the skip to the
    # replacement roll attempt instead of the original one. Recording is
    # delegated to the service/repository layer; routers do not persist.
    await service.record_skip_outcome(
        current_session=current_session,
        thread_id=skipped_thread_id,
    )

    return await service.persist_selection(
        current_session=current_session,
        artifacts=artifacts,
        current_die=current_die,
    )


@router.post("/skip/{thread_id}/unskip", response_model=SessionResponse)
@limiter.limit("30/minute")
async def unskip_thread(
    thread_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Remove a thread from the skipped list for the current session.

    Args:
        thread_id: The ID of the thread to unskip.
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse containing the updated session.

    Raises:
        HTTPException: If no active session exists.
    """
    _ = request
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == current_user.id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
    )
    current_session = result.scalars().first()

    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session",
        )

    skipped_ids = (
        list(current_session.skipped_thread_ids) if current_session.skipped_thread_ids else []
    )

    if thread_id not in skipped_ids:
        return await build_session_response(current_session, db)

    skipped_ids.remove(thread_id)
    current_session.skipped_thread_ids = skipped_ids

    event = Event(
        type="unskip",
        session_id=current_session.id,
        thread_id=thread_id,
    )
    db.add(event)

    # Extract all session attributes before commit to avoid MissingGreenlet.
    session_id = current_session.id
    session_started_at = current_session.started_at
    session_ended_at = current_session.ended_at
    session_start_die = current_session.start_die
    session_manual_die = current_session.manual_die
    session_timezone = current_session.timezone
    session_reading_bandwidth = current_session.reading_bandwidth
    session_reading_intent = current_session.reading_intent
    session_reading_mode_source = current_session.reading_mode_source
    session_reading_mode_suggested = current_session.reading_mode_suggested
    session_active_bandwidth = current_session.active_bandwidth
    session_predicted_bandwidth = current_session.predicted_bandwidth
    session_bandwidth_confidence = current_session.bandwidth_confidence
    session_bandwidth_source = current_session.bandwidth_source
    session_bandwidth_version = current_session.bandwidth_version
    session_active_intent = current_session.active_intent
    session_predicted_intent = current_session.predicted_intent
    session_intent_confidence = current_session.intent_confidence
    session_intent_source = current_session.intent_source
    session_intent_version = current_session.intent_version
    session_pending_thread_id = current_session.pending_thread_id
    user_id = current_user.id

    # Pre-fetch ladder and snapshot count before commit
    pre_ladder_path = await build_ladder_path(session_id, db)
    snapshot_count_result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
    )
    pre_snapshot_count = snapshot_count_result.scalar() or 0

    # Pre-fetch current die before commit
    pre_current_die = await get_current_die_for_session(current_session, db)

    # Pre-fetch skipped threads info before commit
    pre_skipped_ids = list(skipped_ids)
    pre_skipped_threads: list[SnoozedThreadInfo] = []
    if pre_skipped_ids:
        skipped_result = await db.execute(select(Thread).where(Thread.id.in_(pre_skipped_ids)))
        threads_by_id = {t.id: t for t in skipped_result.scalars().all()}
        pre_skipped_threads = [
            SnoozedThreadInfo(id=sid, title=threads_by_id[sid].title)
            for sid in pre_skipped_ids
            if sid in threads_by_id
        ]

    # Pre-fetch snoozed threads info before commit
    pre_snoozed_ids = list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
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

    return SessionResponse(
        id=session_id,
        started_at=session_started_at,
        ended_at=session_ended_at,
        start_die=session_start_die,
        manual_die=session_manual_die,
        user_id=user_id,
        ladder_path=pre_ladder_path,
        active_thread=None,
        current_die=pre_current_die,
        last_rolled_result=None,
        has_restore_point=pre_snapshot_count > 0,
        snapshot_count=pre_snapshot_count,
        snoozed_thread_ids=pre_snoozed_ids,
        snoozed_threads=pre_snoozed_threads,
        skipped_thread_ids=pre_skipped_ids,
        skipped_threads=pre_skipped_threads,
        pending_thread_id=session_pending_thread_id,
        timezone=session_timezone,
        reading_bandwidth=session_reading_bandwidth,
        reading_intent=session_reading_intent,
        reading_mode_source=session_reading_mode_source,
        reading_mode_suggested=session_reading_mode_suggested,
        bandwidth=build_session_bandwidth_state(
            predicted_bandwidth=session_predicted_bandwidth,
            active_bandwidth=session_active_bandwidth,
            confidence=session_bandwidth_confidence,
            source=session_bandwidth_source,
            mode_version=session_bandwidth_version,
        ),
        intent=build_session_intent_state(
            predicted_intent=session_predicted_intent,
            active_intent=session_active_intent,
            confidence=session_intent_confidence,
            source=session_intent_source,
            mode_version=session_intent_version,
        ),
    )


@router.post("/override", response_model=RollResponse)
async def override_roll(
    request: OverrideRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Manually select a thread.

    Args:
        request: Override request containing thread_id.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        RollResponse with selected thread.

    Raises:
        HTTPException: If thread not found.
    """
    return await RollService(db).execute_override(
        thread_id=request.thread_id, current_user=current_user
    )


@router.get(
    "/events/{event_id}/recommendation-explanation",
    response_model=RecommendationExplanationResponse,
)
async def get_roll_recommendation_explanation(
    event_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RecommendationExplanationResponse:
    """Return human-readable explanations for a historical roll event.

    Derives explanations solely from the recommendation context persisted at
    roll decision time, never recomputing scores from current mutable state.
    Unknown or absent context degrades gracefully to an empty explanation list.

    Args:
        event_id: Identifier of the roll event to explain.
        current_user: Authenticated owner of the session that generated the event.
        db: Async database session.

    Returns:
        RecommendationExplanationResponse carrying the event identifier and
        ordered list of human-readable explanation factors.

    Raises:
        HTTPException 404: When the event does not exist or does not belong
            to the current user's session.
        HTTPException 422: When the event type is not ``"roll"``.
    """
    result = await db.execute(
        select(Event, ReadingSession.user_id)
        .join(ReadingSession, Event.session_id == ReadingSession.id)
        .where(Event.id == event_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )
    event, session_user_id = row
    if session_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )
    if event.type != "roll":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Event {event_id} is not a roll event",
        )

    context: dict[str, Any] | None = None
    if hasattr(event, "recommendation_context") and event.recommendation_context is not None:
        raw = event.recommendation_context
        if isinstance(raw, dict):
            context = raw
        elif isinstance(raw, str):
            try:
                context = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                context = None

    factors = RecommendationExplanationProjection.project_recommendation_context(
        context=context,
        selection_method=event.selection_method,
    )

    return RecommendationExplanationResponse(
        event_id=event_id,
        factors=[
            ExplainableFactorResponse(
                code=f.code,
                label=f.label,
                detail=f.detail,
            )
            for f in factors
        ],
    )
