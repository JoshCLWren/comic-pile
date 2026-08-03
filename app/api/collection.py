"""Retired Collections API surface.

Collections are no longer a supported product capability. The empty router is
kept temporarily so application wiring can be removed independently while all
former ``/api/v1/collections`` paths fall through to the standard JSON 404.
"""

from fastapi import APIRouter

router = APIRouter(tags=["collections"])
