"""Queue API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.put("/threads/{thread_id}/position")
async def update_thread_position(thread_id: int):
    """Update thread position in queue."""
    return {"message": f"Thread {thread_id} position update - to be implemented"}
