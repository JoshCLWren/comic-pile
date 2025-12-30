"""Roll API routes."""

import random

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Thread
from app.schemas.thread import OverrideRequest, RollResponse
from comic_pile.queue import get_roll_pool

router = APIRouter(tags=["roll"])

try:
    from app.main import clear_cache
except ImportError:
    clear_cache = None


@router.post("/html", response_class=HTMLResponse)
def roll_dice_html(request: Request, db: Session = Depends(get_db)) -> str:
    """Roll dice and return HTML result."""
    threads = get_roll_pool(db)
    if not threads:
        return (
            '<div class="text-center text-red-500 py-4">No active threads available to roll</div>'
        )
    current_die = 6
    pool_size = min(current_die, len(threads))
    selected_index = random.randint(0, pool_size - 1)
    selected_thread = threads[selected_index]

    return f"""
        <div class="result-reveal">
            <div class="text-center mb-4">
                <div class="inline-block bg-indigo-50 border-2 border-indigo-200 rounded-xl px-6 py-4 shadow-lg">
                    <p class="text-sm text-gray-600 mb-2">Rolled d{current_die}:</p>
                    <p class="text-4xl sm:text-5xl font-bold text-indigo-600">{selected_index + 1}</p>
                </div>
            </div>
            <div class="text-center mt-4">
                <h3 class="text-xl sm:text-2xl font-bold text-gray-800 mb-2">Selected Thread</h3>
                <div class="bg-white border-2 border-indigo-200 rounded-lg p-4 shadow-md thread-selected">
                    <p class="text-lg sm:text-xl font-semibold text-indigo-800">{selected_thread.title}</p>
                    <p class="text-sm sm:text-base text-gray-600 mt-1">{selected_thread.format}</p>
                </div>
            </div>
        </div>
    """


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
    if clear_cache:
        clear_cache()
    return RollResponse(
        thread_id=thread.id,
        title=thread.title,
        die_size=current_die,
        result=0,
    )
