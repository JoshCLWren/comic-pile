"""Vercel serverless entry point for ComicPile API requests."""

from app.main import create_app

app = create_app(serve_frontend=False)
