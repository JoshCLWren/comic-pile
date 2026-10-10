"""Extend Reading Plans with newly adopted release issues (#3118).

When release sync adopts an issue for a followed source, that issue becomes
a member of every plan following the source. New material extends the unread
tail; read history is never reordered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services.reading_plan_normalization import rebuild_plan_membership


@dataclass
class ExtensionResult:
    """Outcome of extending plans with one adopted issue."""

    issue_id: int
    plans_extended: list[int] = field(default_factory=list)
    plans_skipped_duplicate: list[int] = field(default_factory=list)
    plans_needing_review: list[int] = field(default_factory=list)


def _node_id_for_issue(issue_id: int) -> str:
    return f"release-{issue_id}"


async def _load_nodes(plan: ContinuityPlan) -> list[ContinuityPlanNode]:
    raw = plan.nodes_json or []
    return [ContinuityPlanNode.model_validate(n) for n in raw]


async def _read_issue_ids(
    db: AsyncSession, *, plan_id: int
) -> set[int]:
    """Return issue IDs already read in this plan (status != unread)."""
    stmt = select(ReadingPlanIssue.issue_id, Issue.status).join(
        Issue, ReadingPlanIssue.issue_id == Issue.id
    ).where(ReadingPlanIssue.plan_id == plan_id)
    rows = (await db.execute(stmt)).all()
    return {issue_id for issue_id, status in rows if status != "unread"}


async def extend_plans_with_issue(
    db: AsyncSession,
    *,
    issue_id: int,
    source_id: int,
    store_date: datetime | None,
) -> ExtensionResult:
    """Add an adopted issue to every plan following the source.

    Args:
        db: Database session.
        issue_id: Canonical Issue just adopted.
        source_id: Release source that triggered the adoption.
        store_date: Provider store_date for deterministic ordering.

    Returns:
        ExtensionResult with per-plan outcomes.
    """
    result = ExtensionResult(issue_id=issue_id)

    # Find the source to get its plan.
    source = (
        await db.execute(
            select(ReadingPlanReleaseSource).where(
                ReadingPlanReleaseSource.id == source_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        return result

    # Find all plans following this source's volume+thread.
    # For v1: the source's own plan. Multi-plan follows share the volume,
    # so query all enabled sources for the same volume+thread.
    stmt = select(ReadingPlanReleaseSource).where(
        ReadingPlanReleaseSource.thread_id == source.thread_id,
        ReadingPlanReleaseSource.external_identity_id
        == source.external_identity_id,
        ReadingPlanReleaseSource.enabled.is_(True),
    )
    sources = list((await db.execute(stmt)).scalars().all())
    plan_ids = sorted({s.plan_id for s in sources})

    issue = (await db.execute(select(Issue).where(Issue.id == issue_id))).scalar_one_or_none()
    if issue is None:
        return result

    for plan_id in plan_ids:
        plan = (
            await db.execute(
                select(ContinuityPlan).where(ContinuityPlan.id == plan_id)
            )
        ).scalar_one_or_none()
        if plan is None:
            continue
        nodes = await _load_nodes(plan)

        # Idempotent: skip if already a member.
        if any(n.node_type == "issue" and n.ref_id == issue_id for n in nodes):
            result.plans_skipped_duplicate.append(plan_id)
            continue

        # Find unread tail: position after the last read issue.
        read_ids = await _read_issue_ids(db, plan_id=plan_id)
        issue_nodes = [n for n in nodes if n.node_type == "issue"]
        last_read_pos = -1
        for n in issue_nodes:
            if n.ref_id in read_ids and n.position > last_read_pos:
                last_read_pos = n.position

        # New node goes at the tail (after all existing nodes).
        max_pos = max((n.position for n in nodes), default=-1)
        new_position = max(max_pos, last_read_pos) + 1

        new_node = ContinuityPlanNode(
            id=_node_id_for_issue(issue_id),
            node_type="issue",
            ref_id=issue_id,
            lane_id="unread-tail",
            position=new_position,
            label=None,
        )
        nodes.append(new_node)
        # Deterministic order: sort tail by (position, issue_id).
        # New nodes already have increasing positions; stable sort keeps it.
        nodes.sort(key=lambda n: (n.position, n.ref_id))

        # Persist and rebuild via the canonical path.
        plan.nodes_json = [n.model_dump(mode="json") for n in nodes]
        plan.updated_at = datetime.now(UTC)
        await rebuild_plan_membership(db, plan_id=plan_id, nodes=nodes)
        result.plans_extended.append(plan_id)

    await db.commit()
    return result
