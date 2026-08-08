"""Vercel serverless entry point for ComicPile API requests."""

from app import startup_diagnostics
from app.main import create_app

# startup_diagnostics imports before app.main, so this marker captures the
# application import phase from the earliest practical Python entry boundary.
startup_diagnostics.mark_application_import_complete()
app = create_app(serve_frontend=False)
startup_diagnostics.mark_application_created()
