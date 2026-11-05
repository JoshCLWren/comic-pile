"""Roll API routes."""

import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, ReadingSession, Thread
from app.models.recommendation_context import RecommendationContext
from app.models.user import User
from app.services.reading_effort import (
    EffortEstimate,
)
from app.services.recommendation_explanation import RecommendationExplanationProjection
from app.services.roll_service import RollService
from app.services.roll_phase_trace import RollPhaseTrace
from app.services.snooze_service import (
    derive_effective_roll_excluded_thread_ids,
)
from app.schemas import (
    ExplainableFactorResponse,
    OverrideRequest,
    RecommendationExplanationResponse,
    RollRequest,
    RollResponse,
)
from app.schemas.recommendation_context import (
    RecommendationContextCreate,
)
from comic_pile.recommendation_selection import (
    DEFAULT_BANDWIDTH,
    DEFAULT_INTENT,
)
from comic_pile.recommendation_version import (
    CONTROL_MODE_CONTEXTUAL,
    RECOMMENDATION_ALGORITHM_VERSION,
)
from comic_pile.reading_session import get_current_die_for_session, get_or_create

router = APIRouter(tags=["roll"])

logger = logging.getLogger(__name__)


class _SelectionArtifacts:
    """Bundle the per-selection work for ``roll_dice``.

    Holds the bounded-pool selection, effort estimates, recommendation
    snapshot, and the ``Event``/``RecommendationContext`` rows the endpoint
    writes. Callers commit and wire the result into a ``RollResponse`` after
    the helper returns.
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
        candidate_weights: list[object],
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
    empty_pool_detail: str = "No active threads available to roll",
    trace: RollPhaseTrace | None = None,
) -> _SelectionArtifacts:
    """Run the weighted bounded-pool selection for the roll endpoint.

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
        empty_pool_detail=empty_pool_detail,
        trace=trace,
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
    trace = RollPhaseTrace()
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    trace.mark("session")

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
    trace.mark("die_exclusions")

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
        trace=trace,
    )

    db.add(artifacts.event)
    await db.flush()
    trace.mark("event_flush")
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

    # Project before commit so the Queue ordinal reuses this transaction's
    # canonical Option E snapshot. A post-commit projection reloaded all
    # eligibility inputs solely to populate the response's queue_position.
    response = await RollService(db).build_roll_response(
        selected_thread=artifacts.selected_thread,
        current_die=current_die,
        selected_index=artifacts.selected_index,
        unread_count=artifacts.unread_count,
        snoozed_count=len(snoozed_ids),
        issue_id=artifacts.selected_thread_issue_id,
        issue_number=artifacts.selected_thread_issue_number,
        next_issue_id=artifacts.selected_thread_issue_id,
        next_issue_number=artifacts.selected_thread_issue_number,
        recommendation_reason_codes=artifacts.recommendation_reason_codes,
    )
    trace.mark("response")

    # Only expose the prepared response after the event, recommendation
    # context, and pending pointer have committed successfully.
    await db.commit()
    trace.mark("commit")
    trace.emit(logger)
    return response


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
