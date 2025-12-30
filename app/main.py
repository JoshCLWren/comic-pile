"""FastAPI application factory and configuration."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin, queue, rate, roll, session, thread
from app.database import Base, engine

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Dice-Driven Comic Tracker",
        description="API for tracking comic reading with dice rolls",
        version="0.1.0",
    )

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
