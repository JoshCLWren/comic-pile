"""Thread CRUD API endpoints."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import limiter
from app.models import Event, Issue, Thread
from app.models.user import User
from app.schemas import (
    MigrateToIssuesRequest,
    ReactivateRequest,
    RollResponse,
    ThreadCreate,
    ThreadResponse,
    ThreadUpdate,
)
from app.schemas.migration import MigrateToIssuesSimpleRequest
from comic_pile.session import get_current_die, get_or_create

router = APIRouter(tags=["threads"])

logger = logging.getLogger(__name__)


async def thread_to_response(
    thread: Thread,
    db: AsyncSession,
    issue_number_map: dict[int, str] | None = None,
) -> ThreadResponse:
    """Convert Thread model to ThreadResponse.

    Args:
        thread: Thread model instance
        db: Database session for computing issues_remaining
        issue_number_map: Pre-fetched mapping of issue ID → issue_number.
            When provided, avoids per-thread DB lookups for next_unread_issue_number.

    Returns:
        ThreadResponse schema
    """
    issues_remaining = await thread.get_issues_remaining(db)
    reading_progress = thread.reading_progress

    next_unread_issue_id = thread.next_unread_issue_id
    next_unread_issue_number: str | None = None
    if next_unread_issue_id is not None:
        if issue_number_map is not None:
            next_unread_issue_number = issue_number_map.get(next_unread_issue_id)
        else:
            next_issue = await db.get(Issue, next_unread_issue_id)
            if next_issue:
                next_unread_issue_number = next_issue.issue_number

    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=thread.format,
        issues_remaining=issues_remaining,
        queue_position=thread.queue_position,
        status=thread.status,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        review_url=thread.review_url,
        last_review_at=thread.last_review_at,
        notes=thread.notes,
        is_test=thread.is_test,
        is_blocked=thread.is_blocked,
        collection_id=thread.collection_id,
        created_at=thread.created_at,
        total_issues=thread.total_issues,
        reading_progress=reading_progress,
        next_unread_issue_id=next_unread_issue_id,
        next_unread_issue_number=next_unread_issue_number,
        blocked_by_thread_ids=thread.blocked_by_thread_ids or [],
        blocked_by_issue_ids=thread.blocked_by_issue_ids or [],
        blocking_reasons=[],
    )


async def _bulk_issue_number_map(threads: list[Thread], db: AsyncSession) -> dict[int, str]:
    """Batch-fetch issue numbers for all threads' next_unread_issue_id values."""
    issue_ids = {t.next_unread_issue_id for t in threads if t.next_unread_issue_id is not None}
    if not issue_ids:
        return {}
    result = await db.execute(select(Issue.id, Issue.issue_number).where(Issue.id.in_(issue_ids)))
    return {row.id: row.issue_number for row in result}


async def _threads_to_responses(threads: list[Thread], db: AsyncSession) -> list[ThreadResponse]:
    """Convert a list of Thread models to ThreadResponses with batched lookups."""
    issue_map = await _bulk_issue_number_map(threads, db)
    return [await thread_to_response(thread, db, issue_number_map=issue_map) for thread in threads]


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
        .where(Thread.is_blocked.is_(False))
        .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
        .order_by(Thread.last_activity_at.asc().nullsfirst())
    )
    threads = list(result.scalars().all())
    return await _threads_to_responses(threads, db)


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
        threads = list(result.scalars().all())
        return await _threads_to_responses(threads, db)
    elif get_threads_cached and collection_id is None:
        threads = await get_threads_cached(db, current_user.id)
    else:
        query = query.order_by(Thread.queue_position)
        result = await db.execute(query)
        threads = list(result.scalars().all())
    return await _threads_to_responses(threads, db)


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
                total_issues=thread_data.total_issues,
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
            return await thread_to_response(new_thread, db)
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
    return await thread_to_response(thread, db)


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
        if not thread.uses_issue_tracking():
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
    return await thread_to_response(thread, db)


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
    try:
        await db.delete(thread)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete thread: {exc}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error deleting thread %s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from exc
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

    if thread.uses_issue_tracking():
        from app.models import Issue
        from sqlalchemy import select

        locked_issues = await db.execute(
            select(Issue.issue_number, Issue.position)
            .where(Issue.thread_id == thread.id)
            .with_for_update()
        )
        existing_issue_rows = locked_issues.all()
        existing_total = len(existing_issue_rows)
        max_position = max((row.position for row in existing_issue_rows), default=0)
        max_numeric_issue_number = max(
            (int(row.issue_number) for row in existing_issue_rows if row.issue_number.isdigit()),
            default=0,
        )

        new_issues: list[Issue] = []
        for i in range(
            max_numeric_issue_number + 1,
            max_numeric_issue_number + request.issues_to_add + 1,
        ):
            max_position += 1
            new_issue = Issue(
                thread_id=thread.id,
                issue_number=str(i),
                status="unread",
                position=max_position,
            )
            db.add(new_issue)
            new_issues.append(new_issue)

        await db.flush()

        thread.total_issues = existing_total + request.issues_to_add
        thread.reading_progress = "in_progress"
        thread.issues_remaining = request.issues_to_add

        if new_issues:
            thread.next_unread_issue_id = new_issues[0].id
    else:
        thread.issues_remaining = request.issues_to_add

    thread.status = "active"
    thread.queue_position = 1
    await db.commit()
    await db.refresh(thread)
    if clear_cache:
        clear_cache()
    return await thread_to_response(thread, db)


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
    thread_total_issues = thread.total_issues
    thread_reading_progress = thread.reading_progress
    thread_next_unread_issue_id = thread.next_unread_issue_id

    thread_issue_id = None
    thread_issue_number = None
    if thread.uses_issue_tracking() and thread_next_unread_issue_id:
        from app.models import Issue

        issue_result = await db.execute(
            select(Issue).where(Issue.id == thread_next_unread_issue_id)
        )
        next_issue = issue_result.scalar_one_or_none()
        if next_issue:
            thread_issue_id = next_issue.id
            thread_issue_number = next_issue.issue_number

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
        issue_id=thread_issue_id,
        issue_number=thread_issue_number,
        next_issue_id=thread_issue_id,
        next_issue_number=thread_issue_number,
        total_issues=thread_total_issues,
        reading_progress=thread_reading_progress,
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

    response = await thread_to_response(thread, db)
    await db.commit()
    if clear_cache:
        clear_cache()
    return response


@router.post("/{thread_id}:migrateToIssues", response_model=ThreadResponse)
async def migrate_thread_to_issues(
    thread_id: int,
    request: MigrateToIssuesRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Migrate an old-style thread to use issue tracking.

    Creates issue records #1 through total_issues.
    Marks #1 through last_issue_read as read.
    Updates thread with issue tracking fields.

    Args:
        thread_id: The thread ID to migrate
        request: Migration data with last_issue_read and total_issues
        current_user: The authenticated user
        db: Database session

    Returns:
        ThreadResponse with updated thread

    Raises:
        HTTPException: 404 if thread not found, 400 if validation fails
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    if thread.total_issues is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} already uses issue tracking",
        )

    if request.last_issue_read > request.total_issues:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="last_issue_read cannot exceed total_issues",
        )

    await thread.migrate_to_issues(request.last_issue_read, request.total_issues, db)

    response = await thread_to_response(thread, db)

    await db.commit()
    if clear_cache:
        clear_cache()

    return response


@router.post("/{thread_id}:migrateToIssuesSimple", response_model=ThreadResponse)
async def migrate_thread_to_issues_simple(
    thread_id: int,
    request: MigrateToIssuesSimpleRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Simplified migration: infer total_issues from current state.

    If user just read issue N, then issues 1-(N-1) were read previously,
    and issue N is what they just rated (should be unread for the rating flow).

    This endpoint infers total_issues from issues_remaining + issue_number,
    marks issues 1 through (issue_number-1) as READ,
    marks issue issue_number as UNREAD (so the rating can mark it read),
    and sets next_unread_issue_id to point to issue_number.

    Args:
        thread_id: The thread ID to migrate
        request: Migration data with issue_number being the issue just rated
        current_user: The authenticated user
        db: Database session

    Returns:
        ThreadResponse with updated thread

    Raises:
        HTTPException: 404 if thread not found, 400 if validation fails
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    if thread.total_issues is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread {thread_id} already uses issue tracking",
        )

    issue_number = request.issue_number

    if issue_number < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="issue_number must be at least 1",
        )

    total_issues = issue_number + max(thread.issues_remaining - 1, 0)

    await thread.migrate_to_issues(issue_number - 1, total_issues, db)

    response = await thread_to_response(thread, db)

    await db.commit()
    if clear_cache:
        clear_cache()

    return response
