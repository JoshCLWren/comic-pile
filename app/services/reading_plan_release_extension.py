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
from app.repositories import issue_repository, thread_repository
from app.repositories import reading_plan_release_source_repository as source_repository
from app.repositories.reading_list_authoring_repository import lock_reader
from app.services.release_exclusion_service import comicvine_volume_id, load_release_exclusions
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services.reading_plan_normalization import rebuild_plan_membership


@dataclass
class ExtensionResult:
    """Outcome of extending plans with one adopted issue."""

    issue_id: int
    excluded: bool = False
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
    user_id: int,
    store_date: datetime | None,
) -> ExtensionResult:
    """Add an adopted issue to every plan following the source.

    Args:
        db: Caller-owned transaction; this helper flushes but never commits.
        user_id: Authenticated owner of the source and target Issue.
        issue_id: Canonical Issue just adopted.
        source_id: Release source that triggered the adoption.
        store_date: Provider store_date for deterministic ordering.

    Returns:
        ExtensionResult with per-plan outcomes.
    """
    result = ExtensionResult(issue_id=issue_id)

    initial = await source_repository.get_by_id(db, source_id=source_id, user_id=user_id)
    if initial is None:
        return result
    thread_id = initial.thread_id
    await lock_reader(db, user_id)
    thread = await thread_repository.lock_thread(db, thread_id)
    source = await source_repository.get_current_for_sync(db, source_id=source_id, user_id=user_id)
    if source is None or not source.enabled or thread is None:
        return result
    issue = await issue_repository.get_issue(db, issue_id)
    if (thread.user_id != user_id or source.thread_id != thread_id
        or issue is None or issue.thread_id != thread_id):
        result.plans_needing_review.append(source.plan_id)
        return result
    exclusions = await load_release_exclusions(db, user_id)
    volume_id = comicvine_volume_id(source.external_identity.external_id)
    if exclusions.excludes_source(thread_id, volume_id) or issue_id in exclusions.issue_ids:
        result.excluded = True
        return result
    if not await source_repository.has_confirmed_thread_volume(
        db, thread_id=thread_id, external_identity_id=source.external_identity_id,
    ):
        result.plans_needing_review.append(source.plan_id)
        return result
    sources = await source_repository.enabled_siblings(db, source=source, user_id=user_id)
    plan_ids = sorted({row.plan_id for row in sources})

    for plan_id in plan_ids:
        plan = await source_repository.owned_plan_for_extension(db, plan_id=plan_id, user_id=user_id)
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

    await db.flush()
    return result
