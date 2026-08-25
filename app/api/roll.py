"""Roll API routes."""

import json
import logging
import random
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import Text, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Any

from app.api.session import (
    _invalidate_session_caches,
    get_session_with_thread_safe,
)
from app.auth import get_current_user

from app.database import get_db
from app.middleware import limiter
from app.models import DependencyGroup, DependencyGroupMembership, Event, Issue, Session, Thread
from app.models.user import User
from app.roll_recovery import build_roll_recovery
from app.services.explanation_projection import get_primary_explanation
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
)
from app.schemas.session import build_session_bandwidth_state
from comic_pile.queue import get_bounded_roll_pool_rows
from comic_pile.recommendation_weights import (
    BANDWIDTH_DEEP,
    BANDWIDTH_LIGHT,
    WeightedCandidate,
    build_candidate_weights,
    choose_weighted_index,
)
from comic_pile.session import get_current_die_for_session, get_or_create
from app.momentum import compute_momentum_bonus, weighted_momentum_selection

router = APIRouter(tags=["roll"])

logger = logging.getLogger(__name__)


def _weighted_rng() -> random.Random:
    """Create the RNG used for weighted selection.

    Returns:
        A freshly seeded :class:`random.Random`. Isolated as a function so
        regression tests can substitute a seeded instance.
    """
    return random.Random()


def _serialize_weighting(
    bandwidth: str,
    candidates: list[WeightedCandidate],
) -> dict[str, object]:
    """Serialize candidate weights and reason codes for durable roll evidence."""
    return {
        "bandwidth": bandwidth,
        "candidates": [
            {
                "position": candidate.position,
                "thread_id": candidate.thread_id,
                "effort_minutes": candidate.effort_minutes,
                "band": candidate.band,
                "weight": candidate.weight,
                "reason": candidate.reasons[0] if candidate.reasons else "",
                "reasons": list(candidate.reasons),
            }
            for candidate in candidates
        ],
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
    current_session_id = current_session.id

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

    bounded_rows = await get_bounded_roll_pool_rows(user_id, db, current_die, snoozed_ids)
    if not bounded_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )

    session_events_result = await db.execute(
        select(Event).where(Event.session_id == current_session_id)
    )
    session_events = list(session_events_result.scalars().all())

    requested_bandwidth = roll_request.bandwidth
    bandwidth_value = requested_bandwidth if requested_bandwidth is not None else None

    weighting_payload: dict[str, object] | None = None
    recommendation_reason_codes: list[str]
    selection_method: str

    if bandwidth_value == BANDWIDTH_LIGHT or bandwidth_value == BANDWIDTH_DEEP:
        candidates = build_candidate_weights(
            [(row[0].id, row[0].estimated_minutes) for row in bounded_rows],
            bandwidth_value,
        )
        bonuses: list[float] = []
        for row in bounded_rows:
            thread_obj = row[0] if isinstance(row, tuple) else row
            bonus = compute_momentum_bonus(
                thread=thread_obj,
                session_events=session_events,
                last_rating=thread_obj.last_rating,
                now=datetime.now(UTC),
            )
            bonuses.append(bonus)
        max_bonus = max(bonuses) if bonuses else 0.0
        combined_weights = [
            (1.0 + bonus) * candidate.weight
            for bonus, candidate in zip(bonuses, candidates, strict=True)
        ]
        selected_index = choose_weighted_index(combined_weights, _weighted_rng())
        weighting_payload = _serialize_weighting(bandwidth_value, candidates)
        selection_method = f"bandwidth_{bandwidth_value}"
        if max_bonus > 0:
            recommendation_reason_codes = ["momentum_weighted", f"bandwidth_{bandwidth_value}"]
        else:
            recommendation_reason_codes = [f"bandwidth_{bandwidth_value}"]
    else:
        selected_index, max_bonus = await weighted_momentum_selection(
            db=db,
            bounded_rows=bounded_rows,
            user_id=user_id,
            session_events=session_events,
            now=datetime.now(UTC),
        )
        recommendation_reason_codes = (
            ["momentum_weighted"] if max_bonus > 0 else ["pure_random"]
        )
        selection_method = "momentum" if max_bonus > 0 else "random"

    selected_thread, unread_count, issue_number = bounded_rows[selected_index]

    selected_thread_id = selected_thread.id
    selected_thread_title = selected_thread.title
    selected_thread_format = selected_thread.format
    selected_thread_queue_position = selected_thread.queue_position

    selected_thread_issues_remaining = unread_count

    selected_thread_total_issues = selected_thread.total_issues
    selected_thread_reading_progress = selected_thread.reading_progress
    selected_thread_next_unread_issue_id = selected_thread.next_unread_issue_id

    selected_thread_issue_id = None
    selected_thread_issue_number = None
    if selected_thread.uses_issue_tracking() and selected_thread_next_unread_issue_id:
        if unread_count > 0 and issue_number is not None:
            selected_thread_issue_id = selected_thread_next_unread_issue_id
            selected_thread_issue_number = issue_number
        else:
            issue_result = await db.execute(
                select(Issue).where(Issue.id == selected_thread_next_unread_issue_id)
            )
            next_issue = issue_result.scalar_one_or_none()
            if next_issue and next_issue.status == "unread":
                selected_thread_issue_id = next_issue.id
                selected_thread_issue_number = next_issue.issue_number

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=selected_thread_id,
        die=current_die,
        result=selected_index + 1,
        selection_method=selection_method,
        recommendation_reason_codes=recommendation_reason_codes,
        issue_id=selected_thread_issue_id,
        issue_number=selected_thread_issue_number,
        bandwidth_weighting_json=weighting_payload,
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = selected_thread_id
        current_session.pending_thread_updated_at = datetime.now(UTC)

    await db.commit()
    await _invalidate_session_caches(current_user.id)

    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

    return RollResponse(
        thread_id=selected_thread_id,
        title=selected_thread_title,
        format=selected_thread_format,
        issues_remaining=selected_thread_issues_remaining,
        queue_position=selected_thread_queue_position,
        die_size=current_die,
        result=selected_index + 1,
        offset=offset,
        snoozed_count=snoozed_count,
        issue_id=selected_thread_issue_id,
        issue_number=selected_thread_issue_number,
        next_issue_id=selected_thread_issue_id,
        next_issue_number=selected_thread_issue_number,
        total_issues=selected_thread_total_issues,
        reading_progress=selected_thread_reading_progress,
        explanation=get_primary_explanation(recommendation_reason_codes),
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
    override_thread_format = override_thread.format
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

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=override_thread_id,
        die=current_die,
        result=0,
        selection_method="override",
        recommendation_reason_codes=[],
        issue_id=override_thread_issue_id,
        issue_number=override_thread_issue_number,
    )
    db.add(event)

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
        die: The die size to set (must be 4, 6, 8, 10, 12, 20, 30, 50, or 100).
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

    Raises:
        HTTPException: If an invalid enum value is supplied.
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

    if mode_update.bandwidth is not None:
        current_session.active_bandwidth = mode_update.bandwidth
        current_session.predicted_bandwidth = mode_update.bandwidth
        current_session.bandwidth_source = "manual"
        current_session.bandwidth_version = version_tag
        active_bandwidth = mode_update.bandwidth
        predicted_bandwidth = mode_update.bandwidth
        bandwidth_source = "manual"
        bandwidth_version = version_tag

    if mode_update.intent is not None:
        current_session.active_intent = mode_update.intent
        current_session.predicted_intent = mode_update.intent
        current_session.intent_source = "manual"
        current_session.intent_version = version_tag
        active_intent = mode_update.intent
        predicted_intent = mode_update.intent
        intent_source = "manual"
        intent_version = version_tag

    db.add(
        Event(
            session_id=session_id,
            type="session_mode",
            die=None,
            selected_thread_id=None,
            thread_id=None,
            issue_id=None,
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
) -> RollBootstrapResponse:
    """Return bounded bootstrap data for the Roll initial render.

    Replaces the need for separate session, full-thread-library, and stale-thread requests
    by returning only the retained data required for the first interactive screen.

    Args:
        current_user: The authenticated user.
        db: Async database session.

    Returns:
        RollBootstrapResponse with session state, bounded pool, snoozed/blocked/stale summaries.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id, existing_user=current_user)
    await db.refresh(current_session)

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
    if snoozed_ids:
        pool_query = pool_query.where(Thread.id.not_in(snoozed_ids))

    pool_result = await db.execute(pool_query)
    pool_rows = pool_result.all()

    roll_pool = [
        RollBootstrapThread(
            id=row.id,
            title=row.title,
            format=row.format,
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
            RollBootstrapThread(id=row.id, title=row.title, format=row.format)
            for row in snoozed_result.all()
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
        RollBootstrapThread(id=row.id, title=row.title, format=row.format)
        for row in blocked_result.all()
    ]
    snoozed_count = len(snoozed_threads)
    snoozed_threads = snoozed_threads[:RollBootstrapResponse.summary_limit]
    blocked_threads = blocked_threads[:RollBootstrapResponse.summary_limit]

    stale_cutoff = datetime.now(UTC) - timedelta(days=7)
    effective_activity = func.coalesce(Thread.last_activity_at, Thread.created_at)
    stale_count_result = await db.execute(
        select(func.count())
        .select_from(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked.is_(False))
        .where(effective_activity < stale_cutoff)
    )
    stale_thread_count = stale_count_result.scalar() or 0

    stale_thread = None
    if stale_thread_count > 0:
        stale_result = await db.execute(
            select(Thread.id, Thread.title, Thread.format, Thread.last_activity_at)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.is_blocked.is_(False))
            .where(effective_activity < stale_cutoff)
            .order_by(effective_activity.asc())
            .limit(1)
        )
        stale_row = stale_result.first()
        if stale_row:
            stale_last_activity = (
                stale_row.last_activity_at.isoformat() if stale_row.last_activity_at else None
            )
            stale_thread = RollBootstrapThread(
                id=stale_row.id,
                title=stale_row.title,
                format=stale_row.format,
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
        blocked_count=blocked_count,
        blocked_threads=blocked_threads,
        stale_thread_count=stale_thread_count,
        stale_thread=stale_thread,
        session_id=current_session_id,
        user_id=user_id,
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
