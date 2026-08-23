"""Thread business logic and orchestration.

Services own business rules, transaction boundaries (commit/rollback/retry),
and cache invalidation. Query construction lives in
``app/repositories/thread_repository.py`` and sibling repositories; HTTP
status mapping lives in routers.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models import Event, Issue, Thread
from app.repositories import issue_repository, session_repository, thread_repository
from app.schemas import (
    QueueThreadListItem,
    QueueThreadListResponse,
    ReactivateRequest,
    RollResponse,
    SetCurrentIssueResponse,
    ThreadCreate,
    ThreadDetail,
    ThreadResponse,
    ThreadUpdate,
)
from app.services.errors import Forbidden, InvalidRequest, NotFound
from app.services.queue_pagination import (
    QueueCursor,
    QueueSort,
    build_cursor_values_from_row,
    decode_queue_cursor,
    encode_queue_cursor,
    normalize_queue_search,
)
from app.services.thread_issue_stats import load_next_issue_numbers, load_unread_counts
from comic_pile.session import get_current_die, get_or_create

logger = logging.getLogger(__name__)


async def _require_owned_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    for_update: bool = False,
) -> Thread:
    """Return a user-owned thread or raise a 404-mapped NotFound error.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread.

    Raises:
        NotFound: When the thread does not exist for this user.
    """
    thread = await thread_repository.find_owned(db, user_id, thread_id, for_update=for_update)
    if thread is None:
        raise NotFound(f"Thread {thread_id} not found")
    return thread


async def thread_to_response(
    thread: Thread,
    db: AsyncSession,
    issue_number_map: dict[int, str] | None = None,
    issues_remaining_map: dict[int, int] | None = None,
) -> ThreadResponse:
    """Convert Thread model to ThreadResponse.

    Args:
        thread: Thread model instance.
        db: Database session for computing issues_remaining (fallback only).
        issue_number_map: Pre-fetched mapping of issue ID → issue_number.
            When provided, avoids per-thread DB lookups for next_unread_issue_number.
        issues_remaining_map: Pre-fetched mapping of thread ID → unread count.
            When provided and the thread uses issue tracking, avoids a per-thread
            COUNT query. Single-thread callers may omit this to use the per-row
            fallback.

    Returns:
        ThreadResponse schema.
    """
    if issues_remaining_map is not None and thread.uses_issue_tracking():
        issues_remaining = issues_remaining_map.get(thread.id, 0)
    else:
        issues_remaining = await thread.get_issues_remaining(db)
    reading_progress = thread.reading_progress

    next_unread_issue_id = thread.next_unread_issue_id
    next_unread_issue_number: str | None = None
    if next_unread_issue_id is not None:
        if issue_number_map is not None:
            next_unread_issue_number = issue_number_map.get(next_unread_issue_id)
        else:
            next_issue = await issue_repository.get_issue(db, next_unread_issue_id)
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
        notes=thread.notes,
        is_test=thread.is_test,
        is_blocked=thread.is_blocked,
        created_at=thread.created_at,
        total_issues=thread.total_issues,
        reading_progress=reading_progress,
        next_unread_issue_id=next_unread_issue_id,
        next_unread_issue_number=next_unread_issue_number,
        blocking_reasons=[],
    )


async def threads_to_responses(threads: list[Thread], db: AsyncSession) -> list[ThreadResponse]:
    """Convert Thread models to responses with batched lookups.

    Args:
        threads: Threads appearing in one response payload.
        db: Database session.

    Returns:
        One ThreadResponse per input thread, in input order.
    """
    issue_map = await load_next_issue_numbers(threads, db)
    remaining_map = await load_unread_counts(threads, db)
    return [
        await thread_to_response(
            thread,
            db,
            issue_number_map=issue_map,
            issues_remaining_map=remaining_map,
        )
        for thread in threads
    ]


def to_queue_list_item(tr: ThreadResponse) -> QueueThreadListItem:
    """Convert a full ThreadResponse to a narrow QueueThreadListItem.

    Deliberately drops detail-only fields (last_rating, is_test,
    reading_progress, next_unread_issue_id) to reduce payload size for list
    views.

    Args:
        tr: Full thread response.

    Returns:
        Narrow list-item projection of the thread response.
    """
    return QueueThreadListItem(
        id=tr.id,
        title=tr.title,
        format=tr.format,
        issues_remaining=tr.issues_remaining,
        queue_position=tr.queue_position,
        status=tr.status,
        is_blocked=tr.is_blocked,
        blocking_reasons=tr.blocking_reasons,
        last_activity_at=tr.last_activity_at,
        total_issues=tr.total_issues,
        next_unread_issue_number=tr.next_unread_issue_number,
        notes=tr.notes,
        created_at=tr.created_at,
    )


async def list_stale_thread_responses(
    db: AsyncSession, user_id: int, days: int
) -> list[ThreadResponse]:
    """Build responses for threads not read in the given number of days.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        days: Number of days to consider threads stale.

    Returns:
        Responses for stale threads ordered by oldest activity first.
    """
    cutoff_date = datetime.now(UTC) - timedelta(days=days)
    threads = await thread_repository.fetch_stale_threads(db, user_id, cutoff_date)
    return await threads_to_responses(threads, db)


async def list_queue_threads(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: str,
    page_size: int,
    page_token: str | None,
) -> QueueThreadListResponse:
    """List threads with deterministic cursor-based pagination.

    Every retained sort has a deterministic cursor contract with stable
    tie-breakers so that search results remain correct across multiple pages.
    Changing ``search`` or ``sort`` invalidates any prior cursor.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Optional case-insensitive title search filter.
        sort: Validated sort order – ``position``, ``title``, or ``created``.
        page_size: Number of threads to return per page (max 200).
        page_token: Opaque cursor token for pagination continuation.

    Returns:
        QueueThreadListResponse with paginated threads and next_page_token if
        more exist.

    Raises:
        InvalidRequest: When the page token is stale or malformed.
    """
    validated_sort: QueueSort = sort
    normalized_search = normalize_queue_search(search)

    cursor = None
    if page_token:
        try:
            cursor = decode_queue_cursor(page_token, sort=validated_sort, search=search)
        except ValueError as exc:
            raise InvalidRequest(str(exc)) from exc

    threads = await thread_repository.fetch_queue_page(
        db,
        user_id,
        search=normalized_search,
        sort=validated_sort,
        cursor=cursor,
        limit=page_size + 1,
    )

    has_more = len(threads) > page_size
    threads_to_return = threads[:page_size]

    thread_responses = await threads_to_responses(threads_to_return, db)

    queue_items = [to_queue_list_item(tr) for tr in thread_responses]

    next_token = None
    if has_more and threads_to_return:
        last = threads_to_return[-1]
        page_cursor = QueueCursor(
            sort=validated_sort,
            search=normalized_search,
            values=build_cursor_values_from_row(validated_sort, last),
        )
        next_token = encode_queue_cursor(page_cursor)

    return QueueThreadListResponse(
        threads=queue_items,
        next_page_token=next_token,
    )


async def completed_threads_html(db: AsyncSession, user_id: int) -> str:
    """Render completed threads as option elements for the reactivation modal.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        HTML string with option elements for completed threads.
    """
    threads = await thread_repository.fetch_completed_threads(db, user_id)
    options = "\n".join(
        f'<option value="{thread.id}">{thread.title} ({thread.format})</option>'
        for thread in threads
    )
    return f'<option value="">Select a completed thread...</option>\n{options}'


async def active_threads_html(db: AsyncSession, user_id: int) -> str:
    """Render active threads as radio buttons for the override modal.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        HTML string with radio button elements for active threads.
    """
    threads = await thread_repository.fetch_active_threads(db, user_id)
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


async def create_thread_with_retry(
    db: AsyncSession, user_id: int, thread_data: ThreadCreate
) -> ThreadResponse:
    """Create a new thread at the end of the user's queue with deadlock retry.

    Args:
        db: Database session.
        user_id: Owner of the new thread.
        thread_data: Thread creation data.

    Returns:
        ThreadResponse with created thread details.

    Raises:
        RuntimeError: If creation keeps deadlocking past the retry budget.
    """
    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            max_position = await thread_repository.max_queue_position(db, user_id)
            new_thread = Thread(
                title=thread_data.title,
                format=thread_data.format,
                issues_remaining=thread_data.issues_remaining,
                total_issues=thread_data.total_issues,
                queue_position=max_position + 1,
                user_id=user_id,
                notes=thread_data.notes,
                is_test=thread_data.is_test,
            )
            await thread_repository.insert_thread(db, new_thread)
            await db.commit()
            await db.refresh(new_thread)

            await invalidate_user_view(user_id)
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


async def get_thread_detail(db: AsyncSession, user_id: int, thread_id: int) -> ThreadDetail:
    """Build the detail payload for one owned thread.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Returns:
        ThreadDetail for the thread.

    Raises:
        NotFound: When the thread does not exist for this user.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)
    tr = await thread_to_response(thread, db)
    return ThreadDetail(**tr.model_dump())


async def update_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    thread_data: ThreadUpdate,
) -> ThreadResponse:
    """Apply a partial update to an owned thread.

    Only legacy (non-issue-tracked) threads honor manual ``issues_remaining``
    edits; such edits also drive the active/completed status transition.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        thread_data: Partial update data.

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        NotFound: When the thread does not exist for this user.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)
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
    await db.commit()
    await db.refresh(thread)

    await invalidate_user_view(user_id)
    return await thread_to_response(thread, db)


async def delete_thread(db: AsyncSession, user_id: int, thread_id: int) -> None:
    """Delete an owned thread and detach dependent session state.

    Sessions pointing at the thread lose their pending pointer and a
    tombstone event records the deletion.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Raises:
        NotFound: When the thread does not exist for this user.
        InvalidRequest: When the database refuses the deletion.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    await session_repository.detach_pending_thread_references(db, thread_id)

    delete_event = Event(
        type="delete",
        timestamp=datetime.now(UTC),
        thread_id=None,
    )
    db.add(delete_event)
    try:
        await thread_repository.delete_thread(db, thread)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidRequest(f"Cannot delete thread: {exc}") from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error deleting thread %s", thread_id)
        raise InvalidRequest(f"Cannot delete thread: {exc}") from exc
    await invalidate_user_view(user_id)


async def reactivate_completed_thread(
    db: AsyncSession, user_id: int, request: ReactivateRequest
) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues.

    Active threads shift back one queue position and the reactivated thread
    takes position 1.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        request: Reactivation request with thread_id and issues_to_add.

    Returns:
        ThreadResponse with reactivated thread details.

    Raises:
        NotFound: When the thread does not exist for this user.
        InvalidRequest: When the thread is not completed or the issue count
            is not positive.
    """
    thread = await _require_owned_thread(db, user_id, request.thread_id)
    if thread.status != "completed":
        raise InvalidRequest(f"Thread {request.thread_id} is not completed")
    if request.issues_to_add <= 0:
        raise InvalidRequest("Must add at least 1 issue")

    await thread_repository.shift_active_queue_positions(db, user_id)

    if thread.uses_issue_tracking():
        locked_rows = await issue_repository.locked_issue_rows(db, thread.id)
        existing_total = len(locked_rows)
        max_position = max((row[2] for row in locked_rows), default=0)
        max_numeric_issue_number = max(
            (int(row[1]) for row in locked_rows if row[1].isdigit()),
            default=0,
        )

        first_new_issue = None
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
            if first_new_issue is None:
                first_new_issue = new_issue
            await issue_repository.add_issue(db, new_issue)

        await db.flush()

        thread.total_issues = existing_total + request.issues_to_add
        thread.reading_progress = "in_progress"
        thread.issues_remaining = request.issues_to_add

        if first_new_issue:
            thread.next_unread_issue_id = first_new_issue.id
    else:
        thread.issues_remaining = request.issues_to_add

    thread.status = "active"
    thread.queue_position = 1
    await db.commit()
    await db.refresh(thread)

    await invalidate_user_view(user_id)
    return await thread_to_response(thread, db)


async def set_pending_thread(
    db: AsyncSession, user_id: int, thread_id: int
) -> RollResponse:
    """Set a thread as pending for rating (manual selection).

    Manual selection sets the pending pointer directly; no random roll is
    performed. A tombstone roll event records the manual selection and any
    snooze entry for the thread is cleared.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread to select.

    Returns:
        RollResponse describing the selected thread.

    Raises:
        NotFound: When the thread does not exist for this user.
        InvalidRequest: When the thread is not active or has no issues left.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.status != "active":
        raise InvalidRequest(f"Thread {thread_id} is not active")

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
        next_issue = await issue_repository.get_issue(db, thread_next_unread_issue_id)
        if next_issue:
            thread_issue_id = next_issue.id
            thread_issue_number = next_issue.issue_number

    if thread_issues <= 0:
        raise InvalidRequest(f"Thread {thread_id} has no issues remaining")

    current_session = await get_or_create(db, user_id=user_id)
    current_session_id = current_session.id
    current_die = await get_current_die(current_session_id, db)

    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

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
    await invalidate_user_view(user_id)

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


async def backdate_thread_for_testing(
    db: AsyncSession, user_id: int, thread_id: int, days_ago: int
) -> ThreadResponse:
    """Backdate a thread's last_activity_at for E2E testing.

    Only available when TEST_ENVIRONMENT is set.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        days_ago: Number of days to backdate last_activity_at (1-3650).

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        Forbidden: When not running in the test environment.
        NotFound: When the thread does not exist for this user.
    """
    if not os.getenv("TEST_ENVIRONMENT"):
        raise Forbidden("This endpoint is only available in test environment")

    thread = await _require_owned_thread(db, user_id, thread_id)

    thread.last_activity_at = datetime.now(UTC) - timedelta(days=days_ago)
    await db.commit()
    await invalidate_user_view(user_id)

    return await thread_to_response(thread, db)


async def migrate_thread_to_issues(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    last_issue_read: int,
    total_issues: int,
) -> ThreadResponse:
    """Migrate an old-style thread to use issue tracking.

    Creates issue records #1 through ``total_issues`` and marks #1 through
    ``last_issue_read`` as read via the model's migration routine.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread to migrate.
        last_issue_read: Highest issue number already read.
        total_issues: Total issues to create.

    Returns:
        ThreadResponse with the migrated thread.

    Raises:
        NotFound: When the thread does not exist for this user.
        InvalidRequest: When the thread already tracks issues or the range is
            inconsistent.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.total_issues is not None:
        raise InvalidRequest(f"Thread {thread_id} already uses issue tracking")

    if last_issue_read > total_issues:
        raise InvalidRequest("last_issue_read cannot exceed total_issues")

    await thread.migrate_to_issues(last_issue_read, total_issues, db)

    response = await thread_to_response(thread, db)

    await db.commit()
    await invalidate_user_view(user_id)

    return response


# SECTION 6 MARKER




