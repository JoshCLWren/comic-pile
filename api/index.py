"""Vercel serverless entry point for ComicPile API requests."""

from app import startup_diagnostics
from app.main import create_app

# Importing startup_diagnostics before app.main starts the user-code clock as
# close to the Vercel Python entry boundary as practical.
startup_diagnostics.startup_event_snapshot()

app = create_app(serve_frontend=False)
