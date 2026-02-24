"""Thread CRUD API endpoints."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Thread
from app.models.user import User
from app.schemas import ReactivateRequest, RollResponse, ThreadCreate, ThreadResponse, ThreadUpdate
from comic_pile.session import get_current_die, get_or_create

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
        is_blocked=thread.is_blocked,
        blocking_reasons=[],
        collection_id=thread.collection_id,
        created_at=thread.created_at,
    )


@router.get("/stale", response_model=list[ThreadResponse])
async def list_stale_threads(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    days: int = 30,
) -> list[ThreadResponse]:
    """List threads not read in specified days (default 30).

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


@router.get("/", response_model=list[ThreadResponse])
@limiter.limit("100/minute")
async def list_threads(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(default=None, min_length=1),
    collection_id: int | None = Query(default=None),
) -> list[ThreadResponse]:
    """List all threads ordered by position.

    Args:
        request: FastAPI request object for rate limiting.
        search: Optional case-insensitive title search filter.
        collection_id: Optional collection ID to filter threads.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        List of ThreadResponse objects ordered by queue_position.
    """
    normalized_search = search.strip() if search is not None else None
    query = select(Thread).where(Thread.user_id == current_user.id)

    if collection_id is not None:
        query = query.where(Thread.collection_id == collection_id)

    if normalized_search:
        query = query.where(Thread.title.ilike(f"%{normalized_search}%"))
        query = query.order_by(Thread.queue_position)
        result = await db.execute(query)
        threads = result.scalars().all()
    elif get_threads_cached and collection_id is None:
        threads = await get_threads_cached(db, current_user.id)
    else:
        query = query.order_by(Thread.queue_position)
        result = await db.execute(query)
        threads = result.scalars().all()
    return [thread_to_response(thread) for thread in threads]


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
    # If collection_id is provided, verify it belongs to the user
    if thread_data.collection_id is not None:
        from app.models import Collection

        collection = await db.get(Collection, thread_data.collection_id)
        if not collection or collection.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {thread_data.collection_id} not found",
            )

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
                collection_id=thread_data.collection_id,
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
    # Check if collection_id was explicitly provided in the request using model_fields_set
    if "collection_id" in thread_data.model_fields_set:
        # If collection_id is provided (can be None to clear), verify ownership
        if thread_data.collection_id is not None:
            from app.models import Collection

            collection = await db.get(Collection, thread_data.collection_id)
            if not collection or collection.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Collection {thread_data.collection_id} not found",
                )
        thread.collection_id = thread_data.collection_id
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


@router.post("/reactivate", response_model=ThreadResponse)
async def reactivate_thread(
    request: ReactivateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues.

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


@router.post("/{thread_id}/set-pending", response_model=RollResponse)
async def set_pending_thread(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Set a thread as pending for rating (manual selection).

    Args:
        thread_id: The thread ID to set as pending.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        RollResponse with the selected thread details.

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

    thread_id_int = thread.id
    thread_title = thread.title
    thread_format = thread.format
    thread_issues = thread.issues_remaining
    thread_position = thread.queue_position

    if thread_issues <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} has no issues remaining",
        )

    current_session = await get_or_create(db, user_id=current_user.id)
    current_session_id = current_session.id
    current_die = await get_current_die(current_session_id, db)

    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

    # Manual selection sets pending directly; no random roll is performed.
    result = 0
    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=thread_id_int,
        die=current_die,
        result=result,
        selection_method="manual",
    )
    db.add(event)

    current_session.pending_thread_id = thread_id_int
    current_session.pending_thread_updated_at = datetime.now(UTC)

    if thread_id_int in snoozed_ids:
        snoozed_ids.remove(thread_id_int)
        current_session.snoozed_thread_ids = snoozed_ids
        offset = len(snoozed_ids)
        snoozed_count = len(snoozed_ids)

    await db.commit()
    if clear_cache:
        clear_cache()

    return RollResponse(
        thread_id=thread_id_int,
        title=thread_title,
        format=thread_format,
        issues_remaining=thread_issues,
        queue_position=thread_position,
        die_size=current_die,
        result=result,
        offset=offset,
        snoozed_count=snoozed_count,
    )


@router.post("/{thread_id}:moveToCollection", response_model=ThreadResponse)
async def move_thread_to_collection(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    collection_id: int | None = Query(None),
) -> ThreadResponse:
    """Move a thread to a collection (or remove from collection if collection_id is None).

    Args:
        thread_id: The thread ID to move.
        collection_id: The collection ID to move the thread to (None to remove from collection).
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        HTTPException: If thread not found or collection doesn't belong to user.
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    # If collection_id is provided, verify it belongs to the user
    if collection_id is not None:
        from app.models import Collection

        collection = await db.get(Collection, collection_id)
        if not collection or collection.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

    thread.collection_id = collection_id

    # Extract thread attributes before commit to avoid MissingGreenlet error
    thread_response = thread_to_response(thread)

    await db.commit()
    if clear_cache:
        clear_cache()
    return thread_response
