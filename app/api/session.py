"""Session API endpoints."""

from __future__ import annotations

import asyncio
from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import ReadingSession, Snapshot, Thread, User
from app.schemas import (
    CorrectionSheetExamplesResponse,
    SessionListItem,
    SessionResponse,
)
from app.schemas.session import (
    SnoozedThreadInfo,
    build_session_bandwidth_state,
    build_session_intent_state,
)
from app.services.session_response import (
    build_ladder_path,
    get_active_thread,
    get_session_with_thread_safe,
)
from app.services.reading_session_service import get_reading_session_service, ReadingSessionService
from app.services.correction_examples import generate_correction_examples
from comic_pile.reading_session import get_current_die, get_or_create, is_active

router = APIRouter(tags=["sessions"])
#: Versioned-only surface for new session client resources. ``app.main`` mounts
#: this router *before* :data:`router` at the ``/api/v1/sessions`` prefix so a
#: literal path always wins over the ``/{session_id}`` parameter route, and it
#: is never mounted under bare ``/api/*`` (see docs/API.md and the convention
#: comment in app/main.py).
v1_router = APIRouter(tags=["sessions"])


class _RateAggregate(TypedDict):
    """Aggregated rating-event state for one session history row."""

    issues_read: int
    last_rating: float | None


def _to_session_list_item(sr: SessionResponse) -> SessionListItem:
    """Convert a full SessionResponse to a narrow SessionListItem.

    Deliberately drops snoozed_thread_ids, snoozed_threads, and pending_thread_id
    to reduce payload size for session history list views.
    """
    return SessionListItem(
        id=sr.id,
        started_at=sr.started_at,
        ended_at=sr.ended_at,
        start_die=sr.start_die,
        manual_die=sr.manual_die,
        user_id=sr.user_id,
        ladder_path=sr.ladder_path,
        active_thread=sr.active_thread,
        current_die=sr.current_die,
        last_rolled_result=sr.last_rolled_result,
        has_restore_point=sr.has_restore_point,
        snapshot_count=sr.snapshot_count,
    )


@router.get("/current/")
@limiter.limit("200/minute")
async def get_current_session(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Get current active session with deadlock retry handling.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse with current session details.

    Raises:
        RuntimeError: If failed after max retries.
    """
    from sqlalchemy.exc import OperationalError

    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            active_session_result = await db.execute(
                select(ReadingSession)
                .where(ReadingSession.user_id == current_user.id)
                .where(ReadingSession.ended_at.is_(None))
                .order_by(ReadingSession.started_at.desc(), ReadingSession.id.desc())
                .limit(1)
            )
            active_session = active_session_result.scalars().first()

            if active_session is None or not await is_active(
                active_session.started_at, active_session.ended_at, db
            ):
                # Extract timezone from request header
                timezone = request.headers.get("X-Browser-Timezone")
                active_session = await get_or_create(db, user_id=current_user.id, timezone=timezone)

            await db.refresh(active_session)
            active_session_id = active_session.id
            _, active_thread = await get_session_with_thread_safe(active_session_id, db)

            from sqlalchemy import func

            snapshot_count_result = await db.execute(
                select(func.count())
                .select_from(Snapshot)
                .where(Snapshot.session_id == active_session_id)
            )
            snapshot_count = snapshot_count_result.scalar() or 0

            snoozed_threads = []
            snoozed_ids = active_session.snoozed_thread_ids or []
            if snoozed_ids:
                snoozed_result = await db.execute(select(Thread).where(Thread.id.in_(snoozed_ids)))
                snoozed_threads = [
                    SnoozedThreadInfo(id=thread.id, title=thread.title)
                    for thread in snoozed_result.scalars().all()
                ]

            return SessionResponse(
                id=active_session_id,
                started_at=active_session.started_at,
                ended_at=active_session.ended_at,
                start_die=active_session.start_die,
                manual_die=active_session.manual_die,
                user_id=active_session.user_id,
                ladder_path=await build_ladder_path(active_session_id, db),
                active_thread=active_thread,
                current_die=await get_current_die(active_session_id, db),
                last_rolled_result=active_thread.last_rolled_result if active_thread else None,
                has_restore_point=snapshot_count > 0,
                snapshot_count=snapshot_count,
                snoozed_thread_ids=active_session.snoozed_thread_ids or [],
                snoozed_threads=snoozed_threads,
                pending_thread_id=active_session.pending_thread_id,
                timezone=active_session.timezone,
                reading_bandwidth=active_session.reading_bandwidth,
                reading_intent=active_session.reading_intent,
                reading_mode_source=active_session.reading_mode_source,
                reading_mode_suggested=active_session.reading_mode_suggested,
                bandwidth=build_session_bandwidth_state(
                    predicted_bandwidth=active_session.predicted_bandwidth,
                    active_bandwidth=active_session.active_bandwidth,
                    confidence=active_session.bandwidth_confidence,
                    source=active_session.bandwidth_source,
                    mode_version=active_session.bandwidth_version,
                ),
                intent=build_session_intent_state(
                    predicted_intent=active_session.predicted_intent,
                    active_intent=active_session.active_intent,
                    confidence=active_session.intent_confidence,
                    source=active_session.intent_source,
                    mode_version=active_session.intent_version,
                ),
            )
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                await db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise
                delay = initial_delay * (2 ** (retries - 1))
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to get current session after {max_retries} retries")


@router.post("/{session_id}/restore-session-start")
async def restore_reading_session_start(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    session_service: ReadingSessionService = Depends(get_reading_session_service),
) -> SessionResponse:
    """Restore session to its initial state at session start.

    Args:
        session_id: The session ID to restore.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
        session_service: Session service for business logic.

    Returns:
        SessionResponse with restored session details.

    Raises:
        HTTPException: If session or snapshot not found.
        RuntimeError: If failed after max retries.
    """
    session = await session_service.restore_reading_session_start(session_id, current_user.id)


    active_thread = await get_active_thread(session.id, db)

    snapshot_count_result = await db.execute(
        select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session.id)
    )
    snapshot_count = snapshot_count_result.scalar() or 0

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
    )


@v1_router.get("/correction-examples", response_model=CorrectionSheetExamplesResponse)
@limiter.limit("60/minute")
async def get_correction_sheet_examples(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CorrectionSheetExamplesResponse:
    """Get personalized examples for the correction sheet steering choices.

    Returns compact examples drawn from the user's own rated/read history for
    each correction sheet option. Examples are explanatory only and do not
    constrain the canonical recommendation behavior. Returns null for options
    where no honest example exists.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        CorrectionSheetExamplesResponse with examples for each choice.
    """
    return await generate_correction_examples(db, current_user.id)
