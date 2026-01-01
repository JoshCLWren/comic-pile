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
    result_val = selected_index + 1

    event = Event(
        type="roll",
        session_id=current_session.id if current_session else None,
        selected_thread_id=selected_thread.id,
        die=current_die,
        result=result_val,
        selection_method="random",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = selected_thread.id
        current_session.pending_thread_updated_at = datetime.now()
        db.commit()

    # SERVER SIDE RATING FORM (RELIABLE)
    return (
        pending_html
        + f"""
        <div class="result-reveal" data-thread-id="{selected_thread.id}" data-result="{result_val}" data-title="{selected_thread.title}">
            <div class="flex flex-col gap-8 mb-8 animate-[bounce-in_0.8s_ease-out]">
                <div class="dice-perspective relative z-10">
                    <div id="die-result" class="die-3d"></div>
                </div>
                <div class="text-center px-6">
                    <p class="text-[9px] font-black text-slate-600 uppercase tracking-[0.5em] mb-2">You rolled</p>
                    <h2 class="text-2xl font-black text-slate-100 leading-tight tracking-tight">{selected_thread.title}</h2>
                </div>
            </div>

            <div id="rating-form-container" class="glass-card p-6 space-y-6 animate-[bounce-in_0.6s_ease-out] shadow-2xl border-white/10 mb-4">
                <div class="flex flex-col gap-5">
                    <div class="flex items-center justify-between gap-8">
                        <div class="flex-1 min-w-0">
                            <p class="text-[9px] font-black uppercase tracking-[0.5em] text-slate-600 mb-2">Rate your journey</p>
                            <div id="rating-value" class="text-teal-400 text-5xl font-black leading-none">4.0</div>
                        </div>
                        <div class="flex-1 min-w-0 pt-6">
                            <input type="range" id="rating-input" min="0.5" max="5.0" step="0.5" value="4.0" class="w-full h-3" oninput="updateRatingDisplay(this.value)">
                        </div>
                    </div>
                    <div class="p-4 bg-teal-500/5 rounded-xl border border-teal-500/20 shadow-xl mt-2">
                        <p id="rating-preview" class="text-[10px] font-black text-slate-200 text-center uppercase tracking-[0.25em] leading-relaxed">
                            Excellent! Die steps down 🎲 Move to front
                        </p>
                    </div>
                </div>
                <button id="submit-rating-btn" onclick="submitRating()" class="w-full py-6 glass-button text-base font-black uppercase tracking-[0.3em] shadow-[0_20px_60px_rgba(79,70,229,0.3)]">
                    Save & Continue
                </button>
                <div id="error-message" class="text-center text-rose-500 text-xs font-bold hidden"></div>
            </div>
        </div>
        <script>
            // Initialize the 3D die after swap
            (function() {{
                const target = document.getElementById('die-result');
                if (target && typeof renderDieFaces === 'function') {{
                    renderDieFaces(target, {current_die}, {result_val});
                    rolledResult = {result_val};
                    threadId = "{selected_thread.id}";
                }}
            }})();
        </script>
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
