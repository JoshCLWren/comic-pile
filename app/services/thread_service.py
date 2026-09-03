"""Thread business logic and orchestration.

Services own business rules, transaction boundaries (commit/rollback/retry),
and cache invalidation. Query construction lives in
``app/repositories/thread_repository.py`` and sibling repositories; HTTP
status mapping lives in routers.
"""

import asyncio
import logging
import os
from typing import cast
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models import Event, Issue, Thread
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.thread import normalize_format_value
from app.repositories import (
    continuity_repository,
    issue_repository,
    session_repository,
    thread_repository,
)
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
from sqlalchemy import select
from app.services.errors import ForbiddenError, InvalidRequestError, NotFoundError
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
from comic_pile.dependencies import format_blocking_reason, get_blocking_explanations

logger = logging.getLogger(__name__)


async def _require_owned_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    for_update: bool = False,
) -> Thread:
    """Return a user-owned thread or raise a 404-mapped NotFoundError.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
    """
    thread = await thread_repository.find_owned(db, user_id, thread_id, for_update=for_update)
    if thread is None:
        raise NotFoundError(f"Thread {thread_id} not found")
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

    format_value = normalize_format_value(thread.format)

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
        format=format_value,
        issues_remaining=issues_remaining,
        queue_position=thread.queue_position,
        status=thread.status,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        notes=thread.notes,
        is_test=thread.is_test,
        is_blocked=thread.is_blocked,
        blocking_reasons=[],
        created_at=thread.created_at,
        total_issues=thread.total_issues,
        reading_progress=reading_progress,
        next_unread_issue_id=next_unread_issue_id,
        next_unread_issue_number=next_unread_issue_number,
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
    format_value = normalize_format_value(tr.format)

    return QueueThreadListItem(
        id=tr.id,
        title=tr.title,
        format=format_value,
        issues_remaining=tr.issues_remaining,
        queue_position=tr.queue_position,
        status=tr.status,
        last_activity_at=tr.last_activity_at,
        is_blocked=tr.is_blocked,
        blocking_reasons=tr.blocking_reasons,
        total_issues=tr.total_issues,
        next_unread_issue_number=tr.next_unread_issue_number,
        notes=tr.notes,
        created_at=tr.created_at,
    )


async def list_stale_thread_responses(
    db: AsyncSession, user_id: int, days: int, snoozed_ids: list[int] | None = None
) -> list[ThreadResponse]:
    """Build responses for threads not read in the given number of days.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        days: Number of days to consider threads stale.
        snoozed_ids: Thread IDs currently snoozed in the session; these are
            excluded from the stale result.

    Returns:
        Responses for stale threads ordered by oldest activity first.
    """
    cutoff_date = datetime.now(UTC) - timedelta(days=days)
    threads = await thread_repository.fetch_stale_threads(
        db, user_id, cutoff_date, snoozed_ids=snoozed_ids
    )
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
        InvalidRequestError: When the page token is stale or malformed.
    """
    validated_sort: QueueSort = cast(QueueSort, sort)
    normalized_search = normalize_queue_search(search)

    cursor = None
    if page_token:
        try:
            cursor = decode_queue_cursor(page_token, sort=validated_sort, search=search)
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc

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
        f'<option value="{thread.id}">{thread.title} ({thread.normalize_format()})</option>'
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
        f'<span class="text-sm text-gray-500 ml-2">({thread.normalize_format()})</span>'
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
            format_value = normalize_format_value(thread_data.format)

            new_thread = Thread(
                title=thread_data.title,
                format=format_value,
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
        NotFoundError: When the thread does not exist for this user.
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
        NotFoundError: When the thread does not exist for this user.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)
    if thread_data.title is not None:
        thread.title = thread_data.title
    if thread_data.format is not None:
        thread.format = normalize_format_value(thread_data.format)
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

    Sessions pointing at the thread lose their pending pointer, continuity
    plans and rules that reference the thread or its issues are pruned so no
    orphaned steps remain, blocked flags are refreshed, and a tombstone event
    records the deletion.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the database refuses the deletion.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    await session_repository.detach_pending_thread_references(db, thread_id)

    # Collect issue ids that will disappear with the thread for plan cleanup.
    deleted_issue_ids = await issue_repository.issue_ids_for_thread(db, thread_id)

    delete_event = Event(
        type="delete",
        timestamp=datetime.now(UTC),
        thread_id=None,
    )
    db.add(delete_event)
    try:
        # Prune continuity plans that reference this thread or its issues.
        # This prevents orphaned steps that would otherwise 404 on reopen.
        plans = await continuity_repository.plans_for_user(db, user_id)
        for plan in plans:
            original = list(plan.nodes_json or [])
            pruned: list[dict[str, object]] = []
            changed = False
            for node in original:
                try:
                    ntype = str(node.get("node_type", ""))
                    ref = int(node.get("ref_id", 0))
                except (TypeError, ValueError):
                    pruned.append(node)
                    continue
                if ntype == "thread" and ref == thread_id:
                    changed = True
                    continue
                if ntype == "issue" and ref in deleted_issue_ids:
                    changed = True
                    continue
                pruned.append(node)
            if changed:
                # Renormalize contiguous positions per lane after removal.
                by_lane: dict[str, list[dict[str, object]]] = {}
                for n in pruned:
                    by_lane.setdefault(str(n.get("lane_id", "")), []).append(n)
                normalized: list[dict[str, object]] = []
                for _lane_id, lane_nodes in by_lane.items():
                    lane_nodes.sort(key=lambda x: int(x.get("position", 0)))
                    for idx, n in enumerate(lane_nodes):
                        n["position"] = idx
                        normalized.append(n)
                plan.nodes_json = normalized
                # Remove plan-owned rules that pointed at deleted issues.
                marker = f"continuity-plan:{plan.id}"
                if deleted_issue_ids:
                    await continuity_repository.delete_plan_rules_referencing_issues(
                        db, user_id, marker, deleted_issue_ids
                    )
                # If strict plan now has <2 nodes, remove remaining linear edges
                if len(pruned) < 2:
                    await continuity_repository.delete_rules_for_marker(db, user_id, marker)

        # Delete any continuity rules (non-plan-owned) that directly reference deleted issues.
        if deleted_issue_ids:
            await continuity_repository.delete_rules_referencing_issues(
                db, user_id, deleted_issue_ids
            )

        from comic_pile.dependencies import refresh_legacy_blocked_status, refresh_user_blocked_status

        try:
            await refresh_user_blocked_status(user_id, db)
        except HTTPException as exc:
            if exc.status_code == 422 and isinstance(exc.detail, dict) and exc.detail.get("code") == "continuity_graph_too_large":
                # Continuity graph is too large (user has too many threads/issues/etc.)
                # Skip continuity-based blocking refresh and use only dependency-based blocking
                # since we've already cleaned up continuity data related to the deleted thread
                await refresh_legacy_blocked_status(user_id, db)
            else:
                raise

        await thread_repository.delete_thread(db, thread)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidRequestError(f"Cannot delete thread: {exc}") from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error deleting thread %s", thread_id)
        raise InvalidRequestError(f"Cannot delete thread: {exc}") from exc
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
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread is not completed or the issue count
            is not positive.
    """
    thread = await _require_owned_thread(db, user_id, request.thread_id)
    if thread.status != "completed":
        raise InvalidRequestError(f"Thread {request.thread_id} is not completed")
    if request.issues_to_add <= 0:
        raise InvalidRequestError("Must add at least 1 issue")

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
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread is not active, blocked, or has no issues left.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.status != "active":
        raise InvalidRequestError(f"Thread {thread_id} is not active")

    if thread.is_blocked:
        dependencies = await get_blocking_explanations(thread_id, user_id, db)
        reason = ""
        if dependencies:
            reason = f": {format_blocking_reason(dependencies[0])}"
        raise InvalidRequestError(f"Thread {thread_id} is blocked by a dependency{reason}")

    thread_id_int = thread.id
    thread_title = thread.title
    thread_format = normalize_format_value(thread.format)
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
        raise InvalidRequestError(f"Thread {thread_id} has no issues remaining")

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
        ForbiddenError: When not running in the test environment.
        NotFoundError: When the thread does not exist for this user.
    """
    if not os.getenv("TEST_ENVIRONMENT"):
        raise ForbiddenError("This endpoint is only available in test environment")

    thread = await _require_owned_thread(db, user_id, thread_id)

    thread.last_activity_at = datetime.now(UTC) - timedelta(days=days_ago)
    await db.commit()
    await db.refresh(thread)
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
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread already tracks issues or the range is
            inconsistent.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.total_issues is not None:
        raise InvalidRequestError(f"Thread {thread_id} already uses issue tracking")

    if last_issue_read > total_issues:
        raise InvalidRequestError("last_issue_read cannot exceed total_issues")

    await thread.migrate_to_issues(last_issue_read, total_issues, db)

    response = await thread_to_response(thread, db)

    await db.commit()
    await invalidate_user_view(user_id)

    return response


async def migrate_thread_to_issues_simple(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    issue_number: str,
) -> ThreadResponse:
    """Migrate a legacy thread using the issue the user just rated.

    Infers ``total_issues`` from ``issues_remaining`` and the given issue
    number when the thread has no issues yet, marks every earlier position as
    read, keeps the rated issue unread for the rating flow, and points
    ``next_unread_issue_id`` at it.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread to migrate.
        issue_number: Displayed number of the issue just rated.

    Returns:
        ThreadResponse with the migrated thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread already tracks issues, the issue
            is missing and cannot be created, or the number is non-numeric.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.total_issues is not None:
        raise InvalidRequestError(f"Thread {thread_id} already uses issue tracking")

    current_issue = await issue_repository.find_in_thread_by_number(
        db, thread_id, issue_number
    )

    if not current_issue:
        try:
            issue_num_int = int(issue_number)
            total_issues = issue_num_int + max(thread.issues_remaining - 1, 0)

            for i in range(1, total_issues + 1):
                if i < issue_num_int:
                    issue_status = "read"
                    read_at = datetime.now(UTC)
                else:
                    issue_status = "unread"
                    read_at = None

                await issue_repository.add_issue(
                    db,
                    Issue(
                        thread_id=thread.id,
                        issue_number=str(i),
                        status=issue_status,
                        read_at=read_at,
                        position=i,
                    ),
                )

            current_issue = await issue_repository.find_in_thread_by_number(
                db, thread_id, issue_number
            )

            if not current_issue:
                raise InvalidRequestError(
                    f"Failed to create issue '{issue_number}'."
                    " Please add it via Edit Thread first."
                )
        except ValueError:
            raise InvalidRequestError(
                f"Non-numeric issue '{issue_number}' not found in thread."
                " Please add it via Edit Thread first."
            ) from None

    all_issues = await issue_repository.issues_ordered(db, thread_id)

    for issue in all_issues:
        if issue.position < current_issue.position:
            if issue.status != "read":
                issue.status = "read"
                issue.read_at = datetime.now(UTC)
        elif issue.position == current_issue.position:
            issue.status = "unread"
            issue.read_at = None

    thread.total_issues = len(all_issues)
    thread.next_unread_issue_id = current_issue.id
    thread.reading_progress = "in_progress"

    response = await thread_to_response(thread, db)

    await db.commit()
    await invalidate_user_view(user_id)

    return response


async def set_current_issue(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    issue_number: str,
) -> SetCurrentIssueResponse:
    """Atomically correct the current issue for an active owned thread.

    Marks every issue before the target as read, ensures the target is
    unread, updates ``thread.next_unread_issue_id``, and pins
    ``session.pending_issue_id`` so the active roll reflects the corrected
    position immediately.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread whose current issue is corrected.
        issue_number: Displayed number of the target issue.

    Returns:
        SetCurrentIssueResponse with the corrected thread and issue info.

    Raises:
        NotFoundError: When the thread or target issue does not exist for this
            user.
        InvalidRequestError: When the thread is not active or does not use
            issue tracking.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.status != "active":
        raise InvalidRequestError(f"Thread {thread_id} is not active")

    if not thread.uses_issue_tracking():
        raise InvalidRequestError(f"Thread {thread_id} does not use issue tracking")

    target_number = issue_number.strip()

    target_issue = await issue_repository.find_in_thread_by_number(
        db, thread_id, target_number
    )

    if not target_issue:
        raise NotFoundError(f"Issue '{target_number}' not found in thread {thread_id}")

    all_issues = await issue_repository.issues_ordered(db, thread_id)

    now = datetime.now(UTC)
    for issue in all_issues:
        if issue.position < target_issue.position:
            if issue.status != "read":
                issue.status = "read"
                issue.read_at = now
        elif issue.position == target_issue.position:
            if issue.status != "unread":
                issue.status = "unread"
                issue.read_at = None

    thread.total_issues = len(all_issues)
    thread.next_unread_issue_id = target_issue.id
    thread.reading_progress = "in_progress"
    thread.issues_remaining = await thread.get_issues_remaining(db)

    target_issue_id = target_issue.id
    target_issue_number = target_issue.issue_number

    # Extract attributes before commit so post-commit access never triggers a
    # lazy load (MissingGreenlet rule from AGENTS.md).
    issues_remaining = thread.issues_remaining
    total_issues = thread.total_issues
    reading_progress = thread.reading_progress
    queue_position = thread.queue_position
    thread_title = thread.title
    thread_format = normalize_format_value(thread.format)

    current_session = await get_or_create(db, user_id=user_id)
    current_session.pending_thread_id = thread_id
    current_session.pending_issue_id = target_issue_id
    current_session.pending_thread_updated_at = now

    await db.commit()
    await invalidate_user_view(user_id)

    return SetCurrentIssueResponse(
        thread_id=thread_id,
        title=thread_title,
        format=thread_format,
        issues_remaining=issues_remaining,
        queue_position=queue_position,
        issue_id=target_issue_id,
        issue_number=target_issue_number,
        next_issue_id=target_issue_id,
        next_issue_number=target_issue_number,
        total_issues=total_issues,
        reading_progress=reading_progress,
    )

    async def list_cbl_sources(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> List[Dict[str, Any]]:
        """List available CBL sources for a user.
        
        Returns a list of CBL sources with their id and name.
        """
        # Query CBL sources that have been synced for the user
        # For now, we'll return a placeholder implementation
        # In a real implementation, this would join with user permissions
        result = await db.execute(
            select(CBLSource.id, CBLSource.repository.label("name"))
        )
        return [{"id": row.id, "name": row.name} for row in result]

    async def preview_cbl_adoption(
        self,
        db: AsyncSession,
        user_id: int,
        cbl_id: int,
    ) -> Any:
        """Preview the adoption of a CBL for a user.
        
        Returns a preview of what would be adopted without making changes.
        """
        # Placeholder implementation - in reality this would:
        # 1. Get the CBL source by ID
        # 2. Verify user has access to it
        # 3. Get the CBL source list and entries
        # 4. Generate a preview of how it would integrate with user's threads
        # 5. Return the preview data
        
        # For now, return a mock preview structure
        return {
            "entries": [
                {
                    "id": 1,
                    "title": "Sample Comic Issue #1",
                    "seriesId": 101
                },
                {
                    "id": 2,
                    "title": "Sample Comic Issue #2",
                    "seriesId": 101
                }
            ],
            "series": [
                {
                    "id": 101,
                    "name": "Sample Comic Series"
                }
            ],
            "existingCount": 0,
            "missingCount": 2,
            "excludedCount": 0,
            "unresolvedCount": 0
        }

    async def adopt_cbl(
        self,
        db: AsyncSession,
        user_id: int,
        cbl_id: int,
        selections: Dict[int, Dict[str, bool]],
    ) -> None:
        """Adopt a CBL for a user.
        
        Processes the selected CBL entries and creates/updates threads accordingly.
        """
        # Placeholder implementation - in reality this would:
        # 1. Get the CBL source by ID
        # 2. Verify user has access to it
        # 3. Get the CBL source list and entries
        # 4. Process selections to determine which entries to include/exclude
        # 5. Create new threads for missing comics
        # 6. Link existing threads for comics the user already has
        # 7. Update reading positions and continuity information
        pass




