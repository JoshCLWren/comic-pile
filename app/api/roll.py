"""Roll API routes."""

import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, ReadingSession, Snapshot, Thread
from app.models.recommendation_context import RecommendationContext
from app.models.thread import normalize_format_value
from app.models.user import User
from app.roll_recovery import build_roll_recovery
from app.services.explanation_projection import get_primary_explanation
from app.services.reading_effort import (
    EffortEstimate,
)
from app.services.recommendation_explanation import RecommendationExplanationProjection
from app.services.roll_service import RollService
from app.services.session_response import (
    build_ladder_path,
    build_session_response,
    get_session_with_thread_safe,
)
from app.services.snooze_service import (
    derive_cross_session_excluded_thread_ids,
    derive_effective_roll_excluded_thread_ids,
)
from app.schemas import (
    ExplainableFactorResponse,
    OverrideRequest,
    RecommendationExplanationResponse,
    RollBootstrapResponse,
    RollRequest,
    RollResponse,
    SessionMode,
    SessionModeResponse,
    SessionModeUpdateRequest,
    SessionResponse,
)
from app.schemas.roll_v2 import (
    RollV2BootstrapResponse,
    RollableThread,
)
from app.services.roll_v2_projection import get_v2_rollable_projection
from app.services.tag_inheritance_service import TagInheritanceService
from app.schemas.recommendation_context import (
    RecommendationContextCreate,
)
from app.schemas.session import build_session_bandwidth_state, build_session_intent_state, SnoozedThreadInfo
from comic_pile.recommendation_selection import (
    DEFAULT_BANDWIDTH,
    DEFAULT_INTENT,
)
from comic_pile.recommendation_version import (
    CONTROL_MODE_CONTEXTUAL,
    RECOMMENDATION_ALGORITHM_VERSION,
)
from comic_pile.reading_session import get_current_die_for_session, get_or_create
from app.services.dependency_service import get_blocking_details

router = APIRouter(tags=["roll"])
v2_router = APIRouter(tags=["roll"])
logger = logging.getLogger(__name__)


class _SelectionArtifacts:
    """Bundle the per-selection work shared between ``roll_dice`` and ``skip_roll``.

    Holds the bounded-pool selection, effort estimates, recommendation
    snapshot, and the ``Event``/``RecommendationContext`` rows that both
    endpoints write. Callers commit and wire the result into a
    ``RollResponse`` after the helper returns.
    """

    def __init__(
        self,
        *,
        selected_thread: Thread,
        unread_count: int,
        issue_number: str | None,
        selected_thread_issue_id: int | None,
        selected_thread_issue_number: str | None,
        bounded_rows: list[tuple[Thread, int, str | None]],
        selected_index: int,
        bounded_candidate_ids: list[int],
        candidate_weights: list,
        selected_effort_estimate: EffortEstimate,
        json_candidate_weights: list[dict[str, object]] | None,
        json_selected_weight: float | None,
        recommendation_context: dict[str, object],
        recommendation_reason_codes: list[str],
        selection_method: str,
        event: Event,
        rec_context_create: RecommendationContextCreate,
    ) -> None:
        self.selected_thread = selected_thread
        self.unread_count = unread_count
        self.issue_number = issue_number
        self.selected_thread_issue_id = selected_thread_issue_id
        self.selected_thread_issue_number = selected_thread_issue_number
        self.bounded_rows = bounded_rows
        self.selected_index = selected_index
        self.bounded_candidate_ids = bounded_candidate_ids
        self.candidate_weights = candidate_weights
        self.selected_effort_estimate = selected_effort_estimate
        self.json_candidate_weights = json_candidate_weights
        self.json_selected_weight = json_selected_weight
        self.recommendation_context = recommendation_context
        self.recommendation_reason_codes = recommendation_reason_codes
        self.selection_method = selection_method
        self.event = event
        self.rec_context_create = rec_context_create


async def _select_pending_thread(
    *,
    db: AsyncSession,
    user_id: int,
    current_session: ReadingSession,
    current_die: int,
    excluded_ids: list[int],
    selection_bandwidth: str,
    selection_intent: str,
    selection_method_override: str | None,
    empty_pool_detail: str = "No active threads available to roll",
) -> _SelectionArtifacts:
    """Run the weighted bounded-pool selection shared by roll and skip endpoints.

    Delegates to ``RollService.select_pending_thread`` and wraps the
    result in a ``_SelectionArtifacts`` instance.
    """
    service = RollService(db)
    artifacts = await service.select_pending_thread(
        user_id=user_id,
        current_session=current_session,
        current_die=current_die,
        excluded_ids=excluded_ids,
        selection_bandwidth=selection_bandwidth,
        selection_intent=selection_intent,
        selection_method_override=selection_method_override,
        empty_pool_detail=empty_pool_detail,
    )
    return _SelectionArtifacts(
        selected_thread=artifacts["selected_thread"],
        unread_count=artifacts["unread_count"],
        issue_number=artifacts["issue_number"],
        selected_thread_issue_id=artifacts["selected_thread_issue_id"],
        selected_thread_issue_number=artifacts["selected_thread_issue_number"],
        bounded_rows=artifacts["bounded_rows"],
        selected_index=artifacts["selected_index"],
        bounded_candidate_ids=artifacts["bounded_candidate_ids"],
        candidate_weights=artifacts["candidate_weights"],
        selected_effort_estimate=artifacts["selected_effort_estimate"],
        json_candidate_weights=artifacts["json_candidate_weights"],
        json_selected_weight=artifacts["json_selected_weight"],
        recommendation_context=artifacts["recommendation_context"],
        recommendation_reason_codes=artifacts["recommendation_reason_codes"],
        selection_method=artifacts["selection_method"],
        event=artifacts["event"],
        rec_context_create=artifacts["rec_context_create"],
    )


def _build_roll_response(
    *,
    artifacts: _SelectionArtifacts,
    current_die: int,
    snoozed_count: int,
) -> RollResponse:
    """Convert shared selection artifacts into the public ``RollResponse``."""
    selected_thread = artifacts.selected_thread
    return RollResponse(
        thread_id=selected_thread.id,
        title=selected_thread.title,
        format=normalize_format_value(selected_thread.format),
        issues_remaining=artifacts.unread_count,
        queue_position=selected_thread.queue_position,
        die_size=current_die,
        result=artifacts.selected_index + 1,
        offset=snoozed_count,
        snoozed_count=snoozed_count,
        issue_id=artifacts.selected_thread_issue_id,
        issue_number=artifacts.selected_thread_issue_number,
        next_issue_id=artifacts.selected_thread_issue_id,
        next_issue_number=artifacts.selected_thread_issue_number,
        total_issues=selected_thread.total_issues,
        reading_progress=selected_thread.reading_progress,
        explanation=get_primary_explanation(artifacts.recommendation_reason_codes),
    )


def _get_local_hour_from_timezone(timezone: str | None) -> int | None:
    """Derive local hour from session timezone for recommendation context.

    Args:
        timezone: IANA timezone string (e.g., "America/Chicago")

    Returns:
        Local hour (0-23) or None if timezone is invalid/unavailable. Invalid or
        unavailable timezone values are soft failures: the error is logged and the
        caller continues with no local-hour signal.

    """
    if timezone is None:
        return None
    try:
        tz = ZoneInfo(timezone)
        return datetime.now(tz).hour
    except Exception:
        logger.exception("Failed to derive local hour from timezone %s", timezone)
        return None


def _build_rolling_recommendation_context(
    *,
    die_size: int,
    selected_queue_position: int,
    bounded_candidate_ids: list[int],
    selected_index: int,
    selection_method: str,
    session_timezone: str | None,
    selected_thread_last_rating: float | None,
    selected_thread_last_activity_at: datetime | None,
    effort_estimate: str | None = None,
    algorithm_version: str | None = None,
    control_mode: str | None = None,
) -> dict[str, object]:
    """Build the rolling recommendation context snapshot for a roll event.

    Args:
        die_size: Current die size at roll time
        selected_queue_position: Selected thread queue position at roll time
        bounded_candidate_ids: Bounded candidate thread IDs in exact selection order
        selected_index: Selected candidate index/result
        selection_method: Selection method (random, momentum, bandwidth, override,
            skip, or forced legacy)
        session_timezone: Session timezone if available
        selected_thread_last_rating: Last rating of selected thread at decision time
        selected_thread_last_activity_at: Last activity timestamp of selected thread
        effort_estimate: Optional effort estimate if available
        algorithm_version: Canonical algorithm version at decision time; when
            absent the active contextual version is recorded
        control_mode: Operator control mode at decision time; when absent the
            contextual control mode is recorded

    Returns:
        Dictionary suitable for JSON storage as rolling_recommendation_context
    """
    local_hour = _get_local_hour_from_timezone(session_timezone)
    return {
        "schema_version": 1,
        "algorithm_version": algorithm_version or RECOMMENDATION_ALGORITHM_VERSION,
        "control_mode": control_mode or CONTROL_MODE_CONTEXTUAL,
        "die_size": die_size,
        "selected_queue_position": selected_queue_position,
        "bounded_candidate_ids": bounded_candidate_ids,
        "selected_index": selected_index,
        "selection_method": selection_method,
        "session_timezone": session_timezone,
        "local_hour": local_hour,
        "selected_thread_last_rating": selected_thread_last_rating,
        "selected_thread_last_activity_at": selected_thread_last_activity_at.isoformat()
        if selected_thread_last_activity_at else None,
        "effort_estimate": effort_estimate,
    }


@router.post("/", response_model=RollResponse)
@limiter.limit("30/minute")
async def roll_dice(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    roll_request: RollRequest = Body(default_factory=RollRequest),
) -> RollResponse:
    """Roll dice to select a thread.

    Args:
        roll_request: The roll request.
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        RollResponse with selected thread and die result.

    Raises:
        HTTPException: If no active threads available.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)

    if current_session.pending_thread_id is not None:
        pending_thread_result = await db.execute(
            select(Thread.title)
            .where(Thread.id == current_session.pending_thread_id)
            .where(Thread.user_id == user_id)
        )
        pending_title = pending_thread_result.scalar_one_or_none()
        pending_reference = f"'{pending_title}'" if pending_title else "another thread"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A roll is already pending for {pending_reference}. "
                "Rate, snooze, or cancel the pending roll before rolling again."
            ),
        )

    current_die = await get_current_die_for_session(current_session, db)

    snoozed_ids = current_session.snoozed_thread_ids or []
    skipped_ids = current_session.skipped_thread_ids or []

    excluded_ids = await derive_effective_roll_excluded_thread_ids(
        db,
        user_id,
        session_snoozed_ids=snoozed_ids,
        session_skipped_ids=skipped_ids,
    )

    selection_bandwidth = (
        roll_request.bandwidth
        if roll_request.bandwidth is not None
        else (current_session.active_bandwidth or DEFAULT_BANDWIDTH)
    )
    selection_intent = (
        roll_request.intent
        if roll_request.intent is not None
        else (current_session.active_intent or DEFAULT_INTENT)
    )

    artifacts = await _select_pending_thread(
        db=db,
        user_id=user_id,
        current_session=current_session,
        current_die=current_die,
        excluded_ids=excluded_ids,
        selection_bandwidth=selection_bandwidth,
        selection_intent=selection_intent,
        selection_method_override=None,
    )

    db.add(artifacts.event)
    await db.flush()
    rec_context = RecommendationContext(
        event_id=artifacts.event.id,
        schema_version=artifacts.rec_context_create.schema_version,
        intent=artifacts.rec_context_create.intent,
        intent_source=artifacts.rec_context_create.intent_source,
        intent_confidence=artifacts.rec_context_create.intent_confidence,
        bandwidth=artifacts.rec_context_create.bandwidth,
        bandwidth_source=artifacts.rec_context_create.bandwidth_source,
        bandwidth_confidence=artifacts.rec_context_create.bandwidth_confidence,
        candidate_factors=[f.model_dump() for f in artifacts.rec_context_create.candidate_factors]
        if artifacts.rec_context_create.candidate_factors else None,
        final_weight=artifacts.rec_context_create.final_weight,
        random_bypass=artifacts.rec_context_create.random_bypass,
        balanced_neutrality=artifacts.rec_context_create.balanced_neutrality,
        effort_minutes=artifacts.rec_context_create.effort_minutes,
        effort_band=artifacts.rec_context_create.effort_band,
        effort_source=artifacts.rec_context_create.effort_source,
        effort_confidence=artifacts.rec_context_create.effort_confidence,
        effort_sample_count=artifacts.rec_context_create.effort_sample_count,
    )
    db.add(rec_context)
    current_session.pending_thread_id = artifacts.selected_thread.id
    current_session.pending_thread_updated_at = datetime.now(UTC)

    await db.commit()

    return _build_roll_response(
        artifacts=artifacts,
        current_die=current_die,
        snoozed_count=len(snoozed_ids),
    )


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

    current_die = await get_current_die_for_session(current_session, db)

    snoozed_ids = current_session.snoozed_thread_ids or []
    existing_skipped_ids = list(current_session.skipped_thread_ids or [])

    excluded_ids = await derive_effective_roll_excluded_thread_ids(
        db,
        user_id,
        session_snoozed_ids=snoozed_ids,
        session_skipped_ids=existing_skipped_ids,
    )

    artifacts = await _select_pending_thread(
        db=db,
        user_id=user_id,
        current_session=current_session,
        current_die=current_die,
        excluded_ids=[*excluded_ids, skipped_thread_id],
        selection_bandwidth=current_session.active_bandwidth or DEFAULT_BANDWIDTH,
        selection_intent=current_session.active_intent or DEFAULT_INTENT,
        selection_method_override="skip",
        empty_pool_detail="No alternative threads available to skip to",
    )

    db.add(artifacts.event)
    await db.flush()
    rec_context = RecommendationContext(
        event_id=artifacts.event.id,
        schema_version=artifacts.rec_context_create.schema_version,
        intent=artifacts.rec_context_create.intent,
        intent_source=artifacts.rec_context_create.intent_source,
        intent_confidence=artifacts.rec_context_create.intent_confidence,
        bandwidth=artifacts.rec_context_create.bandwidth,
        bandwidth_source=artifacts.rec_context_create.bandwidth_source,
        bandwidth_confidence=artifacts.rec_context_create.bandwidth_confidence,
        candidate_factors=[f.model_dump() for f in artifacts.rec_context_create.candidate_factors]
        if artifacts.rec_context_create.candidate_factors else None,
        final_weight=artifacts.rec_context_create.final_weight,
        random_bypass=artifacts.rec_context_create.random_bypass,
        balanced_neutrality=artifacts.rec_context_create.balanced_neutrality,
        effort_minutes=artifacts.rec_context_create.effort_minutes,
        effort_band=artifacts.rec_context_create.effort_band,
        effort_source=artifacts.rec_context_create.effort_source,
        effort_confidence=artifacts.rec_context_create.effort_confidence,
        effort_sample_count=artifacts.rec_context_create.effort_sample_count,
    )
    db.add(rec_context)
    if skipped_thread_id not in existing_skipped_ids:
        existing_skipped_ids.append(skipped_thread_id)
        current_session.skipped_thread_ids = existing_skipped_ids
    current_session.pending_thread_id = artifacts.selected_thread.id
    current_session.pending_thread_updated_at = datetime.now(UTC)

    await db.commit()

    return _build_roll_response(
        artifacts=artifacts,
        current_die=current_die,
        snoozed_count=len(snoozed_ids),
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
    result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
    )
    pre_snapshot_count = result.scalar() or 0

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


@router.post("/set-die", response_class=HTMLResponse)
async def set_manual_die(
    die: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Set manual die size for current session.

    Args:
        die: The die size to set (must be one of: 4, 6, 8, 10, 12, 20, 30, 50, or 100).
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        HTML string with the die size.

    Raises:
        HTTPException: If die size is invalid.
    """
    current_session = await get_or_create(db, user_id=current_user.id, existing_user=current_user)

    if die not in [4, 6, 8, 10, 12, 20, 30, 50, 100]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid die size. Must be one of: 4, 6, 8, 10, 12, 20, 30, 50, 100",
        )

    current_session.manual_die = die
    await db.commit()
    return f"d{die}"


@router.post("/clear-manual-die", response_class=HTMLResponse)
async def clear_manual_die(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Clear manual die size and return to automatic dice ladder mode.

    Args:
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        HTML string with the current die size.
    """
    current_session = await get_or_create(db, user_id=current_user.id, existing_user=current_user)

    current_session.manual_die = None
    await db.commit()

    await db.refresh(current_session)
    current_die = await get_current_die_for_session(current_session, db)
    return f"d{current_die}"


@router.patch("/session-mode", response_model=SessionModeResponse)
@limiter.limit("60/minute")
async def update_session_mode(
    request: Request,
    mode_update: SessionModeUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionModeResponse:
    """Update the active session's bandwidth and/or intent.

    Only the supplied dimensions are changed. Omitting both is a no-op and
    returns the current mode state. Changed dimensions are marked with source
    ``manual`` and a call-level version tag so the frontend can distinguish
    user overrides from algorithm predictions.

    Args:
        mode_update: The mode values to apply. Omitted dimensions are not reset.
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionModeResponse with the updated canonical mode state.
    """
    current_session = await get_or_create(db, user_id=current_user.id, existing_user=current_user)

    active_bandwidth = current_session.active_bandwidth
    predicted_bandwidth = current_session.predicted_bandwidth
    bandwidth_confidence = current_session.bandwidth_confidence
    bandwidth_source = current_session.bandwidth_source
    bandwidth_version = current_session.bandwidth_version
    active_intent = current_session.active_intent
    predicted_intent = current_session.predicted_intent
    intent_confidence = current_session.intent_confidence
    intent_source = current_session.intent_source
    intent_version = current_session.intent_version
    guidance = current_session.session_mode_correction_guidance
    session_id = current_session.id

    version_tag = f"manual-{int(datetime.now(UTC).timestamp())}"

    changed_dimensions: list[str] = []

    if mode_update.bandwidth is not None:
        current_session.active_bandwidth = mode_update.bandwidth
        current_session.predicted_bandwidth = mode_update.bandwidth
        current_session.bandwidth_source = "manual"
        current_session.bandwidth_confidence = 1.0
        current_session.bandwidth_version = version_tag
        active_bandwidth = mode_update.bandwidth
        predicted_bandwidth = mode_update.bandwidth
        bandwidth_source = "manual"
        bandwidth_confidence = 1.0
        bandwidth_version = version_tag
        changed_dimensions.append("bandwidth")

    if mode_update.intent is not None:
        current_session.active_intent = mode_update.intent
        current_session.predicted_intent = mode_update.intent
        current_session.intent_source = "manual"
        current_session.intent_confidence = 1.0
        current_session.intent_version = version_tag
        active_intent = mode_update.intent
        predicted_intent = mode_update.intent
        intent_source = "manual"
        intent_confidence = 1.0
        intent_version = version_tag
        changed_dimensions.append("intent")

    if changed_dimensions:
        db.add(
            Event(
                session_id=session_id,
                type="session_mode",
                die=None,
                selected_thread_id=None,
                thread_id=None,
                issue_id=None,
                context={
                    "source": "manual",
                    "changed": changed_dimensions,
                    "bandwidth": active_bandwidth,
                    "intent": active_intent,
                    "version": version_tag,
                },
            )
        )
    await db.commit()

    return SessionModeResponse(
        active_bandwidth=active_bandwidth,
        predicted_bandwidth=predicted_bandwidth,
        bandwidth_confidence=bandwidth_confidence,
        bandwidth_source=bandwidth_source,
        bandwidth_version=bandwidth_version,
        active_intent=active_intent,
        predicted_intent=predicted_intent,
        intent_confidence=intent_confidence,
        intent_source=intent_source,
        intent_version=intent_version,
        session_mode_correction_guidance=guidance,
    )


@router.get("/bootstrap", response_model=RollBootstrapResponse)
async def roll_bootstrap(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    timezone: str | None = Query(default=None, description="Browser IANA timezone identifier"),
) -> RollBootstrapResponse:
    """Return bounded bootstrap data for the Roll initial render.

    Replaces the need for separate session, full-thread-library, and stale-thread requests
    by returning only the retained data required for the first interactive screen.

    Args:
        current_user: The authenticated user.
        db: Async database session.
        timezone: Optional browser-resolved IANA timezone identifier captured once
            per active reading session. Invalid or unusable values leave the field
            unset and never break the roll.

    Returns:
        RollBootstrapResponse with session state, bounded pool, snoozed/blocked/stale summaries.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    await db.refresh(current_session)

    if timezone is not None and current_session.timezone is None:
        try:
            candidate_timezone = timezone.strip()
            if candidate_timezone and len(candidate_timezone) <= 100:
                ZoneInfo(candidate_timezone)
                current_session.timezone = candidate_timezone
                await db.commit()
                await db.refresh(current_session)
        except Exception:
            logger.exception("Failed to update session timezone from browser value %s", timezone)

    current_session_id = current_session.id

    bandwidth_state = build_session_bandwidth_state(
        predicted_bandwidth=current_session.predicted_bandwidth,
        active_bandwidth=current_session.active_bandwidth,
        confidence=current_session.bandwidth_confidence,
        source=current_session.bandwidth_source,
        mode_version=current_session.bandwidth_version,
    )

    _, active_thread = await get_session_with_thread_safe(current_session_id, db)

    die_size = await get_current_die_for_session(current_session, db)
    manual_die = current_session.manual_die
    pending_thread_id = current_session.pending_thread_id
    session_mode = SessionMode(
        active_bandwidth=current_session.active_bandwidth,
        predicted_bandwidth=current_session.predicted_bandwidth,
        bandwidth_confidence=current_session.bandwidth_confidence,
        bandwidth_source=current_session.bandwidth_source,
        bandwidth_version=current_session.bandwidth_version,
        active_intent=current_session.active_intent,
        predicted_intent=current_session.predicted_intent,
        intent_confidence=current_session.intent_confidence,
        intent_source=current_session.intent_source,
        intent_version=current_session.intent_version,
        session_mode_correction_guidance=current_session.session_mode_correction_guidance,
    )
    last_rolled_result = active_thread.last_rolled_result if active_thread else None
    pending_thread_title = (
        active_thread.title
        if active_thread is not None and active_thread.id == pending_thread_id
        else None
    )
    derived_snoozed_ids = await derive_cross_session_excluded_thread_ids(db, user_id)
    roll_recovery = await build_roll_recovery(
        db,
        user_id=user_id,
        pending_thread_id=pending_thread_id,
        pending_thread_title=pending_thread_title,
        excluded_thread_ids=frozenset(
            set(current_session.snoozed_thread_ids or [])
            | set(current_session.skipped_thread_ids or [])
            | derived_snoozed_ids
        ),
    )

    # Issue #3375: every thread-shaped section of this response is one
    # batched read answered by the service layer, so the query count no
    # longer scales with the size of the library.
    snoozed_ids = list(current_session.snoozed_thread_ids or [])
    skipped_ids = list(current_session.skipped_thread_ids or [])

    bootstrap_data = await RollService(db).load_bootstrap_thread_data(
        user_id=user_id,
        die_size=die_size,
        snoozed_ids=snoozed_ids,
        skipped_ids=skipped_ids,
        derived_snoozed_ids=derived_snoozed_ids,
        summary_limit=RollBootstrapResponse.summary_limit,
    )

    roll_pool = bootstrap_data.roll_pool
    snoozed_threads = bootstrap_data.snoozed_threads
    skipped_threads = bootstrap_data.skipped_threads
    blocked_threads = bootstrap_data.blocked_threads
    blocked_count = bootstrap_data.blocked_count
    stale_thread = bootstrap_data.stale_thread
    stale_thread_count = bootstrap_data.stale_thread_count
    library = bootstrap_data.library

    snoozed_count = len(snoozed_threads)
    snoozed_threads = snoozed_threads[:RollBootstrapResponse.summary_limit]
    blocked_threads = blocked_threads[:RollBootstrapResponse.summary_limit]
    skipped_threads = skipped_threads[:RollBootstrapResponse.summary_limit]

    # One bounded tag read for every thread this bootstrap returns (issue
    # #3425), so Roll rows show tags without a query per face. Threads have no
    # parents in v1, so these are the directly assigned visible tags.
    bootstrap_threads = [*roll_pool, *snoozed_threads, *skipped_threads, *blocked_threads]
    if stale_thread is not None:
        bootstrap_threads.append(stale_thread)
    tags_by_thread = await TagInheritanceService(db).get_threads_direct_tags(
        user_id, [thread.id for thread in bootstrap_threads]
    )
    for thread in bootstrap_threads:
        thread.tags = tags_by_thread.get(thread.id, [])

    excluded = library.excluded

    # Attach human-readable blocking detail where it exists, then
    # materialize the bounded exclusion lists for the response. Every
    # active row is either available or excluded and every completed
    # row is excluded, so total - available always equals the union of
    # all exclusion reasons.
    if library.blocked_ids:
        blocking_map = await get_blocking_details(
            sorted(library.blocked_ids), user_id, db
        )
        for tid, explanation in (blocking_map or {}).items():
            if tid in excluded and explanation.blocking_reasons:
                excluded[tid].detail = explanation.blocking_reasons[0]

    total_threads = library.total_threads
    available_threads = len(library.available_ids)
    excluded_list = list(excluded.values())
    excluded_count = len(excluded_list)
    inactive_count = len(library.inactive)

    return RollBootstrapResponse(
        current_die=die_size,
        manual_die=manual_die,
        pending_thread_id=pending_thread_id,
        last_rolled_result=last_rolled_result,
        session_mode=session_mode,
        active_thread=active_thread,
        roll_recovery=roll_recovery,
        bandwidth=bandwidth_state,
        roll_pool=roll_pool,
        snoozed_threads=snoozed_threads,
        snoozed_count=snoozed_count,
        skipped_thread_ids=skipped_ids,
        skipped_threads=skipped_threads,
        blocked_count=blocked_count,
        blocked_threads=blocked_threads,
        stale_thread_count=stale_thread_count,
        stale_thread=stale_thread,
        session_id=current_session_id,
        user_id=user_id,
        timezone=current_session.timezone,

        # Issue #3125: exclusion transparency.
        total_threads=total_threads,
        available_threads=available_threads,
        excluded_count=excluded_count,
        excluded_threads=excluded_list,
        inactive_count=inactive_count,
        inactive_threads=library.inactive,
    )


@v2_router.get("/bootstrap", response_model=RollV2BootstrapResponse)
async def roll_v2_bootstrap(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    timezone: str | None = Query(default=None, description="Browser IANA timezone identifier"),
) -> RollV2BootstrapResponse:
    """Return v2 bootstrap data for the Roll initial render.
    
    This is a breaking sibling of the existing bootstrap with no unversioned alias.
    It provides a superset response replacing roll_pool with rollable[] and adding
    nullable session-scoped last_read while preserving all v1 semantics.
    
    Args:
        current_user: The authenticated user.
        db: Async database session.
        timezone: Optional browser-resolved IANA timezone identifier captured once
            per active reading session. Invalid or unusable values leave the field
            unset and never break the roll.
    
    Returns:
        RollV2BootstrapResponse with v2 contract including rollable and last_read.
    """
    # Reuse the existing bootstrap logic to get v1 data
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    await db.refresh(current_session)

    if timezone is not None and current_session.timezone is None:
        try:
            candidate_timezone = timezone.strip()
            if candidate_timezone and len(candidate_timezone) <= 100:
                ZoneInfo(candidate_timezone)
                current_session.timezone = candidate_timezone
                await db.commit()
                await db.refresh(current_session)
        except Exception:
            logger.exception("Failed to update session timezone from browser value %s", timezone)

    current_session_id = current_session.id

    bandwidth_state = build_session_bandwidth_state(
        predicted_bandwidth=current_session.predicted_bandwidth,
        active_bandwidth=current_session.active_bandwidth,
        confidence=current_session.bandwidth_confidence,
        source=current_session.bandwidth_source,
        mode_version=current_session.bandwidth_version,
    )

    _, active_thread = await get_session_with_thread_safe(current_session_id, db)

    die_size = await get_current_die_for_session(current_session, db)
    manual_die = current_session.manual_die
    pending_thread_id = current_session.pending_thread_id
    session_mode = SessionMode(
        active_bandwidth=current_session.active_bandwidth,
        predicted_bandwidth=current_session.predicted_bandwidth,
        bandwidth_confidence=current_session.bandwidth_confidence,
        bandwidth_source=current_session.bandwidth_source,
        bandwidth_version=current_session.bandwidth_version,
        active_intent=current_session.active_intent,
        predicted_intent=current_session.predicted_intent,
        intent_confidence=current_session.intent_confidence,
        intent_source=current_session.intent_source,
        intent_version=current_session.intent_version,
        session_mode_correction_guidance=current_session.session_mode_correction_guidance,
    )
    last_rolled_result = active_thread.last_rolled_result if active_thread else None
    pending_thread_title = (
        active_thread.title
        if active_thread is not None and active_thread.id == pending_thread_id
        else None
    )
    derived_snoozed_ids = await derive_cross_session_excluded_thread_ids(db, user_id)
    roll_recovery = await build_roll_recovery(
        db,
        user_id=user_id,
        pending_thread_id=pending_thread_id,
        pending_thread_title=pending_thread_title,
        excluded_thread_ids=frozenset(
            set(current_session.snoozed_thread_ids or [])
            | set(current_session.skipped_thread_ids or [])
            | derived_snoozed_ids
        ),
    )

    # Bounded v2 projection (issue #2717): rollable[] and session last-read
    # come from three bulk read-model round trips with no per-row queries.
    # Session/recovery/partition semantics above stay identical to #2716.
    snoozed_ids = list(current_session.snoozed_thread_ids or [])
    skipped_ids = list(current_session.skipped_thread_ids or [])
    effective_snoozed_ids = sorted(set(snoozed_ids) | set(derived_snoozed_ids))
    excluded_thread_ids = sorted(set(effective_snoozed_ids) | set(skipped_ids))
    rollable, last_read, _omitted_thread_ids = await get_v2_rollable_projection(
        db,
        user_id=user_id,
        die_size=die_size,
        excluded_thread_ids=excluded_thread_ids,
        session_id=current_session_id,
    )

    summary = await RollService(db).load_bootstrap_thread_data(
        user_id=user_id,
        die_size=die_size,
        snoozed_ids=snoozed_ids,
        skipped_ids=skipped_ids,
        derived_snoozed_ids=derived_snoozed_ids,
        summary_limit=RollV2BootstrapResponse.summary_limit,
        include_pool=False,
    )
    snoozed_threads = [
        RollableThread.model_validate(row.model_dump()) for row in summary.snoozed_threads
    ]
    skipped_threads = [
        RollableThread.model_validate(row.model_dump()) for row in summary.skipped_threads
    ]
    blocked_threads = [
        RollableThread.model_validate(row.model_dump()) for row in summary.blocked_threads
    ]
    blocked_count = summary.blocked_count
    stale_thread_count = summary.stale_thread_count
    stale_thread = (
        RollableThread.model_validate(summary.stale_thread.model_dump())
        if summary.stale_thread is not None
        else None
    )

    return RollV2BootstrapResponse(
        current_die=die_size,
        manual_die=manual_die,
        pending_thread_id=pending_thread_id,
        last_rolled_result=last_rolled_result,
        session_mode=session_mode,
        active_thread=active_thread,
        roll_recovery=roll_recovery,
        bandwidth=bandwidth_state,
        rollable=rollable,  # New v2 field replacing roll_pool
        last_read=last_read,  # New nullable session-scoped field
        snoozed_threads=snoozed_threads,
        snoozed_count=len(snoozed_threads),
        skipped_thread_ids=skipped_ids,
        skipped_threads=skipped_threads,
        blocked_count=blocked_count,
        blocked_threads=blocked_threads,
        stale_thread_count=stale_thread_count,
        stale_thread=stale_thread,
        session_id=current_session_id,
        user_id=user_id,
        timezone=current_session.timezone,
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
