"""Author, search, export, and apply user-owned custom CBL lists."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import cast

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import (
    CBLPlacement,
    ContinuityPlanLane,
    ContinuityPlanNode,
    PlanOrderingMode,
)
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


def _without_source_provenance(
    node: ContinuityPlanNode,
    *,
    source_path: str,
) -> ContinuityPlanNode:
    """Remove stale provenance for this custom CBL while preserving every other source."""
    paths = tuple(path for path in (node.source_paths or ()) if path != source_path)
    placements = tuple(
        placement
        for placement in (node.source_cbl_placements or ())
        if placement.source_path != source_path
    )
    explanation = node.source_explanation
    if explanation and explanation.startswith("Added from custom CBL '"):
        explanation = None
    return node.model_copy(
        update={
            "source_paths": paths or None,
            "source_cbl_placements": placements or None,
            "source_explanation": explanation,
        }
    )


def _with_source_provenance(
    node: ContinuityPlanNode,
    *,
    source_path: str,
    source_position: int,
    list_name: str,
) -> ContinuityPlanNode:
    """Attach current custom-CBL provenance to a reused or newly created plan node."""
    paths = tuple(dict.fromkeys([*(node.source_paths or ()), source_path]))
    placements = [
        placement
        for placement in (node.source_cbl_placements or ())
        if placement.source_path != source_path
    ]
    placements.append(CBLPlacement(source_path=source_path, position=source_position))
    return node.model_copy(
        update={
            "source_paths": paths,
            "source_cbl_placements": tuple(placements),
            "source_explanation": node.source_explanation
            or f"Added from custom CBL '{list_name}'.",
        }
    )


def _renumber_lane(nodes: Sequence[ContinuityPlanNode]) -> list[ContinuityPlanNode]:
    """Return one lane with contiguous positions while preserving node identities."""
    return [node.model_copy(update={"position": position}) for position, node in enumerate(nodes)]


def _merge_custom_cbl_into_lane(
    *,
    all_nodes: Sequence[ContinuityPlanNode],
    target_lane_id: str,
    entries: Sequence[CustomCBLEntryView],
    list_row: CustomCBLList,
) -> tuple[list[ContinuityPlanNode], list[int], list[int]]:
    """Merge one custom list into a lane, anchored by its earliest existing issue.

    Existing source issues are reused. When at least one custom-list issue is
    already in the target lane, the entire source sequence is inserted at the
    earliest such position. This makes an existing issue a stable anchor rather
    than appending new material to the end of the plan.
    """
    source_path = f"custom-cbl:{list_row.id}"
    source_issue_ids = [entry.issue_id for entry in entries]
    source_issue_set = set(source_issue_ids)

    cleaned_nodes = [
        _without_source_provenance(node, source_path=source_path) for node in all_nodes
    ]
    existing_by_issue: dict[int, ContinuityPlanNode] = {}
    for node in cleaned_nodes:
        if node.node_type != "issue" or node.ref_id not in source_issue_set:
            continue
        if node.ref_id in existing_by_issue:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "custom_cbl_duplicate_plan_issue",
                    "issue_id": node.ref_id,
                },
            )
        existing_by_issue[node.ref_id] = node

    cross_lane = [
        issue_id
        for issue_id, node in existing_by_issue.items()
        if node.lane_id != target_lane_id
    ]
    if cross_lane:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "custom_cbl_cross_lane_conflict",
                "issue_ids": sorted(cross_lane),
                "target_lane_id": target_lane_id,
            },
        )

    target_nodes = sorted(
        (node for node in cleaned_nodes if node.lane_id == target_lane_id),
        key=lambda node: node.position,
    )
    source_indexes = [
        index
        for index, node in enumerate(target_nodes)
        if node.node_type == "issue" and node.ref_id in source_issue_set
    ]
    anchor_index = min(source_indexes) if source_indexes else len(target_nodes)
    target_without_source = [
        node
        for node in target_nodes
        if not (node.node_type == "issue" and node.ref_id in source_issue_set)
    ]

    ordered_source_nodes: list[ContinuityPlanNode] = []
    added: list[int] = []
    reused: list[int] = []
    for entry in entries:
        existing = existing_by_issue.get(entry.issue_id)
        if existing is None:
            node = ContinuityPlanNode(
                id=f"custom-cbl-{list_row.id}-{entry.id}",
                node_type="issue",
                ref_id=entry.issue_id,
                lane_id=target_lane_id,
                position=0,
                label=f"{entry.series_name} #{entry.issue_number}",
                convergence_gate=[],
            )
            added.append(entry.issue_id)
        else:
            node = existing.model_copy(update={"lane_id": target_lane_id})
            reused.append(entry.issue_id)
        ordered_source_nodes.append(
            _with_source_provenance(
                node,
                source_path=source_path,
                source_position=entry.position,
                list_name=list_row.name,
            )
        )

    merged_target = [
        *target_without_source[:anchor_index],
        *ordered_source_nodes,
        *target_without_source[anchor_index:],
    ]
    renumbered_target = _renumber_lane(merged_target)

    other_nodes = [node for node in cleaned_nodes if node.lane_id != target_lane_id]
    return [*other_nodes, *renumbered_target], added, reused


async def apply_custom_cbl_to_plan(
    db: AsyncSession,
    *,
    user_id: int,
    list_row: CustomCBLList,
    plan_id: int,
    lane_id: str | None,
) -> CustomCBLApplyResult:
    """Merge custom CBL order into one owned Reading Plan through its canonical writer."""
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
    merged_nodes, added, reused = _merge_custom_cbl_into_lane(
        all_nodes=nodes,
        target_lane_id=target_lane.id,
        entries=entries,
        list_row=list_row,
    )

    await validate_node_ownership(db, user_id=user_id, nodes=merged_nodes)
    plan.lanes_json = preserve_server_lane_metadata(list(plan.lanes_json or []), lanes)
    plan.nodes_json = [node.model_dump() for node in merged_nodes]
    await replace_compiled_rules(
        db,
        user_id=user_id,
        plan=plan,
        nodes=merged_nodes,
        ordering_mode=cast(PlanOrderingMode, plan.ordering_mode),
    )
    await db.flush()

    return CustomCBLApplyResult(
        plan=plan,
        added_issue_ids=tuple(added),
        skipped_existing_issue_ids=tuple(reused),
    )
