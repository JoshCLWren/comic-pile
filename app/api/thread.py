"""Thread API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_threads():
    """List all threads."""
    return {"message": "Thread list endpoint - to be implemented"}


@router.post("/")
async def create_thread():
    """Create a new thread."""
    return {"message": "Thread create endpoint - to be implemented"}


@router.get("/{thread_id}")
async def get_thread(thread_id: int):
    """Get a specific thread."""
    return {"message": f"Thread {thread_id} endpoint - to be implemented"}


@router.put("/{thread_id}")
async def update_thread(thread_id: int):
    """Update a specific thread."""
    return {"message": f"Thread {thread_id} update endpoint - to be implemented"}


@router.delete("/{thread_id}")
async def delete_thread(thread_id: int):
    """Delete a specific thread."""
    return {"message": f"Thread {thread_id} delete endpoint - to be implemented"}
