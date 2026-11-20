"""Issue deletion business logic.

Issue creation, moves, reordering, and read-status changes are served by the
native Rust v2 API; their shadowed Python handlers and service orchestration
were retired. This module keeps the deletion path, including continuity-plan
pruning and thread-counter/lifecycle sync.

Ownership boundary (issue #3225): every Issue-to-Thread write is gated on
parent-thread ownership — the thread must belong to the caller and anchors
must belong to that same thread. Shared catalog links
(``issues.catalog_issue_id``) are never consulted: a shared ``CatalogIssue``
never authorizes a delete in another reader's library.
"""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.repositories import issue_repository, thread_repository
from app.schemas.tags import TagTargetType
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.services.ownership import get_owned_thread_or_404
from app.services.tag_service import purge_target_assignments
from comic_pile.dependencies import refresh_user_blocked_status


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


