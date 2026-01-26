"""Roll API routes."""

import logging
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
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
def roll_dice(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> RollResponse:
    """Roll dice to select a thread."""
    threads = get_roll_pool(current_user.id, db)
    if not threads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )

    current_session = get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = get_current_die(current_session_id, db)

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

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=selected_thread.id,
        die=current_die,
        result=selected_index + 1,
        selection_method="random",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = selected_thread.id
        current_session.pending_thread_updated_at = datetime.now()

    db.commit()
    if clear_cache:
        clear_cache()

    return RollResponse(
        thread_id=selected_thread.id,
        title=selected_thread.title,
        die_size=current_die,
        result=selected_index + 1,
    )


@router.post("/override", response_model=RollResponse)
def override_roll(
    request: OverrideRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> RollResponse:
    """Manually select a thread."""
    override_thread = db.execute(
        select(Thread)
        .where(Thread.id == request.thread_id)
        .where(Thread.user_id == current_user.id)
    ).scalar_one_or_none()
    if not override_thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {request.thread_id} not found",
        )

    current_session = get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = get_current_die(current_session_id, db)

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=override_thread.id,
        die=current_die,
        result=0,
        selection_method="override",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = override_thread.id
        current_session.pending_thread_updated_at = datetime.now()

        snoozed_ids = current_session.snoozed_thread_ids or []
        if override_thread.id in snoozed_ids:
            snoozed_ids.remove(override_thread.id)
            current_session.snoozed_thread_ids = snoozed_ids

        db.commit()
        if clear_cache:
            clear_cache()

    return RollResponse(
        thread_id=override_thread.id,
        title=override_thread.title,
        die_size=current_die,
        result=0,
    )

    current_session = get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = get_current_die(current_session_id, db)

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=override_thread.id,
        die=current_die,
        result=0,
        selection_method="override",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = override_thread.id
        current_session.pending_thread_updated_at = datetime.now()

        snoozed_ids = current_session.snoozed_thread_ids or []
        print(
            f"DEBUG OVERRIDE: thread.id={override_thread.id}, snoozed_ids={snoozed_ids}, thread.id in snoozed_ids={override_thread.id in snoozed_ids}"
        )
        if override_thread.id in snoozed_ids:
            snoozed_ids.remove(override_thread.id)
            current_session.snoozed_thread_ids = snoozed_ids
            print(
                f"DEBUG OVERRIDE: Removed thread from snoozed list, new snoozed_ids={current_session.snoozed_thread_ids}"
            )
        else:
            print(f"DEBUG OVERRIDE: Thread {override_thread.id} not in snoozed list")

        db.commit()
        if clear_cache:
            clear_cache()

    return RollResponse(
        thread_id=override_thread.id,
        title=override_thread.title,
        die_size=current_die,
        result=0,
    )

    current_session = get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = get_current_die(current_session_id, db)

    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=thread.id,
        die=current_die,
        result=0,
        selection_method="override",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = thread.id
        current_session.pending_thread_updated_at = datetime.now()

        snoozed_ids = current_session.snoozed_thread_ids or []
        print(
            f"DEBUG OVERRIDE: thread.id={thread.id}, snoozed_ids={snoozed_ids}, thread.id in snoozed_ids={thread.id in snoozed_ids}"
        )
        if thread.id in snoozed_ids:
            snoozed_ids.remove(thread.id)
            current_session.snoozed_thread_ids = snoozed_ids
            print(
                f"DEBUG OVERRIDE: Removed thread from snoozed list, new snoozed_ids={current_session.snoozed_thread_ids}"
            )

        db.commit()
        print(f"DEBUG OVERRIDE: After commit, snoozed_ids={current_session.snoozed_thread_ids}")
        if clear_cache:
            clear_cache()

    if clear_cache:
        clear_cache()
    return RollResponse(
        thread_id=thread.id,
        title=thread.title,
        die_size=current_die,
        result=0,
    )


@router.post("/set-die", response_class=HTMLResponse)
def set_manual_die(
    die: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> str:
    """Set manual die size for current session."""
    current_session = get_or_create(db, user_id=current_user.id)

    if die not in [4, 6, 8, 10, 12, 20]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid die size. Must be one of: 4, 6, 8, 10, 12, 20",
        )

    current_session.manual_die = die
    db.commit()

    if clear_cache:
        clear_cache()

    return f"d{die}"


@router.post("/clear-manual-die", response_class=HTMLResponse)
def clear_manual_die(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> str:
    """Clear manual die size and return to automatic dice ladder mode."""
    current_session = get_or_create(db, user_id=current_user.id)

    current_session.manual_die = None
    db.commit()

    if clear_cache:
        clear_cache()

    db.expire(current_session)
    current_die = get_current_die(current_session.id, db)
    return f"d{current_die}"
