"""Vercel serverless entry point for ComicPile API requests."""

from app.deployment_safety import validate_vercel_service_isolation

validate_vercel_service_isolation()

from app.main import create_app

app = create_app(serve_frontend=False)
