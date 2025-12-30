"""Roll API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.post("/")
async def roll():
    """Roll the dice to select a thread."""
    return {"message": "Roll endpoint - to be implemented"}


@router.post("/override")
async def override_roll():
    """Override the roll with a manual selection."""
    return {"message": "Roll override endpoint - to be implemented"}
