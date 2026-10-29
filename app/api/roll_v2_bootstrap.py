"""Cold Roll-v2 bootstrap router.

This single-route module avoids importing legacy Roll mutation, explanation,
selection and mode handlers merely to render the first Roll screen. The handler
body was moved verbatim from app.api.roll to preserve session, timezone,
eligibility, recovery and projection semantics.
"""

from __future__ import annotations

import logging
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.roll_recovery import build_roll_recovery
from app.schemas.roll_v2 import RollV2BootstrapResponse, RollableThread
from app.schemas.session import (
    SessionMode,
    build_session_bandwidth_state,
    normalize_reading_mode_source,
)
from app.services.roll_service import RollService
from app.services.roll_v2_projection import get_v2_rollable_projection
from app.services.session_response import get_session_with_thread_safe
from app.services.snooze_service import derive_cross_session_excluded_thread_ids
from comic_pile.reading_session import get_current_die_for_session, get_or_create

logger = logging.getLogger(__name__)
v2_router = APIRouter(tags=["roll"])


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
        bandwidth_source=normalize_reading_mode_source(current_session.bandwidth_source),
        bandwidth_version=current_session.bandwidth_version,
        active_intent=current_session.active_intent,
        predicted_intent=current_session.predicted_intent,
        intent_confidence=current_session.intent_confidence,
        intent_source=normalize_reading_mode_source(current_session.intent_source),
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
