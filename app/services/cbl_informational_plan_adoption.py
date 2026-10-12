"""Create an informational Reading Plan from an imported CBL source list.

X-Men Era Ten and Fantastic Four Early Years were imported as
``cbl-order:source:*`` Dependency rows plus a DependencyGroup. They never
passed CBL adoption commit, so they have no ``ContinuityPlan``. This helper
creates the missing plan as ``informational``: membership and source order
only, no inferred hard gates and no new Dependencies.

Existing canonical Dependencies (Magneto War, Hunt for Xavier, Lee/Kirby
spine notes, and other non-``cbl-order`` rows) stay the Roll authority.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.external_identity import IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.models.thread import Thread


class InformationalCblAdoptionError(ValueError):
    """Raised when an imported CBL list cannot become an informational plan."""


async def adopt_cbl_list_as_informational_plan(
    db: AsyncSession,
    *,
    user_id: int,
    source_list_id: int,
    plan_name: str,
) -> ContinuityPlan:
    """Insert one informational Reading Plan from a CBL source list.

    Unmapped CBL positions are omitted rather than guessed. Duplicate issue
    identities keep the earliest source position. The strict compiler is not
    called.

    Args:
        db: Async database session. Caller commits.
        user_id: Plan owner.
        source_list_id: Active ``cbl_source_lists`` row.
        plan_name: Exact plan name to insert. Must not already exist for the
            user.

    Returns:
        The inserted ``ContinuityPlan``.

    Raises:
        InformationalCblAdoptionError: When the list is missing, inactive, or
            the user already has this plan name.
    """
    existing = (
        await db.execute(
            select(ContinuityPlan.id).where(
                ContinuityPlan.user_id == user_id,
                ContinuityPlan.name == plan_name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise InformationalCblAdoptionError(f"plan {plan_name!r} already exists")
    source_list = await db.get(CBLSourceList, source_list_id)
    if source_list is None or not source_list.active:
        raise InformationalCblAdoptionError("CBL source list is missing or inactive")
    source = await db.get(CBLSource, source_list.source_id)
    entries = list(
        (
            await db.execute(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == source_list_id)
                .order_by(CBLSourceEntry.position, CBLSourceEntry.id)
            )
        ).scalars().all()
    )
    now = datetime.now(UTC)
    plan = ContinuityPlan(
        user_id=user_id,
        name=plan_name,
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    await db.flush()
    plan_source = ReadingPlanSource(
        plan_id=plan.id,
        raw_source_path=source_list.source_path,
        repository=None if source is None else source.repository,
        source_path=source_list.source_path,
        revision_sha=source_list.revision_sha,
        content_hash=source_list.content_hash,
        cbl_source_list_id=source_list.id,
        adopted_at=now,
        recorded_at=now,
        metadata_json={"ordering_mode": "informational", "inferred_gates": False},
    )
    db.add(plan_source)
    await db.flush()

    seen_issue_ids: set[int] = set()
    nodes: list[dict[str, object]] = []
    display_position = 0
    for entry in entries:
        issue = await _owned_issue_for_entry(db, user_id=user_id, entry=entry)
        if issue is None or issue.id in seen_issue_ids:
            continue
        seen_issue_ids.add(issue.id)
        occurrence_id = f"cbl-{source_list.id}-{entry.position}"
        db.add(
            ReadingPlanIssue(
                plan_id=plan.id,
                occurrence_id=occurrence_id,
                issue_id=issue.id,
                lane_id="main",
                display_position=display_position,
                label=f"{entry.series_name} #{entry.issue_number}",
                reader_optional=None,
                is_checkpoint=False,
                source_metadata_json={"cbl_position": entry.position},
            )
        )
        db.add(
            ReadingPlanSourcePlacement(
                plan_id=plan.id,
                occurrence_id=occurrence_id,
                plan_source_id=plan_source.id,
                source_position=entry.position,
            )
        )
        nodes.append(
            {
                "id": occurrence_id,
                "node_type": "issue",
                "ref_id": issue.id,
                "lane_id": "main",
                "position": display_position,
            }
        )
        display_position += 1
    if display_position == 0:
        raise InformationalCblAdoptionError("CBL list mapped to zero owned issues")
    plan.nodes_json = nodes
    await db.flush()
    leftover_rules = list(
        (
            await db.execute(
                select(ContinuityRule.id).where(
                    ContinuityRule.user_id == user_id,
                    ContinuityRule.note == f"continuity-plan:{plan.id}",
                )
            )
        ).scalars().all()
    )
    if leftover_rules:
        raise InformationalCblAdoptionError("informational adoption compiled unexpected rules")
    return plan


async def _owned_issue_for_entry(
    db: AsyncSession,
    *,
    user_id: int,
    entry: CBLSourceEntry,
) -> Issue | None:
    """Return the owner's issue for one CBL identity, if a confirmed mapping exists."""
    if entry.external_issue_identity_id is None:
        return None
    return (
        await db.execute(
            select(Issue)
            .join(
                IssueExternalIdentityMapping,
                IssueExternalIdentityMapping.issue_id == Issue.id,
            )
            .join(Thread, Thread.id == Issue.thread_id)
            .where(
                IssueExternalIdentityMapping.external_identity_id
                == entry.external_issue_identity_id,
                IssueExternalIdentityMapping.status == "confirmed",
                Thread.user_id == user_id,
                Thread.id < 1_000_000,
            )
            .order_by(Issue.id)
            .limit(1)
        )
    ).scalar_one_or_none()
