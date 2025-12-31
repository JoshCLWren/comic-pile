"""FastAPI application factory and configuration."""

import logging
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import admin, queue, rate, roll, session, thread
from app.database import Base, engine, get_db
from app.models import Session as SessionModel

logger = logging.getLogger(__name__)


_thread_cache: dict[str, tuple[list, float]] = {}
_session_cache: dict[str, tuple[dict, float]] = {}


def get_threads_cached(db: Session) -> list:
    """Get threads from cache (30 second TTL)."""
    cache_key = "all_threads"
    now = time.time()
    if cache_key in _thread_cache and now - _thread_cache[cache_key][1] < 30:
        return _thread_cache[cache_key][0]
    from app.models import Thread

    threads = list(db.execute(select(Thread).order_by(Thread.queue_position)).scalars().all())
    _thread_cache[cache_key] = (threads, now)
    return threads


def get_current_session_cached(db: Session) -> dict | None:
    """Get current session from cache (10 second TTL)."""
    cache_key = "current_session"
    now = time.time()
    if cache_key in _session_cache and now - _session_cache[cache_key][1] < 10:
        return _session_cache[cache_key][0]
    from comic_pile.session import is_active

    active_sessions = (
        db.execute(
            select(SessionModel)
            .where(SessionModel.ended_at.is_(None))
            .order_by(SessionModel.started_at.desc())
        )
        .scalars()
        .all()
    )
    active_session = None
    for s in active_sessions:
        if is_active(s):
            active_session = s
            break
    if active_session:
        from app.schemas.thread import SessionResponse
        from comic_pile.session import get_current_die

        response = SessionResponse(
            id=active_session.id,
            started_at=active_session.started_at,
            ended_at=active_session.ended_at,
            start_die=active_session.start_die,
            user_id=active_session.user_id,
            ladder_path=session.build_ladder_path(active_session, db),
            active_thread=session.get_active_thread(active_session, db),
            current_die=get_current_die(active_session.id, db),
        )
        _session_cache[cache_key] = (response.model_dump(), now)
        return response.model_dump()
    return None


def clear_cache() -> None:
    """Clear all caches on POST/PUT/DELETE operations."""
    _thread_cache.clear()
    _session_cache.clear()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )
    templates = Jinja2Templates(directory="app/templates")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(thread.router, prefix="/threads", tags=["threads"])
    app.include_router(roll.router, prefix="/roll", tags=["roll"])
    app.include_router(rate.router, prefix="/rate", tags=["rate"])
    app.include_router(queue.router, prefix="/queue", tags=["queue"])
    app.include_router(session.router, tags=["session"])
    app.include_router(admin.router, tags=["admin"])

    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request, db: Session = Depends(get_db)):
        """Render roll page as default home page."""
        from comic_pile.dice_ladder import DICE_LADDER
        from comic_pile.session import get_current_die, get_or_create

        current_session = get_or_create(db, user_id=1)
        current_die = get_current_die(current_session.id, db) if current_session else 6
        if current_die not in DICE_LADDER:
            current_die = 6
        return templates.TemplateResponse(
            "roll.html", {"request": request, "current_die": current_die}
        )

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request, db: Session = Depends(get_db)):
        """Render session history page."""
        sessions = (
            db.execute(select(SessionModel).order_by(SessionModel.started_at.desc()).limit(50))
            .scalars()
            .all()
        )

        session_responses = []
        for s in sessions:
            ladder_path = session.build_ladder_path(s, db)
            active_thread = session.get_active_thread(s, db)
            session_responses.append(
                {
                    "id": s.id,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "ladder_path": ladder_path,
                    "active_thread": active_thread,
                }
            )

        return templates.TemplateResponse(
            "history.html", {"request": request, "sessions": session_responses}
        )

    @app.get("/rate", response_class=HTMLResponse)
    async def rate_page(request: Request):
        """Render rating page."""
        return templates.TemplateResponse("rate.html", {"request": request})

    @app.get("/queue", response_class=HTMLResponse)
    async def queue_page(request: Request):
        """Render queue page."""
        return templates.TemplateResponse("queue.html", {"request": request})

    @app.get("/roll", response_class=HTMLResponse)
    async def roll_page(request: Request, db: Session = Depends(get_db)):
        """Render roll page."""
        from comic_pile.dice_ladder import DICE_LADDER
        from comic_pile.session import get_current_die, get_or_create

        current_session = get_or_create(db, user_id=1)
        current_die = get_current_die(current_session.id, db) if current_session else 6
        if current_die not in DICE_LADDER:
            current_die = 6
        return templates.TemplateResponse(
            "roll.html", {"request": request, "current_die": current_die}
        )

    @app.on_event("startup")
    async def startup_event():
        """Initialize database on application startup."""
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    return app


app = create_app()
