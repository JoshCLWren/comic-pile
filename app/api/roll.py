"""Roll API routes."""

import logging
import random
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import Text, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.api.session import (
    _invalidate_session_caches,
    get_session_with_thread_safe,
)
from app.auth import get_current_user

from app.database import get_db
from app.middleware import limiter
from app.models import DependencyGroup, DependencyGroupMembership, Event, Issue, Thread
from app.models.user import User
from app.roll_recovery import build_roll_recovery
from app.schemas import (
    OverrideRequest,
    RollBootstrapResponse,
    RollBootstrapThread,
    RollRequest,
    RollResponse,
    SessionModeState,
    SessionModeUpdateRequest,
)
from app.services.reading_mode import (
    apply_manual_mode_change,
    build_mode_state,
)
from comic_pile.queue import get_roll_pool_rows
from comic_pile.session import get_current_die_for_session, get_or_create

router = APIRouter(tags=["roll"])

logger = logging.getLogger(__name__)


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

    rows = await get_roll_pool_rows(user_id, db, snoozed_ids)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )

    # Bound the selection to the current die size, matching original semantics.
    bounded_rows = rows[:current_die]
    pool_size = len(bounded_rows)
    selected_index = random.randint(0, pool_size - 1)
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
        selection_method="random",
        context={
            "bandwidth": current_session.bandwidth,
            "intent": current_session.intent,
            # Phase 5 keeps every intent on the bounded unweighted control path;
            # `random` is the explicit escape hatch to that same legacy behavior.
            "control_path": (
                "random_escape_hatch"
                if current_session.intent == "random"
                else "legacy_unweighted"
            ),
        },
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

    _, active_thread = await get_session_with_thread_safe(current_session_id, db)

    die_size = await get_current_die_for_session(current_session, db)
    manual_die = current_session.manual_die
    pending_thread_id = current_session.pending_thread_id
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
        active_thread=active_thread,
        roll_recovery=roll_recovery,
        roll_pool=roll_pool,
        snoozed_threads=snoozed_threads,
        snoozed_count=len(snoozed_threads),
        blocked_count=blocked_count,
        blocked_threads=blocked_threads,
        stale_thread_count=stale_thread_count,
        stale_thread=stale_thread,
        session_id=current_session_id,
        user_id=user_id,
        session_mode=build_mode_state(current_session),
    )


@router.post("/session-mode", response_model=SessionModeState)
async def update_session_mode(
    mode_request: SessionModeUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionModeState:
    """Explicitly change the active session's bandwidth and/or intent.

    This is the one canonical mutation for manual reading-mode changes. Omitted
    dimensions are preserved, changed dimensions are marked with source
    ``manual``, and a compact ``mode_change`` event records the transition.

    Args:
        mode_request: Optional bandwidth and/or intent values to apply.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The canonical updated SessionModeState.
    """
    current_session = await get_or_create(db, user_id=current_user.id, existing_user=current_user)

    previous_bandwidth = current_session.bandwidth
    previous_intent = current_session.intent

    updated_mode = apply_manual_mode_change(
        current_session,
        bandwidth=mode_request.bandwidth,
        intent=mode_request.intent,
    )

    changed_dimensions: dict[str, dict[str, str | None]] = {}
    if mode_request.bandwidth is not None and mode_request.bandwidth != previous_bandwidth:
        changed_dimensions["bandwidth"] = {
            "from": previous_bandwidth,
            "to": mode_request.bandwidth,
        }
    if mode_request.intent is not None and mode_request.intent != previous_intent:
        changed_dimensions["intent"] = {"from": previous_intent, "to": mode_request.intent}

    event = Event(
        type="mode_change",
        session_id=current_session.id,
        context={
            "source": "manual",
            "changed": changed_dimensions,
            "bandwidth": updated_mode.bandwidth,
            "intent": updated_mode.intent,
            "mode_version": updated_mode.mode_version,
        },
    )
    db.add(event)

    await db.commit()
    await _invalidate_session_caches(current_user.id)

    return updated_mode