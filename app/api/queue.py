# Queue API routes

import logging
from datetime import UTC, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.thread import thread_to_response
from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread, User
from app.schemas import ThreadResponse
from comic_pile.queue import move_to_back, move_to_front, move_to_position, shuffle_queue

logger = logging.getLogger(__name__)

router = APIRouter()

async def _invalidate_queue_caches(user_id: int) -> None:
    """Invalidate every cached view affected by queue reordering."""
    await invalidate_user_view(user_id)

async def _active_queue_positions(user_id: int, db: AsyncSession) -> dict[int, int]:
    """Return the authenticated user's active queue positions by thread ID."""
    result = await db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.queue_position >= 1)
    )
    return dict(result.tuples().all())

@router.get("/queue", response_model=list[ThreadResponse], parameters={"cursor": "page_token", "sort": "created_at_asc,created_at_desc,queue_position_asc,queue_position_desc"})
def list_queue(
    cursor: Optional[str] = None,
    sort: Optional[str] = None,
    current_user: Annotated[User, Depends(get_current_user)]
) -> list[ThreadResponse]:
    """
    List the active queue with cursor-based pagination and deterministic ordering.
    """
    pass

@router.put("/threads/{thread_id}/position/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_position(
    request: Request,
    thread_id: int,
    position_request: PositionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to specific position."""
    ...

@router.put("/threads/{thread_id}/front/", response_model=ThreadResponse)
@limiter.limit("30/minute")
async def move_thread_front(
    request: Request,
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to the front."""
    ...

@router.put("/threads/{thread_id}/back/", response_model=ThreadResponse)
@limiter.limit("30/minute")nasync def move_thread_back(
    request: Request,
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThreadResponse:
    """Move thread to the back."""
    ...

@router.post("/shuffle/", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def shuffle_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Randomize all active queue positions."""
    ...









