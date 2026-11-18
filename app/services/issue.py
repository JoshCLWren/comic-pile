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
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue
from app.repositories import issue_repository, thread_repository
from app.schemas.tags import TagTargetType
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.services.ownership import get_owned_issue_or_404, get_owned_thread_or_404
from app.services.tag_service import purge_target_assignments
from comic_pile.dependencies import refresh_user_blocked_status

logger = logging.getLogger(__name__)



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
