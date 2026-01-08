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

    pool_html = ""
    for i, thread in enumerate(threads[:current_die]):
        is_selected = thread.id == selected_thread.id
        highlight_class = (
            "border-2 border-amber-400 bg-amber-500/10 shadow-[0_0_20px_rgba(251,191,36,0.3)]"
            if is_selected
            else "border-white/5"
        )
        position_class = "text-amber-400" if is_selected else "text-slate-500/50"
        pool_html += f"""
                <div class="flex items-center gap-3 px-4 py-2 bg-white/5 {highlight_class} rounded-xl group transition-all">
                    <span class="text-lg font-black {position_class} group-hover:text-slate-400/50 transition-colors">{i + 1}</span>
                    <div class="flex-1 min-w-0">
                        <p class="font-black text-slate-300 truncate text-sm">{thread.title}</p>
                        <p class="text-[8px] font-black text-slate-500 uppercase tracking-widest">{thread.format}</p>
                    </div>
                </div>
        """

    # MULTI-DICE VISUALIZATION
    dice_html = ""
    for i in range(current_die):
        position = i + 1
        if position == result_val:
            dice_html += f"""
            <div id="dice-wrapper-{position}" class="dice-wrapper">
                <div id="dice-container-{position}" class="dice-container selected">
                    <div id="die-3d-{position}" class="w-full h-full"></div>
                    <div class="dice-number">{position}</div>
                </div>
                <div id="thread-preview-{position}" class="thread-preview selected">
                    <div class="thread-preview-title">{selected_thread.title}</div>
                    <div class="thread-preview-format">{selected_thread.format}</div>
                </div>
            </div>
            """
        elif i < len(threads):
            thread = threads[i]
            dice_html += f"""
            <div id="dice-wrapper-{position}" class="dice-wrapper">
                <div id="dice-container-{position}" class="dice-container">
                    <div id="die-3d-{position}" class="w-full h-full"></div>
                    <div class="dice-number">{position}</div>
                </div>
                <div id="thread-preview-{position}" class="thread-preview">
                    <div class="thread-preview-title">{thread.title}</div>
                    <div class="thread-preview-format">{thread.format}</div>
                </div>
            </div>
            """
        else:
            dice_html += f"""
            <div id="dice-wrapper-{position}" class="dice-wrapper">
                <div id="dice-container-{position}" class="dice-container">
                    <div id="die-3d-{position}" class="w-full h-full"></div>
                    <div class="dice-number">{position}</div>
                </div>
                <div id="thread-preview-{position}" class="thread-preview">
                    <div class="thread-preview-title text-slate-600">Empty</div>
                    <div class="thread-preview-format">--</div>
                </div>
            </div>
            """

    # SERVER SIDE RATING FORM (RELIABLE)
    return (
        pending_html
        + f"""
        <div id="dice-grid" class="dice-grid flex-1 min-h-0" data-result="{result_val}">
            {dice_html}
        </div>

            <div id="rating-form-container" class="glass-card p-4 space-y-4 animate-[bounce-in_0.6s_ease-out] shadow-2xl border-white/10 mb-4">
                <div class="flex flex-col gap-3">
                    <div class="flex items-center justify-center gap-2 mb-2">
                        <p class="text-[8px] font-black text-slate-600 uppercase tracking-[0.5em]">Selected</p>
                        <span class="bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded-lg text-sm font-black border border-amber-500/30">#{result_val}</span>
                    </div>
                    <h2 class="text-center text-lg font-black text-slate-100 leading-tight tracking-tight">{selected_thread.title}</h2>
                    <p class="text-center text-[8px] font-bold text-slate-500">{selected_thread.format}</p>
                    <div class="h-px bg-white/10 my-2"></div>
                    <div class="flex items-center justify-between gap-6">
                        <div class="flex-1 min-w-0">
                            <p class="text-[8px] font-black uppercase tracking-[0.5em] text-slate-600 mb-1">Rate your journey</p>
                            <div id="rating-value" class="text-teal-400 text-4xl font-black leading-none">4.0</div>
                        </div>
                        <div class="flex-1 min-w-0 pt-4">
                            <input type="range" id="rating-input" min="0.5" max="5.0" step="0.5" value="4.0" class="w-full h-2" oninput="updateRatingDisplay(this.value)">
                        </div>
                    </div>
                    <div class="px-3 py-2 bg-teal-500/5 rounded-lg border border-teal-500/20">
                        <p id="rating-preview" class="text-[9px] font-black text-slate-200 text-center uppercase tracking-[0.2em] leading-tight">
                            Excellent! Die steps down 🎲 Move to front
                        </p>
                    </div>
                </div>
                <button id="submit-rating-btn" onclick="submitRating()" class="w-full py-4 glass-button text-sm font-black uppercase tracking-[0.3em] shadow-[0_20px_60px_rgba(79,70,229,0.3)]">
                    Save & Continue
                </button>
                <button id="reroll-btn" onclick="triggerReroll()" class="w-full py-3 text-sm font-black uppercase tracking-[0.3em] text-slate-400 hover:text-slate-300 transition-colors">
                    Reroll Dice 🎲
                </button>
                <div id="error-message" class="text-center text-rose-500 text-xs font-bold hidden"></div>
            </div>
        </div>
        <script>
            (function() {{
                rolledResult = {result_val};
                threadId = "{selected_thread.id}";
                localStorage.setItem('selectedThreadId', '{selected_thread.id}');
                isRolling = false;
                const instruction = document.getElementById('tap-instruction');
                if (instruction) {{
                    instruction.innerHTML = 'Tap #{result_val} to rate, or Reroll';
                    instruction.classList.remove('animate-pulse');
                }}

                setTimeout(function() {{
                    for (let i = 1; i <= {current_die}; i++) {{
                        const dieContainer = document.getElementById('die-3d-' + i);
                        if (dieContainer && window.Dice3D) {{
                            const die = Dice3D.create(dieContainer, {current_die}, {{ color: 0xffffff, showValue: false }});
                            if (die) {{
                                die.setValue(i);
                                diceInstances[i] = die;
                            }}
                        }}
                    }}
                }}, 100);
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


@router.post("/set-die", response_class=HTMLResponse)
def set_manual_die(die: int, db: Session = Depends(get_db)) -> str:
    """Set manual die size for current session."""
    current_session = get_or_create(db, user_id=1)

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
def clear_manual_die(db: Session = Depends(get_db)) -> str:
    """Clear manual die size and return to automatic dice ladder mode."""
    current_session = get_or_create(db, user_id=1)

    current_session.manual_die = None
    db.commit()

    if clear_cache:
        clear_cache()

    db.expire(current_session)
    current_die = get_current_die(current_session.id, db)
    return f"d{current_die}"


@router.post("/reroll", response_class=HTMLResponse)
def reroll_dice(db: Session = Depends(get_db)) -> str:
    """Reroll dice, clearing pending thread."""
    current_session = get_or_create(db, user_id=1)

    threads = get_roll_pool(db)
    if not threads:
        return (
            '<div class="text-center text-red-500 py-4">No active threads available to roll</div>'
        )

    current_die = get_current_die(current_session.id, db)
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
        selection_method="reroll",
    )
    db.add(event)

    if current_session:
        current_session.pending_thread_id = selected_thread.id
        current_session.pending_thread_updated_at = datetime.now()
        db.commit()

    pool_html = ""
    for i, thread in enumerate(threads[:current_die]):
        is_selected = thread.id == selected_thread.id
        highlight_class = (
            "border-2 border-amber-400 bg-amber-500/10 shadow-[0_0_20px_rgba(251,191,36,0.3)]"
            if is_selected
            else "border-white/5"
        )
        position_class = "text-amber-400" if is_selected else "text-slate-500/50"
        pool_html += f"""
                <div class="flex items-center gap-3 px-4 py-2 bg-white/5 {highlight_class} rounded-xl group transition-all">
                    <span class="text-lg font-black {position_class} group-hover:text-slate-400/50 transition-colors">{i + 1}</span>
                    <div class="flex-1 min-w-0">
                        <p class="font-black text-slate-300 truncate text-sm">{thread.title}</p>
                        <p class="text-[8px] font-black text-slate-500 uppercase tracking-widest">{thread.format}</p>
                    </div>
                </div>
        """

    # MULTI-DICE VISUALIZATION
    dice_html = ""
    for i in range(current_die):
        position = i + 1
        if position == result_val:
            dice_html += f"""
            <div id="dice-wrapper-{position}" class="dice-wrapper">
                <div id="dice-container-{position}" class="dice-container selected">
                    <div id="die-3d-{position}" class="w-full h-full"></div>
                    <div class="dice-number">{position}</div>
                </div>
                <div id="thread-preview-{position}" class="thread-preview selected">
                    <div class="thread-preview-title">{selected_thread.title}</div>
                    <div class="thread-preview-format">{selected_thread.format}</div>
                </div>
            </div>
            """
        elif i < len(threads):
            thread = threads[i]
            dice_html += f"""
            <div id="dice-wrapper-{position}" class="dice-wrapper">
                <div id="dice-container-{position}" class="dice-container">
                    <div id="die-3d-{position}" class="w-full h-full"></div>
                    <div class="dice-number">{position}</div>
                </div>
                <div id="thread-preview-{position}" class="thread-preview">
                    <div class="thread-preview-title">{thread.title}</div>
                    <div class="thread-preview-format">{thread.format}</div>
                </div>
            </div>
            """
        else:
            dice_html += f"""
            <div id="dice-wrapper-{position}" class="dice-wrapper">
                <div id="dice-container-{position}" class="dice-container">
                    <div id="die-3d-{position}" class="w-full h-full"></div>
                    <div class="dice-number">{position}</div>
                </div>
                <div id="thread-preview-{position}" class="thread-preview">
                    <div class="thread-preview-title text-slate-600">Empty</div>
                    <div class="thread-preview-format">--</div>
                </div>
            </div>
            """

    return f"""
        <div id="dice-grid" class="dice-grid flex-1 min-h-0" data-result="{result_val}">
            {dice_html}
        </div>

            <div id="rating-form-container" class="glass-card p-4 space-y-4 animate-[bounce-in_0.6s_ease-out] shadow-2xl border-white/10 mb-4">
                <div class="flex flex-col gap-3">
                    <div class="flex items-center justify-center gap-2 mb-2">
                        <p class="text-[8px] font-black text-slate-600 uppercase tracking-[0.5em]">Selected</p>
                        <span class="bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded-lg text-sm font-black border border-amber-500/30">#{result_val}</span>
                    </div>
                    <h2 class="text-center text-lg font-black text-slate-100 leading-tight tracking-tight">{selected_thread.title}</h2>
                    <p class="text-center text-[8px] font-bold text-slate-500">{selected_thread.format}</p>
                    <div class="h-px bg-white/10 my-2"></div>
                    <div class="flex items-center justify-between gap-6">
                        <div class="flex-1 min-w-0">
                            <p class="text-[8px] font-black uppercase tracking-[0.5em] text-slate-600 mb-1">Rate your journey</p>
                            <div id="rating-value" class="text-teal-400 text-4xl font-black leading-none">4.0</div>
                        </div>
                        <div class="flex-1 min-w-0 pt-4">
                            <input type="range" id="rating-input" min="0.5" max="5.0" step="0.5" value="4.0" class="w-full h-2" oninput="updateRatingDisplay(this.value)">
                        </div>
                    </div>
                    <div class="px-3 py-2 bg-teal-500/5 rounded-lg border border-teal-500/20">
                        <p id="rating-preview" class="text-[9px] font-black text-slate-200 text-center uppercase tracking-[0.2em] leading-tight">
                            Excellent! Die steps down 🎲 Move to front
                        </p>
                    </div>
                </div>
                <button id="submit-rating-btn" onclick="submitRating()" class="w-full py-4 glass-button text-sm font-black uppercase tracking-[0.3em] shadow-[0_20px_60px_rgba(79,70,229,0.3)]">
                    Save & Continue
                </button>
                <button id="reroll-btn" onclick="triggerReroll()" class="w-full py-3 text-sm font-black uppercase tracking-[0.3em] text-slate-400 hover:text-slate-300 transition-colors">
                    Reroll Dice 🎲
                </button>
                <div id="error-message" class="text-center text-rose-500 text-xs font-bold hidden"></div>
            </div>
        </div>
        <script>
            (function() {{
                rolledResult = {result_val};
                threadId = "{selected_thread.id}";
                localStorage.setItem('selectedThreadId', '{selected_thread.id}');
                isRolling = false;
                const instruction = document.getElementById('tap-instruction');
                if (instruction) {{
                    instruction.innerHTML = 'Tap #{result_val} to rate, or Reroll';
                    instruction.classList.remove('animate-pulse');
                }}

                setTimeout(function() {{
                    for (let i = 1; i <= {current_die}; i++) {{
                        const dieContainer = document.getElementById('die-3d-' + i);
                        if (dieContainer && window.Dice3D) {{
                            const die = Dice3D.create(dieContainer, {current_die}, {{ color: 0xffffff, showValue: false }});
                            if (die) {{
                                die.setValue(i);
                                diceInstances[i] = die;
                            }}
                        }}
                    }}
                }}, 100);
            }})();
        </script>
    """
