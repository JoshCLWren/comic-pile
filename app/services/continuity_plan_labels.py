"""Fill missing Reading Plan issue-step labels from owned Issue and Thread rows.

CBL adoption historically persisted issue nodes without ``label``. The planner
then rendered every unlabeled issue step as ``[deleted series]``. Read-time
enrichment repairs those plans without rewriting stored JSON.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.repositories import issue_repository, thread_repository
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode, ContinuityPlanResponse


def issue_step_label(series_name: str, issue_number: str) -> str:
    """Return the planner label for one series + issue number.

    Args:
        series_name: Series or thread title.
        issue_number: Issue number as stored, with or without a leading ``#``.

    Returns:
        ``Series #N`` when both parts are present, otherwise the non-empty part.
    """
    number = issue_number.lstrip("#").strip()
    series = series_name.strip()
    if series and number:
        return f"{series} #{number}"
    return series or number


async def labeled_plan_nodes(
    db: AsyncSession,
    nodes: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Copy plan nodes and fill blank issue labels from owned issues.

    Args:
        db: Database session.
        nodes: Stored plan node dicts. The originals are not mutated.

    Returns:
        Node dicts with missing issue labels filled when the issue still exists.
    """
    copies = [dict(node) for node in nodes]
    missing_ids: list[int] = []
    for node in copies:
        ref_id = node.get("ref_id")
        if (
            str(node.get("node_type")) == "issue"
            and not str(node.get("label") or "").strip()
            and isinstance(ref_id, int)
        ):
            missing_ids.append(ref_id)
    if not missing_ids:
        return copies

    issues = await issue_repository.get_issues_by_ids(db, missing_ids)
    threads = await thread_repository.threads_by_ids(
        db, {issue.thread_id for issue in issues}
    )
    labels = {
        issue.id: issue_step_label(thread.title, issue.issue_number)
        for issue in issues
        if (thread := threads.get(issue.thread_id)) is not None
    }
    for node in copies:
        ref_id = node.get("ref_id")
        if (
            str(node.get("node_type")) == "issue"
            and isinstance(ref_id, int)
            and not str(node.get("label") or "").strip()
            and ref_id in labels
        ):
            node["label"] = labels[ref_id]
    return copies


async def plan_response_with_labels(
    db: AsyncSession,
    plan: ContinuityPlan,
) -> ContinuityPlanResponse:
    """Convert a persisted plan into the public response with issue labels filled.

    Args:
        db: Database session.
        plan: Owned continuity plan.

    Returns:
        The typed plan response, including series + issue labels for unlabeled
        issue nodes that still exist.
    """
    nodes = await labeled_plan_nodes(db, list(plan.nodes_json or []))
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=[ContinuityPlanLane.model_validate(lane) for lane in plan.lanes_json or []],
        nodes=[ContinuityPlanNode.model_validate(node) for node in nodes],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )
