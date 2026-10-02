"""Vercel serverless entry point for ComicPile API requests."""

from app import startup_diagnostics
from app.main import create_app

# startup_diagnostics imports before app.main, so this marker captures the
# application import phase from the earliest practical Python entry boundary.
startup_diagnostics.mark_application_import_complete()
# defer_router_imports keeps the core, heavy, debug, and test routers out of the
# cold start: a keep-warm /api/ping invocation registers them on the first
# non-ping request instead of importing the whole API surface up front.
app = create_app(serve_frontend=False, defer_router_imports=True)
startup_diagnostics.mark_application_created()