"""Roll API routes."""

import logging
import random
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread
from app.models.user import User
from app.schemas import OverrideRequest, RollResponse
from comic_pile.queue import get_roll_pool
from comic_pile.session import get_current_die, get_or_create

router = APIRouter(tags=["roll"])

clear_cache = None
logger = logging.getLogger(__name__)


@router.post("/", response_model=RollResponse)
@limiter.limit("30/minute")
async def roll_dice(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Roll dice to select a thread.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        RollResponse with selected thread and die result.

    Raises:
        HTTPException: If no active threads available.
    """
    user_id = current_user.id
    current_session = await get_or_create(db, user_id=user_id)
    current_session_id = current_session.id

    if current_session.pending_thread_id is not None:
        pending_thread = await db.get(Thread, current_session.pending_thread_id)
        pending_title = pending_thread.title if pending_thread else f"Thread {current_session.pending_thread_id}"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A roll is already pending for '{pending_title}'. "
                "Rate, snooze, or cancel the pending roll before rolling again."
            ),
        )

    current_die = await get_current_die(current_session_id, db)

    # Exclude snoozed threads from the pool
    snoozed_ids = current_session.snoozed_thread_ids or []
    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

    threads = await get_roll_pool(user_id, db, snoozed_ids)
    if not threads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )

    pool_size = min(current_die, len(threads))
    selected_index = random.randint(0, pool_size - 1)
    selected_thread = threads[selected_index]

    selected_thread_id = selected_thread.id
    selected_thread_title = selected_thread.title
    selected_thread_format = selected_thread.format
    selected_thread_issues_remaining = selected_thread.issues_remaining
    selected_thread_queue_position = selected_thread.queue_position

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=selected_thread_id,
        die=current_die,
        result=selected_index + 1,
        selection_method="random",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = selected_thread_id
        current_session.pending_thread_updated_at = datetime.now(UTC)

    await db.commit()
    if clear_cache:
        clear_cache()

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
    current_session = await get_or_create(db, user_id=current_user.id)
    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None
    await db.commit()

    if clear_cache:
        clear_cache()


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
    )
    override_thread = result.scalar_one_or_none()
    if not override_thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {request.thread_id} not found",
        )

    current_session = await get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = await get_current_die(current_session_id, db)

    override_thread_id = override_thread.id
    override_thread_title = override_thread.title
    override_thread_format = override_thread.format
    override_thread_issues_remaining = override_thread.issues_remaining
    override_thread_queue_position = override_thread.queue_position

    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

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

    if override_thread_id in snoozed_ids:
        snoozed_ids.remove(override_thread_id)
        current_session.snoozed_thread_ids = snoozed_ids
        offset = len(snoozed_ids)
        snoozed_count = len(snoozed_ids)

    await db.commit()
    if clear_cache:
        clear_cache()

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
    )


@router.post("/set-die", response_class=HTMLResponse)
async def set_manual_die(
    die: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Set manual die size for current session.

    Args:
        die: The die size to set (must be 4, 6, 8, 10, 12, or 20).
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        HTML string with the die size.

    Raises:
        HTTPException: If die size is invalid.
    """
    current_session = await get_or_create(db, user_id=current_user.id)

    if die not in [4, 6, 8, 10, 12, 20]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid die size. Must be one of: 4, 6, 8, 10, 12, 20",
        )

    current_session.manual_die = die
    await db.commit()

    if clear_cache:
        clear_cache()

    return f"d{die}"


@router.post("/clear-manual-die", response_class=HTMLResponse)
async def clear_manual_die(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Clear manual die size and return to automatic dice ladder mode.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        HTML string with the current die size.
    """
    current_session = await get_or_create(db, user_id=current_user.id)

    current_session.manual_die = None
    await db.commit()

    if clear_cache:
        clear_cache()

    await db.refresh(current_session)
    current_die = await get_current_die(current_session.id, db)
    return f"d{current_die}"
