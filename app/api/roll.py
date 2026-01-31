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
    """Roll dice to select a thread."""
    threads = await get_roll_pool(current_user.id, db)
    if not threads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )

    current_session = await get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = await get_current_die(current_session_id, db)

    # Exclude snoozed threads from the pool
    snoozed_ids = current_session.snoozed_thread_ids or []
    threads = [t for t in threads if t.id not in snoozed_ids]

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
        die_size=current_die,
        result=selected_index + 1,
    )


@router.post("/override", response_model=RollResponse)
async def override_roll(
    request: OverrideRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Manually select a thread."""
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

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=override_thread_id,
        die=current_die,
        result=0,
        selection_method="override",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = override_thread_id
        current_session.pending_thread_updated_at = datetime.now(UTC)

        snoozed_ids = (
            list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
        )
        if override_thread_id in snoozed_ids:
            snoozed_ids.remove(override_thread_id)
            current_session.snoozed_thread_ids = snoozed_ids

        await db.commit()
        if clear_cache:
            clear_cache()

    return RollResponse(
        thread_id=override_thread_id,
        title=override_thread_title,
        die_size=current_die,
        result=0,
    )


@router.post("/set-die", response_class=HTMLResponse)
async def set_manual_die(
    die: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """Set manual die size for current session."""
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
    """Clear manual die size and return to automatic dice ladder mode."""
    current_session = await get_or_create(db, user_id=current_user.id)

    current_session.manual_die = None
    await db.commit()

    if clear_cache:
        clear_cache()

    await db.refresh(current_session)
    current_die = await get_current_die(current_session.id, db)
    return f"d{current_die}"
