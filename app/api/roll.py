"""Roll API routes."""

import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Thread
from app.models import Session as SessionModel
from app.schemas.thread import OverrideRequest, RollResponse
from comic_pile.queue import get_roll_pool
from comic_pile.session import get_current_die, get_or_create

router = APIRouter(tags=["roll"])

try:
    from app.main import clear_cache
except ImportError:
    clear_cache = None


@router.post("/html", response_class=HTMLResponse)
def roll_dice_html(request: Request, db: Session = Depends(get_db)) -> str:
    """Roll dice and return HTML result."""
    current_session = get_or_create(db, user_id=1)

    pending_html = ""
    if current_session and current_session.pending_thread_id:
        cutoff_time = datetime.now() - timedelta(hours=6)
        if (
            current_session.pending_thread_updated_at
            and current_session.pending_thread_updated_at >= cutoff_time
        ):
            pending_thread = db.get(Thread, current_session.pending_thread_id)
            if pending_thread:
                pending_html = f"""
                <div id="pending-thread-alert" class="mb-4 bg-yellow-50 border-2 border-yellow-300 rounded-lg p-4">
                    <div class="flex items-start justify-between">
                        <div class="flex-1">
                            <p class="text-yellow-800 font-medium mb-1">You were about to read:</p>
                            <p class="text-lg font-bold text-gray-900">{pending_thread.title}</p>
                            <p class="text-sm text-gray-600">{pending_thread.format}</p>
                        </div>
                        <button
                            hx-post="/roll/dismiss-pending"
                            hx-target="#pending-thread-alert"
                            hx-swap="outerHTML"
                            class="text-yellow-700 hover:text-yellow-900 text-2xl ml-2"
                            aria-label="Dismiss pending thread"
                        >
                            &times;
                        </button>
                    </div>
                </div>
                """

    threads = get_roll_pool(db)
    if not threads:
        return pending_html + (
            '<div class="text-center text-red-500 py-4">No active threads available to roll</div>'
        )

    current_die = get_current_die(current_session.id, db) if current_session else 6
    pool_size = min(current_die, len(threads))
    selected_index = random.randint(0, pool_size - 1)
    selected_thread = threads[selected_index]

    event = Event(
        type="roll",
        session_id=current_session.id if current_session else None,
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

    return (
        pending_html
        + f"""
        <div class="result-reveal" data-thread-id="{selected_thread.id}">
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
    )


@router.post("/", response_model=RollResponse)
def roll_dice(db: Session = Depends(get_db)) -> RollResponse:
    """Roll dice to select a thread."""
    threads = get_roll_pool(db)
    if not threads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active threads available to roll",
        )

    current_session = get_or_create(db, user_id=1)
    current_die = get_current_die(current_session.id, db)
    pool_size = min(current_die, len(threads))
    selected_index = random.randint(0, pool_size - 1)
    selected_thread = threads[selected_index]

    event = Event(
        type="roll",
        session_id=current_session.id,
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

    current_session = get_or_create(db, user_id=1)
    current_die = get_current_die(current_session.id, db)

    event = Event(
        type="roll",
        session_id=current_session.id,
        selected_thread_id=thread.id,
        die=current_die,
        result=0,
        selection_method="override",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = thread.id
        current_session.pending_thread_updated_at = datetime.now()
        db.commit()

    if clear_cache:
        clear_cache()
    return RollResponse(
        thread_id=thread.id,
        title=thread.title,
        die_size=current_die,
        result=0,
    )


@router.post("/dismiss-pending", response_class=HTMLResponse)
def dismiss_pending(db: Session = Depends(get_db)) -> str:
    """Dismiss pending thread and log as skipped."""
    current_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .first()
    )

    if current_session and current_session.pending_thread_id:
        event = Event(
            type="rolled_but_skipped",
            session_id=current_session.id,
            thread_id=current_session.pending_thread_id,
        )
        db.add(event)

        current_session.pending_thread_id = None
        current_session.pending_thread_updated_at = None
        db.commit()

    return ""
