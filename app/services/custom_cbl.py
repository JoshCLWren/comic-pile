"""Author, search, export, and apply user-owned custom CBL lists."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Sequence

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import CBLPlacement, ContinuityPlanLane, ContinuityPlanNode
from app.services.continuity_plan_writer import (
    preserve_server_lane_metadata,
    replace_compiled_rules,
    validate_node_ownership,
)


@dataclass(frozen=True, slots=True)
class CustomCBLEntryView:
    """Resolved custom CBL membership used by API and plan application."""

    id: int
    position: int
    issue_id: int
    thread_id: int
    series_name: str
    issue_number: str
    status: str


@dataclass(frozen=True, slots=True)
class CustomCBLApplyResult:
    """Reading Plan mutation outcome from one explicit custom CBL application."""

    plan: ContinuityPlan
    added_issue_ids: tuple[int, ...]
    skipped_existing_issue_ids: tuple[int, ...]


async def get_owned_custom_cbl(
    db: AsyncSession, *, user_id: int, list_id: int
) -> CustomCBLList:
    """Load one custom CBL without leaking another user's list identifiers."""
    row = (
        await db.execute(
            select(CustomCBLList).where(
                CustomCBLList.id == list_id,
                CustomCBLList.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Custom CBL {list_id} not found")
    return row


async def list_custom_cbls(
    db: AsyncSession, *, user_id: int
) -> list[tuple[CustomCBLList, int]]:
    """Return owned custom CBLs newest-first with issue counts."""
    result = await db.execute(
        select(CustomCBLList, func.count(CustomCBLEntry.id))
        .outerjoin(CustomCBLEntry, CustomCBLEntry.list_id == CustomCBLList.id)
        .where(CustomCBLList.user_id == user_id)
        .group_by(CustomCBLList.id)
        .order_by(CustomCBLList.updated_at.desc(), CustomCBLList.id.desc())
    )
    return [(row[0], int(row[1])) for row in result.all()]


async def load_custom_cbl_entries(
    db: AsyncSession, *, list_id: int
) -> list[CustomCBLEntryView]:
    """Resolve ordered custom CBL entries to their canonical issue/thread labels."""
    result = await db.execute(
        select(CustomCBLEntry, Issue, Thread)
        .join(Issue, Issue.id == CustomCBLEntry.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(CustomCBLEntry.list_id == list_id)
        .order_by(CustomCBLEntry.position)
    )
    return [
        CustomCBLEntryView(
            id=entry.id,
            position=entry.position,
            issue_id=issue.id,
            thread_id=thread.id,
            series_name=thread.title,
            issue_number=issue.issue_number,
            status=issue.status,
        )
        for entry, issue, thread in result.all()
    ]


async def replace_custom_cbl_entries(
    db: AsyncSession,
    *,
    user_id: int,
    list_row: CustomCBLList,
    issue_ids: Sequence[int],
) -> None:
    """Replace membership after proving every referenced issue belongs to the user."""
    if issue_ids:
        result = await db.execute(
            select(Issue.id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id == user_id, Issue.id.in_(set(issue_ids)))
        )
        owned = set(result.scalars().all())
        missing = [issue_id for issue_id in issue_ids if issue_id not in owned]
        if missing:
            raise HTTPException(
                status_code=422,
                detail={"code": "custom_cbl_issue_not_owned", "issue_ids": missing},
            )

    await db.execute(delete(CustomCBLEntry).where(CustomCBLEntry.list_id == list_row.id))
    for position, issue_id in enumerate(issue_ids):
        db.add(CustomCBLEntry(list_id=list_row.id, issue_id=issue_id, position=position))
    await db.flush()


async def search_owned_issues(
    db: AsyncSession,
    *,
    user_id: int,
    query: str,
    limit: int,
) -> list[tuple[Issue, Thread]]:
    """Search canonical owned issues for custom CBL authoring."""
    normalized = query.strip()
    statement = (
        select(Issue, Thread)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Thread.title.asc(), Issue.position.asc(), Issue.id.asc())
        .limit(limit)
    )
    if normalized:
        pattern = f"%{normalized}%"
        statement = statement.where(
            or_(
                Thread.title.ilike(pattern),
                Issue.issue_number.ilike(pattern),
                (Thread.title + " #" + Issue.issue_number).ilike(pattern),
            )
        )
    result = await db.execute(statement)
    return [(issue, thread) for issue, thread in result.all()]


def export_custom_cbl_xml(name: str, entries: Sequence[CustomCBLEntryView]) -> str:
    """Render a portable CBL document from canonical issue references."""
    books = "\n".join(
        f'    <Book Series="{escape(entry.series_name, quote=True)}" '
        f'Number="{escape(entry.issue_number, quote=True)}" />'
        for entry in entries
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<ReadingList>\n"
        f"  <Name>{escape(name)}</Name>\n"
        f"  <NumIssues>{len(entries)}</NumIssues>\n"
        "  <Books>\n"
        f"{books}\n"
        "  </Books>\n"
        "</ReadingList>\n"
    )


async def apply_custom_cbl_to_plan(
    db: AsyncSession,
    *,
    user_id: int,
    list_row: CustomCBLList,
    plan_id: int,
    lane_id: str | None,
) -> CustomCBLApplyResult:
    """Append custom CBL issues to one owned Reading Plan through its canonical writer."""
    plan = (
        await db.execute(
            select(ContinuityPlan).where(
                ContinuityPlan.id == plan_id,
                ContinuityPlan.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Continuity plan {plan_id} not found")

    entries = await load_custom_cbl_entries(db, list_id=list_row.id)
    if not entries:
        raise HTTPException(
            status_code=422,
            detail={"code": "custom_cbl_empty", "message": "Custom CBL has no issues"},
        )

    lanes = [ContinuityPlanLane.model_validate(value) for value in (plan.lanes_json or [])]
    if not lanes:
        target_lane = ContinuityPlanLane(id="custom-cbl", name="Custom CBL", order=0)
        lanes = [target_lane]
    elif lane_id is None:
        target_lane = min(lanes, key=lambda lane: lane.order)
    else:
        target_lane = next((lane for lane in lanes if lane.id == lane_id), None)
        if target_lane is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "custom_cbl_lane_not_found", "lane_id": lane_id},
            )

    nodes = [ContinuityPlanNode.model_validate(value) for value in (plan.nodes_json or [])]
    existing_issue_ids = {node.ref_id for node in nodes if node.node_type == "issue"}
    lane_positions = [node.position for node in nodes if node.lane_id == target_lane.id]
    next_position = max(lane_positions, default=-1) + 1
    source_path = f"custom-cbl:{list_row.id}"
    added: list[int] = []
    skipped: list[int] = []

    for entry in entries:
        if entry.issue_id in existing_issue_ids:
            skipped.append(entry.issue_id)
            continue
        nodes.append(
            ContinuityPlanNode(
                id=f"custom-cbl-{list_row.id}-{entry.id}",
                node_type="issue",
                ref_id=entry.issue_id,
                lane_id=target_lane.id,
                position=next_position,
                label=f"{entry.series_name} #{entry.issue_number}",
                source_explanation=f"Added from custom CBL '{list_row.name}'.",
                source_paths=(source_path,),
                source_cbl_placements=(
                    CBLPlacement(source_path=source_path, position=entry.position),
                ),
            )
        )
        existing_issue_ids.add(entry.issue_id)
        added.append(entry.issue_id)
        next_position += 1

    if added:
        await validate_node_ownership(db, user_id=user_id, nodes=nodes)
        plan.lanes_json = preserve_server_lane_metadata(list(plan.lanes_json or []), lanes)
        plan.nodes_json = [node.model_dump() for node in nodes]
        await replace_compiled_rules(
            db,
            user_id=user_id,
            plan=plan,
            nodes=nodes,
            ordering_mode=plan.ordering_mode,
        )
        await db.flush()

    return CustomCBLApplyResult(
        plan=plan,
        added_issue_ids=tuple(added),
        skipped_existing_issue_ids=tuple(skipped),
    )
