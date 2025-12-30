"""FastAPI application factory and configuration."""

import logging

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
    app.include_router(admin.router, prefix="/admin", tags=["admin"])

    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint with basic API information."""
        return {
            "name": "Dice-Driven Comic Tracker API",
            "version": "0.1.0",
            "docs": "/docs",
            "redoc": "/redoc",
        }

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
