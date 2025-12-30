"""Roll API routes."""

import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Thread
from app.schemas import OverrideRequest, RollResponse
from comic_pile.queue import get_roll_pool

router = APIRouter(tags=["roll"])


@router.post("/", response_model=RollResponse)
def roll_dice(db: Session = Depends(get_db)) -> RollResponse:
    """Roll dice to select a thread."""
    threads = get_roll_pool(db)
    if not threads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )
    current_die = 6
    pool_size = min(current_die, len(threads))
    selected_index = random.randint(0, pool_size - 1)
    selected_thread = threads[selected_index]
    return RollResponse(
        thread_id=selected_thread.id,
        title=selected_thread.title,
        die_size=current_die,
        result=selected_index + 1,
    )


@router.post("/override", response_model=RollResponse)
def override_roll(request: OverrideRequest, db: Session = Depends(get_db)) -> RollResponse:
    """Manually select a thread."""
    thread = db.get(Thread, request.thread_id)
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {request.thread_id} not found",
        )
    current_die = 6
    return RollResponse(
        thread_id=thread.id,
        title=thread.title,
        die_size=current_die,
        result=0,
    )
