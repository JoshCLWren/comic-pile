"""Retired Reviews API surface.

The frontend no longer exposes Reviews. Keep an empty router temporarily so the
application wiring can be removed independently while former endpoints fall
through to the standard JSON 404 handler.
"""

from fastapi import APIRouter

router = APIRouter(tags=["reviews"])
