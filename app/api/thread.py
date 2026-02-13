"""Thread CRUD API endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread
from app.models.user import User
from app.schemas import (
    RateRequest,
    ReactivateRequest,
    SessionResponse,
    ThreadCreate,
    ThreadListResponse,
    ThreadResponse,
    ThreadUpdate,
)

router = APIRouter(tags=["threads"])


def thread_to_response(thread: Thread) -> ThreadResponse:
    """Convert a Thread model to ThreadResponse schema.

    Args:
        thread: The Thread model to convert.

    Returns:
        ThreadResponse with all thread fields.
    """
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=thread.issues_remaining,
        queue_position=thread.queue_position,
        status=thread.status,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        review_url=thread.review_url,
        last_review_at=thread.last_review_at,
        notes=thread.notes,
        is_test=thread.is_test,
        created_at=thread.created_at,
    )


@router.get("/stale", response_model=list[ThreadResponse], deprecated=True)
async def list_stale_threads(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    days: int = 30,
) -> list[ThreadResponse]:
    """List threads not read in specified days (default 30).

    DEPRECATED: Use GET /threads?status=stale&days={days} instead.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
        days: Number of days to consider threads stale.

    Returns:
        List of ThreadResponse objects for stale threads.
    """
    from datetime import timedelta

    cutoff_date = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == current_user.id)
        .where(Thread.status == "active")
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    threads = result.scalars().all()
    return [thread_to_response(thread) for thread in threads]


clear_cache = None
get_threads_cached = None


@router.get("/", response_model=ThreadListResponse)
@limiter.limit("100/minute")
async def list_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, pattern="^(active|completed|stale)$", alias="status"),
    days: int | None = Query(None, ge=1, description="Days for stale filter"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> ThreadListResponse:
    """List threads with optional filtering and pagination.

    Supports filtering by status and pagination.
    Use status=stale with days parameter to list stale threads.

    Args:
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
        status_filter: Optional status filter (active, completed, stale).
        days: Days threshold for stale filter (only used with status=stale).
        page: Page number for pagination (default 1).
        page_size: Number of items per page (default 50, max 100).

    Returns:
        ThreadListResponse with paginated threads and metadata.
    """
    from datetime import timedelta

    query = select(Thread).where(Thread.user_id == current_user.id)

    # Apply status filter
    if status_filter == "active":
        query = query.where(Thread.status == "active")
    elif status_filter == "completed":
        query = query.where(Thread.status == "completed")
    elif status_filter == "stale":
        days_value = days or 30
        cutoff_date = datetime.now(UTC) - timedelta(days=days_value)
        query = query.where(Thread.status == "active").where(
            (Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None))
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Thread.queue_position).limit(page_size).offset(offset)

    result = await db.execute(query)
    threads = result.scalars().all()

    return ThreadListResponse(
        threads=[thread_to_response(thread) for thread in threads],
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


@router.get("/completed", response_class=HTMLResponse)
async def list_completed_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """List completed threads for reactivation modal.

    Args:
        request: FastAPI request object.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        HTML string with option elements for completed threads.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == current_user.id)
        .where(Thread.status == "completed")
        .order_by(Thread.created_at.desc())
    )
    threads = result.scalars().all()
    options = "\n".join(
        f'<option value="{thread.id}">{thread.title} ({thread.format})</option>'
        for thread in threads
    )
    return f'<option value="">Select a completed thread...</option>\n{options}'


@router.get("/active", response_class=HTMLResponse)
async def list_active_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> str:
    """List active threads for override modal.

    Args:
        request: FastAPI request object.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        HTML string with radio button elements for active threads.
    """
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == current_user.id)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    threads = result.scalars().all()
    items = "\n".join(
        f'<div class="flex items-center p-2 hover:bg-gray-50 rounded">'
        f'<input type="radio" name="thread_id" value="{thread.id}" id="thread-{thread.id}" class="mr-3">'
        f'<label for="thread-{thread.id}" class="flex-1 cursor-pointer">'
        f'<span class="font-medium">{thread.title}</span>'
        f'<span class="text-sm text-gray-500 ml-2">({thread.format})</span>'
        f"</label></div>"
        for thread in threads
    )
    return items or '<p class="text-gray-500 text-center py-4">No active threads available</p>'


@router.post("/", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_thread(
    request: Request,
    thread_data: ThreadCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Create a new thread.

    Args:
        request: FastAPI request object for rate limiting.
        thread_data: Thread creation data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with created thread details.

    Raises:
        RuntimeError: If failed after max retries.
    """
    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            result = await db.execute(
                select(Thread.queue_position)
                .where(Thread.user_id == current_user.id)
                .order_by(Thread.queue_position.desc())
            )
            max_position = result.scalar() or 0
            new_thread = Thread(
                title=thread_data.title,
                format=thread_data.format,
                issues_remaining=thread_data.issues_remaining,
                queue_position=max_position + 1,
                user_id=current_user.id,
                notes=thread_data.notes,
                is_test=thread_data.is_test,
            )
            db.add(new_thread)
            await db.commit()
            await db.refresh(new_thread)
            if clear_cache:
                clear_cache()
            return thread_to_response(new_thread)
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                await db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise
                delay = initial_delay * (2 ** (retries - 1))
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to create thread after {max_retries} retries")


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Get a single thread by ID.

    Args:
        thread_id: The thread ID to retrieve.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with thread details.

    Raises:
        HTTPException: If thread not found.
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return thread_to_response(thread)


@router.put("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: int,
    thread_data: ThreadUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Update a thread.

    Args:
        thread_id: The thread ID to update.
        thread_data: Thread update data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        HTTPException: If thread not found.
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    if thread_data.title is not None:
        thread.title = thread_data.title
    if thread_data.format is not None:
        thread.format = thread_data.format
    if thread_data.issues_remaining is not None:
        thread.issues_remaining = thread_data.issues_remaining
        if thread.issues_remaining == 0:
            thread.status = "completed"
        else:
            thread.status = "active"
    if thread_data.notes is not None:
        thread.notes = thread_data.notes
    if thread_data.is_test is not None:
        thread.is_test = thread_data.is_test
    await db.commit()
    await db.refresh(thread)
    if clear_cache:
        clear_cache()
    return thread_to_response(thread)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a thread.

    Args:
        thread_id: The thread ID to delete.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Raises:
        HTTPException: If thread not found.
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    from app.models import Session as SessionModel

    await db.execute(
        update(SessionModel)
        .where(SessionModel.pending_thread_id == thread_id)
        .values(pending_thread_id=None)
    )

    delete_event = Event(
        type="delete",
        timestamp=datetime.now(UTC),
        thread_id=None,
    )
    db.add(delete_event)
    await db.delete(thread)
    await db.commit()
    if clear_cache:
        clear_cache()


@router.post(":reactivate", response_model=ThreadResponse)
async def reactivate_thread_custom_method(
    request: ReactivateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues (custom method).

    This is a Google API Design Guide compliant custom method.

    Args:
        request: Reactivation request with thread_id and issues_to_add.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with reactivated thread details.

    Raises:
        HTTPException: If thread not found, not completed, or issues_to_add invalid.
    """
    thread = await db.get(Thread, request.thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {request.thread_id} not found",
        )
    if thread.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {request.thread_id} is not completed",
        )
    if request.issues_to_add <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must add at least 1 issue",
        )

    await db.execute(
        update(Thread)
        .where(Thread.user_id == current_user.id)
        .where(Thread.status == "active")
        .values(queue_position=Thread.queue_position + 1)
    )
    thread.issues_remaining = request.issues_to_add
    thread.status = "active"
    thread.queue_position = 1
    await db.commit()
    await db.refresh(thread)
    if clear_cache:
        clear_cache()
    return thread_to_response(thread)


# Keep old endpoint for backward compatibility during migration
@router.post("/reactivate", response_model=ThreadResponse)
async def reactivate_thread(
    request: ReactivateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues.

    DEPRECATED: Use POST /threads:reactivate instead.

    Args:
        request: Reactivation request with thread_id and issues_to_add.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with reactivated thread details.

    Raises:
        HTTPException: If thread not found, not completed, or issues_to_add invalid.
    """
    return await reactivate_thread_custom_method(request, current_user, db)


@router.post("/{thread_id}:setPending")
async def set_pending_thread_custom_method(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    """Set a thread as pending for rating (skip roll) - custom method.

    This is a Google API Design Guide compliant custom method.

    Args:
        thread_id: The thread ID to set as pending.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Status indicating thread was set as pending.

    Raises:
        HTTPException: If thread not found.
    """
    thread = await db.get(Thread, thread_id)

    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    if thread.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} is not active",
        )

    if thread.issues_remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} has no issues remaining",
        )

    from comic_pile.session import get_or_create

    current_session = await get_or_create(db, user_id=current_user.id)
    current_session.pending_thread_id = thread_id
    current_session.pending_thread_updated_at = datetime.now(UTC)
    await db.commit()

    if clear_cache:
        clear_cache()

    return {"status": "pending_set", "thread_id": thread_id}


# Keep old endpoint for backward compatibility during migration
@router.post("/{thread_id}/set-pending")
async def set_pending_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    """Set a thread as pending for rating (skip roll).

    DEPRECATED: Use POST /threads/{id}:setPending instead.

    Args:
        thread_id: The thread ID to set as pending.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Status indicating thread was set as pending.

    Raises:
        HTTPException: If thread not found.
    """
    return await set_pending_thread_custom_method(thread_id, current_user, db)


@router.post(":rate", response_model=ThreadResponse)
@limiter.limit("60/minute")
async def rate_current_thread(
    request: Request,
    rate_data: RateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Rate the currently active thread (custom method).

    This is a Google API Design Guide compliant custom method.
    Delegates to the rate API implementation.

    Args:
        request: FastAPI request object for rate limiting.
        rate_data: Rating request data.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        HTTPException: If no active session, invalid rating, or thread not found.
    """
    from app.api.rate import rate_thread as rate_thread_impl

    return await rate_thread_impl(request, rate_data, current_user, db)


@router.post("/{thread_id}:unsnooze", response_model=SessionResponse)
@limiter.limit("30/minute")
async def unsnooze_thread_custom_method(
    thread_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Remove thread from snoozed list (custom method).

    This is a Google API Design Guide compliant custom method.
    Delegates to the snooze unsnooze implementation.

    Args:
        thread_id: The thread ID to remove from snoozed list.
        request: FastAPI request object for rate limiting.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        SessionResponse containing the updated session.

    Raises:
        HTTPException: If no active session exists.
    """
    from app.api.snooze import unsnooze_thread as unsnooze_thread_impl

    return await unsnooze_thread_impl(thread_id, request, current_user, db)
