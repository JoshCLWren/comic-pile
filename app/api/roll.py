"""Roll API routes."""

import json
import logging
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import Text, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Any

from app.api.session import (
    _invalidate_session_caches,
    build_ladder_path,
    get_session_with_thread_safe,
)
from app.api.snooze import build_session_response
from app.auth import get_current_user

from app.database import get_db
from app.middleware import limiter
from app.models import DependencyGroup, DependencyGroupMembership, Event, Issue, Session, Snapshot, Thread
from app.models.recommendation_context import RecommendationContext
from app.models.thread import normalize_format_value
from app.models.user import User
from app.roll_recovery import build_roll_recovery
from app.services.explanation_projection import get_primary_explanation
from app.services.reading_effort import (
    EffortEstimate,
    build_recommendation_context,
    compute_effort_estimate,
)
from app.services.recommendation_explanation import RecommendationExplanationProjection
from app.schemas import (
    ExplainableFactorResponse,
    OverrideRequest,
    RecommendationExplanationResponse,
    RollBootstrapResponse,
    RollBootstrapThread,
    RollRequest,
    RollResponse,
    SessionMode,
    SessionModeResponse,
    SessionModeUpdateRequest,
    SessionResponse,
)
from app.schemas.recommendation_context import (
    CandidateFactor,
    RecommendationContextCreate,
)
from app.schemas.session import build_session_bandwidth_state, build_session_intent_state, SnoozedThreadInfo
from app.momentum import MomentumCandidateWeight
from app.services.bandwidth_selection import select_bandwidth_weighted
from comic_pile.queue import get_bounded_roll_pool_rows
from comic_pile.recommendation_selection import (
    DEFAULT_BANDWIDTH,
    DEFAULT_INTENT,
    SelectionMode,
    normalize_bandwidth,
    normalize_intent,
    resolve_selection_mode,
    select_from_pool,
)
from comic_pile.session import get_current_die_for_session, get_or_create

router = APIRouter(tags=["roll"])

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
    current_session: Session,
    current_die: int,
    excluded_ids: list[int],
    selection_bandwidth: str,
    selection_intent: str,
    selection_method_override: str | None,
    empty_pool_detail: str = "No active threads available to roll",
) -> _SelectionArtifacts:
    """Run the weighted bounded-pool selection shared by roll and skip endpoints.

    Computes the bounded pool, runs pure-random / bandwidth / momentum
    selection, builds the per-candidate effort estimates, the JSON snapshot
    payload, the bounded-pool rolling context, and the ``Event`` and
    ``RecommendationContextCreate`` records. Returns the bundled artifacts
    without committing; the caller assigns ``pending_thread_id`` and commits.

    Args:
        db: Async database session.
        user_id: Owner of the bounded pool.
        current_session: Active session used for event linkage and stored mode.
        current_die: Current die size from the dice ladder.
        excluded_ids: Thread IDs to exclude from the bounded pool.
        selection_bandwidth: Bandwidth value to resolve a selection mode with.
        selection_intent: Intent value to resolve a selection mode with.
        selection_method_override: When set, write this as the ``Event.selection_method``
            instead of deriving it from the resolved mode. Skip uses this to label
            its draw as ``"skip"`` while preserving the underlying reason codes.
        empty_pool_detail: 400 detail message when the bounded pool is empty.
            Callers customize this for the roll vs. skip user-facing language.

    Returns:
        ``_SelectionArtifacts`` ready for the caller to commit and convert into a
        ``RollResponse``.

    Raises:
        HTTPException: 400 when the bounded pool is empty.
    """
    bounded_rows = await get_bounded_roll_pool_rows(user_id, db, current_die, excluded_ids)
    if not bounded_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=empty_pool_detail,
        )

    pool_size = len(bounded_rows)
    resolved_mode = resolve_selection_mode(selection_bandwidth, selection_intent)

    max_bonus = 0.0
    weights_applied = False
    candidate_weights: list = []
    if resolved_mode is SelectionMode.PURE_RANDOM_BYPASS:
        selection = select_from_pool(
            pool_size,
            bandwidth=selection_bandwidth,
            intent=selection_intent,
        )
        selected_index = selection.index
        candidate_weights = [
            MomentumCandidateWeight(
                candidate_id=row[0].id if isinstance(row, tuple) else row.id,
                weight=1.0,
                factors=(),
            )
            for row in bounded_rows
        ]
    else:
        session_events_result = await db.execute(
            select(Event).where(Event.session_id == current_session.id)
        )
        session_events = list(session_events_result.scalars().all())
        selected = await select_bandwidth_weighted(
            db=db,
            bounded_rows=bounded_rows,
            user_id=user_id,
            session_events=session_events,
            bandwidth=selection_bandwidth,
            intent=selection_intent,
            now=datetime.now(UTC),
        )
        selected_index = selected.selected_index
        max_bonus = selected.max_bonus
        candidate_weights = selected.weights
        weights_applied = selected.weights_applied

    if resolved_mode is not SelectionMode.PURE_RANDOM_BYPASS and weights_applied:
        if selection_bandwidth in ("light", "deep"):
            recommendation_reason_codes = ["bandwidth_weighted"]
        else:
            recommendation_reason_codes = ["momentum_weighted"]
    else:
        recommendation_reason_codes = ["pure_random"]

    selected_thread, unread_count, issue_number = bounded_rows[selected_index]
    bounded_candidate_ids = [
        row[0].id if isinstance(row, tuple) else row.id for row in bounded_rows
    ]

    selected_thread_issue_id = None
    selected_thread_issue_number = None
    if selected_thread.uses_issue_tracking() and selected_thread.next_unread_issue_id:
        if unread_count > 0 and issue_number is not None:
            selected_thread_issue_id = selected_thread.next_unread_issue_id
            selected_thread_issue_number = issue_number
        else:
            issue_result = await db.execute(
                select(Issue).where(Issue.id == selected_thread.next_unread_issue_id)
            )
            next_issue = issue_result.scalar_one_or_none()
            if next_issue and next_issue.status == "unread":
                selected_thread_issue_id = next_issue.id
                selected_thread_issue_number = next_issue.issue_number

    effort_estimates: list[EffortEstimate] = []
    for thread, _unread_count, _issue_number in bounded_rows:
        issue_id = thread.next_unread_issue_id if thread.uses_issue_tracking() else None
        effort_estimate = await compute_effort_estimate(
            db,
            user_id=user_id,
            thread_id=thread.id,
            issue_id=issue_id,
        )
        effort_estimates.append(effort_estimate)
    selected_effort_estimate = effort_estimates[selected_index]

    json_candidate_weights: list[dict[str, object]] | None = None
    json_selected_weight: float | None = None
    if candidate_weights:
        json_candidate_weights = [
            {
                "candidate_id": entry.candidate_id,
                "weight": round(float(entry.weight), 4),
                "reasons": list(entry.factors),
                "factors": list(entry.factors),
            }
            for entry in candidate_weights
        ]
        json_selected_weight = float(candidate_weights[selected_index].weight)
    recommendation_context = build_recommendation_context(
        selected_effort_estimate,
        thread_id=selected_thread.id,
        issue_id=selected_thread_issue_id,
        issue_number=selected_thread_issue_number,
        candidate_weights=json_candidate_weights,
        bandwidth=normalize_bandwidth(selection_bandwidth).value,
        bandwidth_source=current_session.bandwidth_source or "default",
        bandwidth_confidence=current_session.bandwidth_confidence or 0.0,
        random_bypass=not weights_applied,
        balanced_neutrality=not weights_applied,
        selected_weight=json_selected_weight,
    )

    if selection_method_override is not None:
        selection_method = selection_method_override
    elif resolved_mode is not SelectionMode.PURE_RANDOM_BYPASS and weights_applied:
        selection_method = "bandwidth" if selection_bandwidth in ("light", "deep") else "momentum"
    else:
        selection_method = "random"

    effort_estimate_str = (
        selected_effort_estimate.band
        if isinstance(selected_effort_estimate, EffortEstimate)
        else selected_effort_estimate
    )
    event = Event(
        type="roll",
        session_id=current_session.id,
        selected_thread_id=selected_thread.id,
        die=current_die,
        result=selected_index + 1,
        selection_method=selection_method,
        recommendation_reason_codes=recommendation_reason_codes,
        recommendation_context=recommendation_context,
        issue_id=selected_thread_issue_id,
        issue_number=selected_thread_issue_number,
        rolling_recommendation_context=_build_rolling_recommendation_context(
            die_size=current_die,
            selected_queue_position=selected_thread.queue_position,
            bounded_candidate_ids=bounded_candidate_ids,
            selected_index=selected_index,
            selection_method=selection_method,
            session_timezone=current_session.timezone,
            selected_thread_last_rating=selected_thread.last_rating,
            selected_thread_last_activity_at=selected_thread.last_activity_at,
            effort_estimate=effort_estimate_str,
        ),
    )
    db.add(event)

    logger.info(
        "roll selection mode=%s bandwidth=%s intent=%s max_bonus=%.3f pool_size=%s",
        resolved_mode.value,
        normalize_bandwidth(selection_bandwidth).value,
        normalize_intent(selection_intent).value,
        max_bonus,
        pool_size,
    )

    has_explicit_mode = bool(current_session.active_intent)
    rec_context_create = RecommendationContextCreate(
        schema_version=2,
        intent=normalize_intent(selection_intent).value,
        intent_source=current_session.intent_source or "default",
        intent_confidence=1.0 if has_explicit_mode else 0.0,
        bandwidth=normalize_bandwidth(selection_bandwidth).value,
        bandwidth_source=current_session.bandwidth_source or "default",
        bandwidth_confidence=current_session.bandwidth_confidence or 0.0,
        candidate_factors=[
            CandidateFactor(
                candidate_id=breakdown.candidate_id,
                factors=list(breakdown.factors),
                weight=breakdown.weight,
                effort_minutes=(
                    round(effort_estimate.minutes, 2)
                    if effort_estimate.minutes is not None
                    else None
                ),
                effort_band=effort_estimate.band,
                effort_source=effort_estimate.source.value,
                effort_confidence=round(effort_estimate.confidence, 3),
                effort_sample_count=effort_estimate.sample_count,
            )
            for breakdown, effort_estimate in zip(candidate_weights, effort_estimates, strict=True)
        ]
        if candidate_weights
        else None,
        final_weight=(
            candidate_weights[selected_index].weight if candidate_weights else None
        ),
        random_bypass=not weights_applied,
        balanced_neutrality=not weights_applied,
        effort_minutes=(
            round(selected_effort_estimate.minutes, 2)
            if selected_effort_estimate.minutes is not None
            else None
        ),
        effort_band=selected_effort_estimate.band,
        effort_source=selected_effort_estimate.source.value,
        effort_confidence=round(selected_effort_estimate.confidence, 3),
        effort_sample_count=selected_effort_estimate.sample_count,
    )

    return _SelectionArtifacts(
        selected_thread=selected_thread,
        unread_count=unread_count,
        issue_number=issue_number,
        selected_thread_issue_id=selected_thread_issue_id,
        selected_thread_issue_number=selected_thread_issue_number,
        bounded_rows=bounded_rows,
        selected_index=selected_index,
        bounded_candidate_ids=bounded_candidate_ids,
        candidate_weights=candidate_weights,
        selected_effort_estimate=selected_effort_estimate,
        json_candidate_weights=json_candidate_weights,
        json_selected_weight=json_selected_weight,
        recommendation_context=recommendation_context,
        recommendation_reason_codes=recommendation_reason_codes,
        selection_method=selection_method,
        event=event,
        rec_context_create=rec_context_create,
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
        Local hour (0-23) or None if timezone is invalid/unavailable.
    """
    if timezone is None:
        return None
    try:
        tz = ZoneInfo(timezone)
        return datetime.now(tz).hour
    except Exception:
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
) -> dict[str, object]:
    """Build the rolling recommendation context snapshot for a roll event.

    Args:
        die_size: Current die size at roll time
        selected_queue_position: Selected thread queue position at roll time
        bounded_candidate_ids: Bounded candidate thread IDs in exact selection order
        selected_index: Selected candidate index/result
        selection_method: Selection method (random, momentum, override)
        session_timezone: Session timezone if available
        selected_thread_last_rating: Last rating of selected thread at decision time
        selected_thread_last_activity_at: Last activity timestamp of selected thread
        effort_estimate: Optional effort estimate if available

    Returns:
        Dictionary suitable for JSON storage as rolling_recommendation_context
    """
    local_hour = _get_local_hour_from_timezone(session_timezone)

    return {
        "schema_version": 1,
        "algorithm_version": "legacy",
        "die_size": die_size,
        "selected_queue_position": selected_queue_position,
        "bounded_candidate_ids": bounded_candidate_ids,
        "selected_index": selected_index,
        "selection_method": selection_method,
        "session_timezone": session_timezone,
        "local_hour": local_hour,
        "selected_thread_last_rating": selected_thread_last_rating,
        "selected_thread_last_activity_at": selected_thread_last_activity_at.isoformat()
        if selected_thread_last_activity_at
        else None,
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

    # The active session mode is the durable, user-controlled override. A per-roll
    # request value wins when supplied; otherwise the session's canonical
    # active_bandwidth/active_intent drives selection so a manual "random" intent
    # (or any inferred mode) actually changes this roll. Legacy sessions with null
    # session mode fall back to the balanced defaults, preserving old behavior.
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
        excluded_ids=[*snoozed_ids, *skipped_ids],
        selection_bandwidth=selection_bandwidth,
        selection_intent=selection_intent,
        selection_method_override=None,
    )

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
        if artifacts.rec_context_create.candidate_factors
        else None,
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
    await _invalidate_session_caches(current_user.id)

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
    current_session = await get_or_create(db, user_id=current_user.id, existing_user=current_user)
    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None
    await db.commit()

    await _invalidate_session_caches(current_user.id)


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

    artifacts = await _select_pending_thread(
        db=db,
        user_id=user_id,
        current_session=current_session,
        current_die=current_die,
        excluded_ids=[*snoozed_ids, skipped_thread_id],
        selection_bandwidth=current_session.active_bandwidth or DEFAULT_BANDWIDTH,
        selection_intent=current_session.active_intent or DEFAULT_INTENT,
        selection_method_override="skip",
        empty_pool_detail="No alternative threads available to skip to",
    )

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
        if artifacts.rec_context_create.candidate_factors
        else None,
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
    # Advance pending to the newly selected thread; do not mark the skipped
    # issue/thread as read and do not mutate dependencies.
    current_session.pending_thread_id = artifacts.selected_thread.id
    current_session.pending_thread_updated_at = datetime.now(UTC)

    await db.commit()
    await _invalidate_session_caches(current_user.id)

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
        select(Session)
        .where(Session.user_id == current_user.id)
        .where(Session.ended_at.is_(None))
        .order_by(Session.started_at.desc())
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
    await _invalidate_session_caches(user_id)

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
    result = await db.execute(
        select(Thread)
        .where(Thread.id == request.thread_id)
        .where(Thread.user_id == current_user.id)
        .with_for_update()
    )
    override_thread = result.scalar_one_or_none()
    if not override_thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {request.thread_id} not found",
        )

    if override_thread.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Thread {request.thread_id} is blocked and cannot be selected",
        )

    if override_thread.status != "active":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Thread {request.thread_id} is {override_thread.status} and cannot be selected",
        )

    current_session = await get_or_create(db, user_id=current_user.id, existing_user=current_user)
    current_session_id = current_session.id
    current_die = await get_current_die_for_session(current_session, db)

    override_thread_id = override_thread.id
    override_thread_title = override_thread.title
    override_thread_format = normalize_format_value(override_thread.format)
    override_thread_queue_position = override_thread.queue_position

    override_thread_issues_remaining = await override_thread.get_issues_remaining(db)

    override_thread_total_issues = override_thread.total_issues
    override_thread_reading_progress = override_thread.reading_progress
    override_thread_next_unread_issue_id = override_thread.next_unread_issue_id

    # For override we don't have the enriched pool row; resolve directly.
    override_thread_issue_id = None
    override_thread_issue_number = None
    if override_thread.uses_issue_tracking() and override_thread_next_unread_issue_id:
        issue_result = await db.execute(
            select(Issue).where(Issue.id == override_thread_next_unread_issue_id)
        )
        next_issue = issue_result.scalar_one_or_none()
        if next_issue and next_issue.status == "unread":
            override_thread_issue_id = next_issue.id
            override_thread_issue_number = next_issue.issue_number

    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )

    if override_thread_id in snoozed_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {override_thread_id} is snoozed. Please unsnooze it first before overriding.",
        )

    # Decision-time context is purely observational: it records the estimate
    # that existed when this roll happened and never changes the selection.
    effort_estimate = await compute_effort_estimate(
        db,
        user_id=current_user.id,
        thread_id=override_thread_id,
        issue_id=override_thread_issue_id,
    )
    # Versioned JSON context for override: single bounded candidate, neutral
    # weighting but explicit manual-override bandwidth source (issue #1718).
    override_candidate_weights: list[dict[str, object]] = [
        {
            "candidate_id": override_thread_id,
            "weight": 1.0,
            "reasons": [],
            "factors": [],
        }
    ]
    recommendation_context = build_recommendation_context(
        effort_estimate,
        thread_id=override_thread_id,
        issue_id=override_thread_issue_id,
        issue_number=override_thread_issue_number,
        candidate_weights=override_candidate_weights,
        bandwidth="balanced",
        bandwidth_source="manual_override",
        bandwidth_confidence=1.0,
        random_bypass=False,
        balanced_neutrality=True,
        selected_weight=1.0,
    )

    # Extract effort estimate band as string for JSON serialization
    effort_estimate_str = effort_estimate.band if isinstance(effort_estimate, EffortEstimate) else effort_estimate

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=override_thread_id,
        die=current_die,
        result=0,
        selection_method="override",
        recommendation_reason_codes=[],
        recommendation_context=recommendation_context,
        issue_id=override_thread_issue_id,
        issue_number=override_thread_issue_number,
        rolling_recommendation_context=_build_rolling_recommendation_context(
            die_size=current_die,
            selected_queue_position=override_thread_queue_position,
            bounded_candidate_ids=[override_thread_id],
            selected_index=0,
            selection_method="override",
            session_timezone=current_session.timezone,
            selected_thread_last_rating=override_thread.last_rating,
            selected_thread_last_activity_at=override_thread.last_activity_at,
            effort_estimate=effort_estimate_str,
        ),
    )
    db.add(event)

    # Record recommendation context for override selection
    # Override is a manual selection, not a weighted recommendation
    context_data = RecommendationContextCreate(
        schema_version=2,
        intent="balanced",
        intent_source="manual_override",
        intent_confidence=1.0,
        bandwidth="balanced",
        bandwidth_source="manual_override",
        bandwidth_confidence=1.0,
        candidate_factors=None,
        final_weight=1.0,
        random_bypass=False,
        balanced_neutrality=True,
        effort_minutes=round(effort_estimate.minutes, 2) if effort_estimate.minutes is not None else None,
        effort_band=effort_estimate.band,
        effort_source=effort_estimate.source.value,
        effort_confidence=round(effort_estimate.confidence, 3),
        effort_sample_count=effort_estimate.sample_count,
    )

    # Flush event to get its ID for the recommendation context FK
    await db.flush()

    rec_context = RecommendationContext(
        event_id=event.id,
        schema_version=context_data.schema_version,
        intent=context_data.intent,
        intent_source=context_data.intent_source,
        intent_confidence=context_data.intent_confidence,
        bandwidth=context_data.bandwidth,
        bandwidth_source=context_data.bandwidth_source,
        bandwidth_confidence=context_data.bandwidth_confidence,
        candidate_factors=[f.model_dump() for f in context_data.candidate_factors]
        if context_data.candidate_factors
        else None,
        final_weight=context_data.final_weight,
        random_bypass=context_data.random_bypass,
        balanced_neutrality=context_data.balanced_neutrality,
        effort_minutes=context_data.effort_minutes,
        effort_band=context_data.effort_band,
        effort_source=context_data.effort_source,
        effort_confidence=context_data.effort_confidence,
        effort_sample_count=context_data.effort_sample_count,
    )
    db.add(rec_context)

    current_session.pending_thread_id = override_thread_id
    current_session.pending_thread_updated_at = datetime.now(UTC)

    await db.commit()
    await _invalidate_session_caches(current_user.id)

    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

    return RollResponse(
        thread_id=override_thread_id,
        title=override_thread_title,
        format=override_thread_format,
        issues_remaining=override_thread_issues_remaining,
        queue_position=override_thread_queue_position,
        die_size=current_die,
        result=0,
        offset=offset,
        snoozed_count=snoozed_count,
        issue_id=override_thread_issue_id,
        issue_number=override_thread_issue_number,
        next_issue_id=override_thread_issue_id,
        next_issue_number=override_thread_issue_number,
        total_issues=override_thread_total_issues,
        reading_progress=override_thread_reading_progress,
        explanation=get_primary_explanation([]),
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

    await _invalidate_session_caches(current_user.id)
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

    await _invalidate_session_caches(current_user.id)

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
    await _invalidate_session_caches(current_user.id)

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
            unset and never break the bootstrap response.

    Returns:
        RollBootstrapResponse with session state, bounded pool, snoozed/blocked/stale summaries.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    await db.refresh(current_session)

    # Capture browser IANA timezone once for the active session if not already set.
    # Invalid values fail safely: the field remains unset and roll continues.
    if timezone is not None and current_session.timezone is None:
        try:
            candidate_timezone = timezone.strip()
            if candidate_timezone and len(candidate_timezone) <= 100:
                # Resolving through ZoneInfo rejects malformed identifiers such as
                # "Not/AZone" while accepting real IANA names like "America/Chicago".
                ZoneInfo(candidate_timezone)
                current_session.timezone = candidate_timezone
                await db.commit()
                await db.refresh(current_session)
        except Exception:
            # Any failure during timezone persistence must not break roll.
            pass

    current_session_id = current_session.id

    # Extract bandwidth state before any further awaits; nullable columns on
    # legacy sessions serialize to a safe all-null canonical shape.
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
    roll_recovery = await build_roll_recovery(
        db,
        user_id=user_id,
        pending_thread_id=pending_thread_id,
        pending_thread_title=pending_thread_title,
    )

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

    snoozed_ids = list(current_session.snoozed_thread_ids or [])
    skipped_ids = list(current_session.skipped_thread_ids or [])
    if snoozed_ids:
        pool_query = pool_query.where(Thread.id.not_in(snoozed_ids))
    if skipped_ids:
        pool_query = pool_query.where(Thread.id.not_in(skipped_ids))

    pool_result = await db.execute(pool_query)
    pool_rows = pool_result.all()

    roll_pool = [
        RollBootstrapThread(
            id=row.id,
            title=row.title,
            format=normalize_format_value(row.format),
            issue_id=row.issue_id,
            issue_number=row.issue_number,
            route_labels=list(row.route_labels or []),
        )
        for row in pool_rows
    ]

    snoozed_threads: list[RollBootstrapThread] = []
    if snoozed_ids:
        snoozed_result = await db.execute(
            select(Thread.id, Thread.title, Thread.format)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(snoozed_ids))
        )
        snoozed_threads = [
            RollBootstrapThread(
                id=row.id, title=row.title, format=normalize_format_value(row.format)
            )
            for row in snoozed_result.all()
        ]

    skipped_threads: list[RollBootstrapThread] = []
    if skipped_ids:
        skipped_result = await db.execute(
            select(Thread.id, Thread.title, Thread.format)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(skipped_ids))
        )
        skipped_threads = [
            RollBootstrapThread(
                id=row.id, title=row.title, format=normalize_format_value(row.format)
            )
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
        RollBootstrapThread(
            id=row.id, title=row.title, format=normalize_format_value(row.format)
        )
        for row in blocked_result.all()
    ]
    snoozed_count = len(snoozed_threads)
    snoozed_threads = snoozed_threads[:RollBootstrapResponse.summary_limit]
    blocked_threads = blocked_threads[:RollBootstrapResponse.summary_limit]
    skipped_threads = skipped_threads[:RollBootstrapResponse.summary_limit]

    stale_cutoff = datetime.now(UTC) - timedelta(days=7)
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
            chosen_id = random.choice(stale_ids)
            stale_detail_result = await db.execute(
                select(Thread.id, Thread.title, Thread.format, Thread.last_activity_at)
                .where(Thread.id == chosen_id)
            )
            stale_row = stale_detail_result.first()
            if stale_row:
                stale_last_activity = (
                    stale_row.last_activity_at.isoformat()
                    if stale_row.last_activity_at
                    else None
                )
                stale_thread = RollBootstrapThread(
                    id=stale_row.id,
                    title=stale_row.title,
                    format=normalize_format_value(stale_row.format),
                    last_activity_at=stale_last_activity,
                )

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
        select(Event, Session.user_id)
        .join(Session, Event.session_id == Session.id)
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
