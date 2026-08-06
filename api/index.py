"""Vercel serverless entry point for ComicPile API requests."""

from fastapi import FastAPI

from app.deployment_safety import validate_vercel_service_isolation


def _create_guarded_app() -> FastAPI:
    """Validate deployment isolation before importing application configuration."""
    validate_vercel_service_isolation()

    from app.main import create_app

    return create_app(serve_frontend=False)


app = _create_guarded_app()
