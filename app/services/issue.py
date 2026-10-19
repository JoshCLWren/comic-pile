"""Issue business logic and orchestration.

This service coordinates issue CRUD operations, reordering, and continuity plan
pruning. It ensures that thread counters (next-unread, remaining) and
lifecycle status are kept in sync with the issue set.

Ownership boundary (issue #3225): every Issue-to-Thread write is gated on
parent-thread ownership — the thread must belong to the caller and anchors
must belong to that same thread. Shared catalog links
(``issues.catalog_issue_id``) are never consulted: a shared ``CatalogIssue``
never authorizes creation, moves, reorders, or deletes in another reader's
library.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.repositories import issue_repository, thread_repository
from app.schemas.tags import TagTargetType
from app.services.issue_insertion import create_issues_in_natural_order
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.services.ownership import get_owned_issue_or_404, get_owned_thread_or_404
from app.services.provider_issue_adoption import adopt_comicvine_issue
from app.services.tag_service import purge_target_assignments
from app.utils.issue_parser import parse_issue_ranges
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.comicvine_provider import ComicVineClient

logger = logging.getLogger(__name__)


async def list_issues(
    db: AsyncSession,
    thread_id: int,
    current_user_id: int,
    status_filter: str | None,
    page_size: int,
    page_token: str | None,
) -> tuple[list[Issue], int, str | None]:
    """List issues for a thread with pagination and filtering.

    Args:
        db: Database session.
        thread_id: The thread ID to list issues for.
        current_user_id: The authenticated user making the request.
        status_filter: Optional filter by issue status.
        page_size: Number of issues to return per page.
        page_token: Token for pagination.

    Returns:
        A tuple of (issues, total_count, next_page_token).
    """
    await get_owned_thread_or_404(db, current_user_id, thread_id)

    cursor = None
    if page_token:
        try:
            parts = page_token.split(",")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            cursor = (int(parts[0]), int(parts[1]))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid page_token format",
            ) from None

    issues = await issue_repository.list_page(
        db, thread_id, status_filter=status_filter, cursor=cursor, limit=page_size + 1
    )

    has_more = len(issues) > page_size
    issues_to_return = issues[:page_size]

    total_count = await issue_repository.count_for_thread(db, thread_id, status_filter)

    next_token = None
    if has_more and issues_to_return:
        last = issues_to_return[-1]
        next_token = f"{last.position},{last.id}"

    return issues_to_return, total_count, next_token


async def create_issues(
    db: AsyncSession,
    thread_id: int,
    current_user_id: int,
    issue_range: str,
    insert_after_issue_id: int | None,
    *,
    append_to_end: bool = False,
) -> tuple[list[Issue], int]:
    """Create issues from a range and integrate them into the thread order.

    Ordinary numeric issue numbers are placed at their natural position in the
    series so adding ``#2`` to a series of ``#33, #34, #35`` saves
    ``#2, #33, #34, #35`` instead of appending ``#2`` at the end.

    Placement stays append-only whenever automatic ordering would be ambiguous:
    an explicit ``insert_after_issue_id`` anchor, ``append_to_end`` (explicit
    JSON ``null`` / UI "At the end"), or irregular numbering such as
    ``Annual 1``, ``0``, or fractions. Ordinary numeric series are seated in
    natural number order even when an earlier append left the thread messy.

    Args:
        db: Database session.
        thread_id: Target thread ID.
        current_user_id: User owning the thread.
        issue_range: Range string to parse.
        insert_after_issue_id: Optional anchor for insertion.
        append_to_end: When True, append after the last issue even if
            ``insert_after_issue_id`` is ``None``. Distinguishes the wire
            contract for explicit null from an omitted placement field.

    Returns:
        A tuple of (newly_created_issues, total_issue_count).
    """
    # Take the queue lock before the thread row lock so queue writers keep a
    # single lock ordering and cannot deadlock with a concurrent shuffle.
    await thread_repository.renormalize_queue_positions(db, current_user_id)
    thread = await get_owned_thread_or_404(db, current_user_id, thread_id, for_update=True)

    try:
        issue_numbers = parse_issue_ranges(issue_range)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None

    if not issue_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Issue range cannot be empty",
        )

    existing_rows = await issue_repository.locked_issue_rows(db, thread_id)
    existing_issues = {row[1]: row[2] for row in existing_rows}

    max_position = max((row[2] for row in existing_rows), default=0)
    insert_position = max_position

    if insert_after_issue_id is not None:
        insert_after_issue = next(
            (row for row in existing_rows if row[0] == insert_after_issue_id),
            None,
        )
        if insert_after_issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue {insert_after_issue_id} not found",
            )
        insert_position = insert_after_issue[2]

    new_issue_numbers = [n for n in issue_numbers if n not in existing_issues]

    if not new_issue_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All issues in range already exist",
        )

    new_issues_count = len(new_issue_numbers)

    new_issues: list[Issue] | None = None
    if insert_after_issue_id is None and not append_to_end:
        new_issues = await create_issues_in_natural_order(
            db, thread_id, new_issue_numbers, existing_rows=existing_rows
        )

    if new_issues is None:
        if insert_after_issue_id is not None:
            await issue_repository.defer_position_unique_constraint(db)
            await issue_repository.shift_positions_after(
                db, thread_id, after_position=insert_position, delta=new_issues_count
            )

        new_issues = []
        next_new_position = insert_position + 1
        for num in new_issue_numbers:
            issue = Issue(
                thread_id=thread_id,
                issue_number=num,
                position=next_new_position,
                status="unread",
            )
            await issue_repository.add_issue(db, issue)
            new_issues.append(issue)
            next_new_position += 1

        # Validation
        position_values = [i.position for i in new_issues]
        if len(position_values) != len(set(position_values)):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal error: Duplicate positions calculated",
            )

        reserved_positions = {row[2] for row in existing_rows if row[2] <= insert_position}
        if any(p in reserved_positions for p in position_values):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal error: Position conflict with existing issues",
            )

    await db.flush()

    # Try to auto-map new issues to ComicVine if the thread has a confirmed series mapping
    comicvine_volume_id = None
    try:
        # Check if thread has a confirmed ComicVine series mapping
        mapping_result = await db.execute(
            select(ExternalIdentity.external_id)
            .join(ThreadExternalSeriesMapping, ThreadExternalSeriesMapping.external_identity_id == ExternalIdentity.id)
            .where(
                ThreadExternalSeriesMapping.thread_id == thread_id,
                ThreadExternalSeriesMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "series",
            )
            .limit(1)
        )
        external_id = mapping_result.scalar_one_or_none()
        if external_id:
            # Extract ComicVine volume ID from the external identity
            comicvine_volume_id = int(external_id)
    except Exception:
        # If there's any error checking for ComicVine mapping, continue without auto-mapping
        logger.warning("Failed to check for ComicVine series mapping on thread %d", thread_id, exc_info=True)

    # Auto-map new issues to ComicVine if we found a volume mapping
    if comicvine_volume_id and new_issues:
        try:
            # Create a ComicVine client for fetching volume issues
            api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
            cache_dir = Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine"))
            if not api_key:
                logger.warning("COMICVINE_API_KEY not set, skipping auto-mapping")
            else:
                comicvine_client = ComicVineClient(api_key, cache_dir)
                
                # Fetch all issues for the ComicVine volume
                volume_issues_response = await comicvine_client.fetch_volume_issues(comicvine_volume_id)
                comicvine_issues = volume_issues_response or []
                
                # Create a mapping from issue number to ComicVine issue ID
                comicvine_issue_map = {}
                for issue_data in comicvine_issues:
                    issue_number = issue_data.get("issue_number")
                    if issue_number is not None:
                        # Normalize issue number to string for consistent comparison
                        comicvine_issue_map[str(issue_number)] = issue_data.get("id")
                
                # Try to adopt each new issue to its corresponding ComicVine issue
                for issue in new_issues:
                    issue_number_str = str(issue.issue_number)
                    if issue_number_str in comicvine_issue_map:
                        comicvine_issue_id = comicvine_issue_map[issue_number_str]
                        if comicvine_issue_id is None or not isinstance(comicvine_issue_id, int):
                            logger.warning("Skipping adoption for issue %d: invalid ComicVine issue ID %r", issue.id, comicvine_issue_id)
                            continue
                        try:
                            adoption_result = await adopt_comicvine_issue(
                                db=db,
                                user_id=current_user_id,
                                thread_id=thread_id,
                                comicvine_issue_id=comicvine_issue_id,
                                issue_number=issue_number_str,
                                comicvine_client=comicvine_client,
                                thread=thread,
                                issue=issue,
                                recalculate_tracking=False,
                            )
                            if adoption_result.outcome == "created":
                                logger.info("Auto-mapped issue %d to ComicVine issue %s", issue.id, comicvine_issue_id)
                            elif adoption_result.outcome == "reused":
                                logger.info("Reused existing ComicVine mapping for issue %d", issue.id)
                            elif adoption_result.outcome == "conflict":
                                logger.warning("ComicVine mapping conflict for issue %d: %s", issue.id, adoption_result.conflict_detail)
                        except Exception as e:
                            logger.warning("Failed to adopt ComicVine issue %s for issue %d: %s", comicvine_issue_id, issue.id, str(e))
        except Exception as e:
            logger.warning("Failed to auto-map new issues to ComicVine volume %d: %s", comicvine_volume_id, str(e))

    was_unmigrated = thread.total_issues is None
    had_next_unread_issue = thread.next_unread_issue_id is not None

    # Re-fetch ordered issues to derive tracking state correctly
    adopted_issues = await issue_repository.issues_ordered(db, thread_id)
    tracking_state = apply_thread_issue_tracking_state(thread, adopted_issues)

    if tracking_state.next_unread_issue_id is None:
        if thread.apply_derived_status("completed"):
            thread.queue_position = 0
            await thread_repository.renormalize_queue_positions(db, current_user_id)
    elif was_unmigrated or not had_next_unread_issue:
        if not was_unmigrated and thread.status == "completed":
            # Shift other active threads in queue
            await db.execute(
                update(Thread)
                .where(Thread.user_id == current_user_id)
                .where(Thread.status == "active")
                .values(queue_position=Thread.queue_position + 1)
            )
            thread.queue_position = 1
        thread.apply_derived_status("active")
        if thread.queue_position < 1:
            thread.queue_position = await thread_repository.max_queue_position(db, current_user_id) + 1
        await thread_repository.renormalize_queue_positions(db, current_user_id)

    event = Event(
        type="issues_created",
        timestamp=datetime.now(UTC),
        thread_id=thread.id,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user_id, db)
    total_issue_count = tracking_state.total_issues
    return new_issues, total_issue_count


async def move_issue(
    db: AsyncSession,
    issue_id: int,
    current_user_id: int,
    after_issue_id: int | None,
) -> None:
    """Move an issue within its thread and update positions.

    Args:
        db: Database session.
        issue_id: The issue to move.
        current_user_id: User owning the thread.
        after_issue_id: The issue that should come before the moved one.
    """
    thread_id = await issue_repository.resolve_owned_thread_id(db, issue_id, current_user_id)
    if thread_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue {issue_id} not found")

    thread = await get_owned_thread_or_404(db, current_user_id, thread_id, for_update=True)
    thread_issues = await issue_repository.locked_issues(db, thread_id)

    issue_map = {i.id: i for i in thread_issues}
    issue = issue_map.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue {issue_id} not found")

    if after_issue_id == issue_id:
        # Just refresh tracking state
        apply_thread_issue_tracking_state(thread, thread_issues)
        await refresh_user_blocked_status(current_user_id, db)
        return

    reordered_issues = [i for i in thread_issues if i.id != issue_id]

    if after_issue_id is None:
        insert_index = 0
    else:
        after_issue = issue_map.get(after_issue_id)
        if after_issue is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue {after_issue_id} not found")
        insert_index = next(idx for idx, i in enumerate(reordered_issues) if i.id == after_issue.id) + 1

    reordered_issues.insert(insert_index, issue)

    for position, i in enumerate(reordered_issues, start=1):
        i.position = position

    apply_thread_issue_tracking_state(thread, reordered_issues)
    await refresh_user_blocked_status(current_user_id, db)


async def reorder_issues(
    db: AsyncSession,
    thread_id: int,
    current_user_id: int,
    requested_issue_ids: list[int],
) -> None:
    """Rewrite all issue positions from a list of IDs.

    Args:
        db: Database session.
        thread_id: Thread to reorder.
        current_user_id: User owning the thread.
        requested_issue_ids: Desired order of IDs.
    """
    thread = await get_owned_thread_or_404(db, current_user_id, thread_id, for_update=True)
    thread_issues = await issue_repository.locked_issues(db, thread_id)

    existing_ids = [i.id for i in thread_issues]
    if (
        len(requested_issue_ids) != len(existing_ids)
        or len(set(requested_issue_ids)) != len(requested_issue_ids)
        or set(requested_issue_ids) != set(existing_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="issue_ids must contain every issue in the thread exactly once",
        )

    issue_map = {i.id: i for i in thread_issues}
    reordered_issues = [issue_map[id] for id in requested_issue_ids]

    for position, i in enumerate(reordered_issues, start=1):
        i.position = position

    apply_thread_issue_tracking_state(thread, reordered_issues)
    await refresh_user_blocked_status(current_user_id, db)


async def delete_issue(
    db: AsyncSession,
    issue_id: int,
    current_user_id: int,
) -> None:
    """Delete an issue and prune references in continuity plans.

    Args:
        db: Database session.
        issue_id: Issue to delete.
        current_user_id: User owning the issue.
    """
    thread_id = await issue_repository.resolve_owned_thread_id(db, issue_id, current_user_id)
    if thread_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue {issue_id} not found")

    # Take the queue lock before the thread row lock so queue writers keep a
    # single lock ordering and cannot deadlock with a concurrent shuffle.
    await thread_repository.renormalize_queue_positions(db, current_user_id)
    thread = await get_owned_thread_or_404(db, current_user_id, thread_id, for_update=True)
    thread_issues = await issue_repository.locked_issues(db, thread_id)

    issue_map = {i.id: i for i in thread_issues}
    issue = issue_map.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue {issue_id} not found")

    deleted_position = issue.position
    deleted_issue_number = issue.issue_number
    remaining_issues = [i for i in thread_issues if i.id != issue_id]

    await purge_target_assignments(db, TagTargetType.ISSUE.value, [issue_id])
    await issue_repository.delete_issue(db, issue)

    for i in remaining_issues:
        if i.position > deleted_position:
            i.position -= 1

    state = apply_thread_issue_tracking_state(thread, remaining_issues)
    queue_changed = False
    if state.issues_remaining == 0:
        if thread.apply_derived_status("completed"):
            queue_changed = True
    elif thread.status == "completed":
        if thread.apply_derived_status("active"):
            if thread.queue_position < 1:
                thread.queue_position = (
                    await thread_repository.max_queue_position(db, current_user_id) + 1
                )
            queue_changed = True
    if queue_changed:
        await thread_repository.renormalize_queue_positions(db, current_user_id)

    event = Event(
        type="issue_deleted",
        timestamp=datetime.now(UTC),
        thread_id=thread.id,
        issue_number=deleted_issue_number,
    )
    db.add(event)

    # Prune continuity plans
    from app.models.continuity_plan import ContinuityPlan
    from app.models.continuity_rule import ContinuityRule
    from app.schemas.continuity_plan import ContinuityPlanNode
    from app.services.reading_plan_normalization import rebuild_plan_membership

    plans_result = await db.execute(
        select(ContinuityPlan).where(ContinuityPlan.user_id == current_user_id)
    )
    for plan in plans_result.scalars().all():
        original = list(plan.nodes_json or [])
        pruned = [
            n for n in original
            if not (str(n.get("node_type", "")) == "issue" and int(n.get("ref_id", 0) or 0) == issue_id)
        ]
        if len(pruned) != len(original):
            by_lane: dict[str, list[dict[str, object]]] = {}
            for n in pruned:
                by_lane.setdefault(str(n.get("lane_id", "")), []).append(n)

            normalized: list[dict[str, object]] = []
            for lane_nodes in by_lane.values():
                lane_nodes.sort(key=lambda x: int(x.get("position", 0)))
                for idx, n in enumerate(lane_nodes):
                    n["position"] = idx
                    normalized.append(n)
            plan.nodes_json = normalized
            await rebuild_plan_membership(
                db,
                plan_id=plan.id,
                nodes=[ContinuityPlanNode.model_validate(n) for n in normalized],
            )

            marker = f"continuity-plan:{plan.id}"
            await db.execute(
                delete(ContinuityRule).where(
                    ContinuityRule.user_id == current_user_id,
                    ContinuityRule.note == marker,
                    (
                        (ContinuityRule.source_type == "issue") & (ContinuityRule.source_id == issue_id)
                    )
                    | (
                        (ContinuityRule.target_type == "issue") & (ContinuityRule.target_id == issue_id)
                    ),
                )
            )
            if len(pruned) < 2:
                await db.execute(
                    delete(ContinuityRule).where(
                        ContinuityRule.user_id == current_user_id,
                        ContinuityRule.note == marker,
                    )
                )

    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == current_user_id,
            (
                (ContinuityRule.source_type == "issue") & (ContinuityRule.source_id == issue_id)
            )
            | (
                (ContinuityRule.target_type == "issue") & (ContinuityRule.target_id == issue_id)
            ),
        )
    )

    await refresh_user_blocked_status(current_user_id, db)


async def mark_issue_read(
    db: AsyncSession,
    issue_id: int,
    current_user_id: int,
) -> None:
    """Mark an issue as read and update thread state.

    Args:
        db: Database session.
        issue_id: Issue to mark read.
        current_user_id: User owning the issue.
    """
    issue = await get_owned_issue_or_404(db, current_user_id, issue_id)
    thread = await get_owned_thread_or_404(db, current_user_id, issue.thread_id)

    if issue.status == "read":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Issue {issue_id} is already marked as read",
        )

    issue.status = "read"
    issue.read_at = datetime.now(UTC)

    next_unread = await issue_repository.first_unread(db, thread.id)

    if next_unread:
        thread.next_unread_issue_id = next_unread.id
        thread.reading_progress = "in_progress"
        thread.issues_remaining = await thread.get_issues_remaining(db)
    else:
        thread.next_unread_issue_id = None
        thread.reading_progress = "completed"
        thread.issues_remaining = 0
        if thread.apply_derived_status("completed"):
            await thread_repository.renormalize_queue_positions(db, current_user_id)

    event = Event(
        type="issue_read",
        timestamp=datetime.now(UTC),
        thread_id=thread.id,
        issue_id=issue_id,
        issue_number=issue.issue_number,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user_id, db)


async def mark_issue_unread(
    db: AsyncSession,
    issue_id: int,
    current_user_id: int,
) -> None:
    """Mark an issue as unread and update thread state.

    Args:
        db: Database session.
        issue_id: Issue to mark unread.
        current_user_id: User owning the issue.
    """
    issue = await get_owned_issue_or_404(db, current_user_id, issue_id)
    thread = await get_owned_thread_or_404(db, current_user_id, issue.thread_id)

    if issue.status == "unread":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Issue {issue_id} is already marked as unread",
        )

    thread_was_completed = thread.status == "completed"
    if thread_was_completed:
        # Reactivating changes queue membership and the later renumbering
        # takes the per-reader queue lock. Take it before any thread row is
        # dirty or flushed so row locks always follow it (same ordering as
        # move/shuffle) and the two cannot deadlock.
        await thread_repository.acquire_queue_lock(db, current_user_id)

    issue.status = "unread"
    issue.read_at = None

    # Logic for updating next_unread
    current_next = await issue_repository.get_issue(db, thread.next_unread_issue_id) if thread.next_unread_issue_id else None
    if current_next is None or issue.position < current_next.position:
        thread.next_unread_issue_id = issue.id

    thread.reading_progress = "in_progress"
    thread.issues_remaining = await thread.get_issues_remaining(db)

    if thread_was_completed:
        if thread.apply_derived_status("active"):
            if thread.queue_position < 1:
                thread.queue_position = (
                    await thread_repository.max_queue_position(db, current_user_id) + 1
                )
            await thread_repository.renormalize_queue_positions(db, current_user_id)

    event = Event(
        type="issue_unread",
        timestamp=datetime.now(UTC),
        thread_id=thread.id,
        issue_id=issue_id,
        issue_number=issue.issue_number,
    )
    db.add(event)

    await refresh_user_blocked_status(current_user_id, db)


async def bulk_mark_issue_read(
    db: AsyncSession,
    issue_ids: list[int],
    current_user_id: int,
) -> None:
    """Mark multiple issues as read atomically within a single transaction.

    Args:
        db: Database session.
        issue_ids: Issue IDs to mark read.
        current_user_id: User owning the issues.
    """
    if not issue_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="issue_ids must not be empty",
        )

    # Any of these reads can complete a series and trigger renumbering, and
    # the loop below flushes dirty thread rows between queries. Take the queue
    # lock first so row locks always follow it (same ordering as move/shuffle)
    # and the two cannot deadlock.
    await thread_repository.acquire_queue_lock(db, current_user_id)

    # Load and verify ownership for all requested IDs
    issues: list[Issue] = []
    for issue_id in issue_ids:
        issue = await get_owned_issue_or_404(db, current_user_id, issue_id)
        if issue.status == "read":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Issue {issue_id} is already marked as read",
            )
        issues.append(issue)

    # Apply updates atomically before any thread-state recalculation
    for issue in issues:
        issue.status = "read"
        issue.read_at = datetime.now(UTC)

    # Gather unique threads to recalculate tracking once per thread
    thread_ids = {issue.thread_id for issue in issues}
    queue_changed = False
    for thread_id in thread_ids:
        thread = await get_owned_thread_or_404(db, current_user_id, thread_id)
        adopted_issues = await issue_repository.issues_ordered(db, thread_id)
        tracking_state = apply_thread_issue_tracking_state(thread, adopted_issues)
        if tracking_state.next_unread_issue_id is None:
            if thread.apply_derived_status("completed"):
                queue_changed = True
        elif thread.status == "completed":
            if thread.apply_derived_status("active"):
                if thread.queue_position < 1:
                    thread.queue_position = (
                        await thread_repository.max_queue_position(db, current_user_id) + 1
                    )
                queue_changed = True
    if queue_changed:
        await thread_repository.renormalize_queue_positions(db, current_user_id)

    # Create events for each issue
    for issue in issues:
        event = Event(
            type="issue_read",
            timestamp=datetime.now(UTC),
            thread_id=issue.thread_id,
            issue_id=issue.id,
            issue_number=issue.issue_number,
        )
        db.add(event)

    await refresh_user_blocked_status(current_user_id, db)


async def bulk_mark_issue_unread(
    db: AsyncSession,
    issue_ids: list[int],
    current_user_id: int,
) -> None:
    """Mark multiple issues as unread atomically within a single transaction.

    Args:
        db: Database session.
        issue_ids: Issue IDs to mark unread.
        current_user_id: User owning the issues.
    """
    if not issue_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="issue_ids must not be empty",
        )

    # Any of these reads can reactivate or complete a series and trigger
    # renumbering, and the loop below flushes dirty thread rows between
    # queries. Take the queue lock first so row locks always follow it (same
    # ordering as move/shuffle) and the two cannot deadlock.
    await thread_repository.acquire_queue_lock(db, current_user_id)

    issues: list[Issue] = []
    for issue_id in issue_ids:
        issue = await get_owned_issue_or_404(db, current_user_id, issue_id)
        if issue.status == "unread":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Issue {issue_id} is already marked as unread",
            )
        issues.append(issue)

    for issue in issues:
        issue.status = "unread"
        issue.read_at = None

    thread_ids = {issue.thread_id for issue in issues}
    queue_changed = False
    for thread_id in thread_ids:
        thread = await get_owned_thread_or_404(db, current_user_id, thread_id)
        adopted_issues = await issue_repository.issues_ordered(db, thread_id)
        tracking_state = apply_thread_issue_tracking_state(thread, adopted_issues)
        if tracking_state.next_unread_issue_id is None:
            if thread.apply_derived_status("completed"):
                queue_changed = True
        elif thread.status == "completed":
            if thread.apply_derived_status("active"):
                if thread.queue_position < 1:
                    thread.queue_position = (
                        await thread_repository.max_queue_position(db, current_user_id) + 1
                    )
                queue_changed = True
    if queue_changed:
        await thread_repository.renormalize_queue_positions(db, current_user_id)

    for issue in issues:
        event = Event(
            type="issue_unread",
            timestamp=datetime.now(UTC),
            thread_id=issue.thread_id,
            issue_id=issue.id,
            issue_number=issue.issue_number,
        )
        db.add(event)

    await refresh_user_blocked_status(current_user_id, db)
