"""FastAPI application factory and configuration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates


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

    @app.on_event("startup")
    async def startup_event():
        """Initialize database on application startup."""
        pass

    return app


app = create_app()
templates = Jinja2Templates(directory="app/templates")
