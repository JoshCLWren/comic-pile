"""Rate API endpoint."""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import RateRequest, ThreadResponse
from comic_pile.dice_ladder import DICE_LADDER, step_down, step_up
from comic_pile.queue import move_to_back, move_to_front

router = APIRouter()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
def get_rate_page(request: Request) -> str:
    """Return the rate page HTML."""
    dice_ladder_json = "[" + ", ".join(str(d) for d in DICE_LADDER) + "]"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rate Session</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex flex-col items-center justify-center p-4">
    <div class="w-full max-w-md">
        <h1 class="text-2xl font-bold text-center mb-6">Rate Session</h1>
        
        <div id="thread-info" class="hidden bg-gray-800 rounded-lg p-4 mb-4"></div>
        
        <div id="die-preview" class="flex items-center justify-center mb-6">
            <div id="die-preview-wrapper" class="w-24 h-24 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-4xl font-bold shadow-lg">
                ?
            </div>
        </div>
        
        <div id="header-die-container" class="text-center mb-4">
            <span id="header-die-state-label" class="text-gray-400">Current Die: d6</span>
        </div>
        
        <div class="bg-gray-800 rounded-lg p-6 mb-6">
            <label for="rating-input" class="block text-sm font-medium mb-2">Rating</label>
            <input type="range" id="rating-input" min="0.5" max="5.0" step="0.5" value="3.0" 
                   class="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
                   oninput="updateUI(this.value)">
            <div class="flex justify-between text-sm text-gray-400 mt-1">
                <span>0.5</span>
                <span id="rating-value" class="text-white font-bold">3.0</span>
                <span>5.0</span>
            </div>
        </div>
        
        <div id="queue-effect" class="text-center mb-6 text-sm text-gray-400">
            Queue effect will be shown here
        </div>
        
        <div class="flex gap-4 mb-4">
            <button id="submit-btn" onclick="submitRating(false)" 
                    class="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-6 rounded-lg transition">
                Save & Continue
            </button>
            <button id="finish-btn" onclick="submitRating(true)" 
                    class="flex-1 bg-green-600 hover:bg-green-700 text-white font-bold py-3 px-6 rounded-lg transition">
                Finish Session
            </button>
        </div>
        
        <div id="error-message" class="text-xs text-rose-500 text-center font-bold hidden">
            Error message here
        </div>
        
        <div id="session-safe-indicator" class="text-center mt-4 text-sm text-yellow-400 hidden">
            ⚠️ Session safe (restore point available)
        </div>
        
        <div id="explosion-layer" class="fixed inset-0 pointer-events-none z-50"></div>
    </div>

    <script>
        const DICE_LADDER = [{dice_ladder_json}];
        let currentSession = null;
        let currentThread = null;

        function updateUI(val) {{
            document.getElementById('rating-value').textContent = parseFloat(val).toFixed(1);
        }}

        async function checkRestorePointBeforeSubmit() {{
            const response = await fetch('/api/sessions/current/');
            if (response.ok) {{
                const data = await response.json();
                return data.has_restore_point || false;
            }}
            return false;
        }}

        async function submitRating(finishSession) {{
            const rating = parseFloat(document.getElementById('rating-input').value);
            const issuesRead = 1;
            const hasRestorePoint = await checkRestorePointBeforeSubmit();
            
            if (hasRestorePoint && !confirm('This action will overwrite the restore point. Continue?')) {{
                return;
            }}
            
            const response = await fetch('/api/rate/', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ rating, issues_read: issuesRead, finish_session: finishSession }})
            }});
            
            if (response.ok) {{
                window.location.href = '/';
            }} else {{
                const error = await response.json();
                const errorEl = document.getElementById('error-message');
                errorEl.textContent = error.detail || 'An error occurred';
                errorEl.classList.remove('hidden');
            }}
        }}

        async function loadSessionData() {{
            try {{
                const response = await fetch('/api/sessions/current/');
                if (response.ok) {{
                    const data = await response.json();
                    currentSession = data;
                    currentThread = data.active_thread;
                    
                    if (currentThread) {{
                        const threadInfo = document.getElementById('thread-info');
                        threadInfo.classList.remove('hidden');
                        threadInfo.innerHTML = `
                            <h2 class="text-xl font-bold mb-2">${{currentThread.title}}</h2>
                            <p class="text-sm text-gray-400">${{currentThread.format}}</p>
                            <p class="text-sm text-gray-400">Issues remaining: ${{currentThread.issues_remaining}}</p>
                        `;
                        document.getElementById('header-die-state-label').textContent = `Current Die: d${{data.current_die || '6'}}`;
                        document.getElementById('die-preview-wrapper').textContent = data.last_rolled_result || '?';
                    }}
                    
                    if (data.has_restore_point) {{
                        document.getElementById('session-safe-indicator').classList.remove('hidden');
                    }}
                }}
            }} catch (error) {{
                console.error('Failed to load session data:', error);
            }}
        }}

        loadSessionData();
    </script>
</body>
</html>"""


def snapshot_thread_states(db: Session, session_id: int, event: Event, user_id: int) -> None:
    """Create a snapshot of all thread states for undo functionality."""
    threads = db.execute(select(Thread).where(Thread.user_id == user_id)).scalars().all()

    thread_states = {}
    for thread in threads:
        thread_states[thread.id] = {
            "title": thread.title,
            "format": thread.format,
            "issues_remaining": thread.issues_remaining,
            "last_rating": thread.last_rating,
            "last_activity_at": thread.last_activity_at.isoformat()
            if thread.last_activity_at
            else None,
            "queue_position": thread.queue_position,
            "status": thread.status,
            "review_url": thread.review_url,
            "last_review_at": thread.last_review_at.isoformat() if thread.last_review_at else None,
            "notes": thread.notes,
            "is_test": thread.is_test,
            "created_at": thread.created_at.isoformat(),
            "user_id": thread.user_id,
        }

    session = db.get(SessionModel, session_id)
    session_state = None
    if session:
        session_state = {
            "start_die": session.start_die,
            "manual_die": session.manual_die,
        }

    snapshot = Snapshot(
        session_id=session_id,
        event_id=event.id,
        thread_states=thread_states,
        session_state=session_state,
        description=f"After rating {event.rating}/5.0",
    )
    db.add(snapshot)
    db.commit()


clear_cache = None


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed = float(value)
    except ValueError:
        return default

    return parsed


def _rating_min() -> float:
    value = _float_env("RATING_MIN", 0.5)
    return value if 0.0 <= value <= 5.0 else 0.5


def _rating_max() -> float:
    value = _float_env("RATING_MAX", 5.0)
    return value if 0.0 <= value <= 10.0 else 5.0


def _rating_threshold() -> float:
    value = _float_env("RATING_THRESHOLD", 4.0)
    return value if 0.0 <= value <= 10.0 else 4.0


@router.post("/", response_model=ThreadResponse)
@limiter.limit("60/minute")
def rate_thread(
    request: Request,
    rate_data: RateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> ThreadResponse:
    """Rate current reading and update thread."""
    current_session = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.user_id == current_user.id)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .first()
    )

    if not current_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session. Please roll the dice first.",
        )

    current_session_id = current_session.id
    last_roll_event = (
        db.execute(
            select(Event)
            .where(Event.session_id == current_session_id)
            .where(Event.type == "roll")
            .where(Event.selected_thread_id.is_not(None))
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if not last_roll_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active thread. Please roll the dice first.",
        )

    thread = db.execute(
        select(Thread)
        .where(Thread.id == last_roll_event.selected_thread_id)
        .where(Thread.user_id == current_user.id)
    ).scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {last_roll_event.selected_thread_id} not found",
        )

    current_die = current_session.start_die
    last_rate_event = (
        db.execute(
            select(Event)
            .where(Event.session_id == current_session_id)
            .where(Event.type == "rate")
            .order_by(Event.timestamp.desc())
        )
        .scalars()
        .first()
    )

    if last_rate_event and last_rate_event.die_after:
        current_die = last_rate_event.die_after

    rating_min = _rating_min()
    rating_max = _rating_max()
    rating_threshold = _rating_threshold()

    if rate_data.rating < rating_min or rate_data.rating > rating_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rating must be between {rating_min} and {rating_max}",
        )

    thread.issues_remaining -= rate_data.issues_read
    thread.last_rating = rate_data.rating
    thread.last_activity_at = datetime.now()

    if rate_data.rating >= rating_threshold:
        new_die = step_down(current_die)
    else:
        new_die = step_up(current_die)

    current_session.manual_die = new_die

    event = Event(
        type="rate",
        session_id=current_session_id,
        thread_id=thread.id,
        rating=rate_data.rating,
        issues_read=rate_data.issues_read,
        die=current_die,
        die_after=new_die,
    )
    db.add(event)

    if rate_data.rating >= rating_threshold:
        move_to_front(thread.id, current_user.id, db)
    else:
        move_to_back(thread.id, current_user.id, db)

    if rate_data.finish_session and thread.issues_remaining <= 0:
        thread.status = "completed"
        move_to_back(thread.id, current_user.id, db)
        current_session.ended_at = datetime.now()

    if clear_cache:
        clear_cache()

    current_session.pending_thread_id = None
    current_session.pending_thread_updated_at = None

    db.commit()

    snapshot_thread_states(db, current_session_id, event, current_user.id)
    db.refresh(thread)

    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        position=thread.queue_position,
        status=thread.status,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        review_url=thread.review_url,
        last_review_at=thread.last_review_at,
        notes=thread.notes,
        is_test=thread.is_test,
        created_at=thread.created_at,
    )
