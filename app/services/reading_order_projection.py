"""Deterministic continuity plan → reading order projection service.

Projections are explicit two-step operations: callers preview the entries
that would be added or updated, then confirm the projection in a separate
request. The plan is never modified by a projection, and reading order
changes never feed back into the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode

if TYPE_CHECKING:
    from app.schemas.reading_order import (
        ReadingOrderProjectionPreview,
        ReadingOrderProjectionResult,
    )


@dataclass(frozen=True)
class ProjectionEntry:
    """One row in the projected reading order view."""

    thread_id: int
    thread_title: str | None
    position: int
    source: Literal["existing", "added", "updated"]
    source_node_id: str | None


@dataclass(frozen=True)
class ProjectionConflict:
    """An entry blocked from mutation until the user resolves it."""

    code: Literal["duplicate_thread", "missing_thread", "non_thread_node"]
    message: str
    node_id: str
    thread_id: int | None = None
    existing_positions: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectionPlan:
    """Internal representation of a projection request ready for execution."""

    plan_id: int
    plan_name: str
    plan_ordering_mode: str
    reading_order_id: int
    reading_order_name: str
    entries: tuple[ProjectionEntry, ...]
    conflicts: tuple[ProjectionConflict, ...]
    total_positions: int
    dropped_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProjectionOutcome:
    """Internal representation of an applied projection."""

    plan_id: int
    reading_order_id: int
    added_count: int
    updated_count: int
    kept_count: int
    total_positions: int


async def _load_owned_plan(db: AsyncSession, *, user_id: int, plan_id: int) -> ContinuityPlan:
    """Load a single plan without leaking another user's identifier."""
    plan = (
        await db.execute(
            select(ContinuityPlan).where(
                ContinuityPlan.id == plan_id,
                ContinuityPlan.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise _not_found(f"Continuity plan {plan_id} not found")
    return plan


async def _load_owned_reading_order(
    db: AsyncSession, *, user_id: int, reading_order_id: int
) -> ReadingOrder:
    """Load a single reading order scoped to the authenticated user."""
    order = (
        await db.execute(
            select(ReadingOrder).where(
                ReadingOrder.id == reading_order_id,
                ReadingOrder.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise _not_found(f"Reading order {reading_order_id} not found")
    return order


def _not_found(detail: str) -> Exception:
    """Build a 404 HTTPException without importing FastAPI in this module."""
    from fastapi import HTTPException

    return HTTPException(status_code=404, detail=detail)


def _conflict(detail: dict[str, object]) -> Exception:
    """Build a 409 HTTPException with a structured detail body."""
    from fastapi import HTTPException

    return HTTPException(status_code=409, detail=detail)


def _parse_plan_nodes(plan: ContinuityPlan) -> list[ContinuityPlanNode]:
    """Validate persisted JSON into typed nodes; reject malformed plans."""
    try:
        return [ContinuityPlanNode.model_validate(node) for node in plan.nodes_json]
    except ValueError as exc:
        raise _conflict(
            {
                "code": "malformed_plan",
                "plan_id": plan.id,
                "reason": str(exc),
            }
        ) from exc


def _flatten_plan(
    plan: ContinuityPlan,
    nodes: list[ContinuityPlanNode],
) -> tuple[list[ContinuityPlanNode], tuple[str, ...]]:
    """Apply the documented deterministic flattening policy.
    
    Sequential plans already enforce a single lane with contiguous positions;
    parallel (informational) plans are flattened lane by lane using the lane
    ``order`` as the primary key and ``position`` as the secondary key. The
    plan is intentionally not mutated - lanes/positions are read directly.
    """
    if plan.ordering_mode == "strict_sequential":
        # Validate strict sequential constraints
        if len(plan.lanes_json) != 1:
            raise ValueError("strict sequential plans must use exactly one lane")
        
        single_lane_id = plan.lanes_json[0]["id"]
        nodes_in_lane = [node for node in nodes if node.lane_id == single_lane_id]
        
        # Verify all nodes are in the single lane
        if len(nodes) != len(nodes_in_lane):
            raise ValueError("strict sequential plans must have all nodes in single lane")
            
        # Verify positions are contiguous starting at zero
        positions = sorted(node.position for node in nodes_in_lane)
        if positions != list(range(len(positions))):
            raise ValueError("strict sequential positions must be contiguous starting at zero")
            
        # Sort nodes by position
        sorted_nodes = sorted(nodes_in_lane, key=lambda node: node.position)
    else:
        # Informational plans: flatten lane by lane using lane order and position
        lane_orders = {lane["id"]: lane["order"] for lane in plan.lanes_json}
        sorted_nodes = sorted(
            nodes,
            key=lambda node: (lane_orders.get(node.lane_id, 0), node.position, node.id),
        )
    
    dropped = tuple(node.id for node in nodes if node.lane_id not in {lane["id"] for lane in plan.lanes_json})
    return sorted_nodes, dropped


async def _resolve_threads(
    db: AsyncSession, *, user_id: int, thread_ids: set[int]
) -> dict[int, str]:
    """Map thread identifiers to titles so callers see a human-readable preview."""
    if not thread_ids:
        return {}
    rows = await db.execute(
        select(Thread.id, Thread.title).where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
        )
    )
    return {row[0]: row[1] for row in rows.all()}


async def build_projection_plan(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    reading_order_id: int,
) -> ProjectionPlan:
    """Compute a deterministic projection without mutating any resource.

    The plan must be ordered lane-by-lane and position-by-position so that
    callers see exactly the same preview as the eventual confirm step.
    """
    plan = await _load_owned_plan(db, user_id=user_id, plan_id=plan_id)
    order = await _load_owned_reading_order(db, user_id=user_id, reading_order_id=reading_order_id)

    nodes = _parse_plan_nodes(plan)
    ordered_nodes, dropped_ids = _flatten_plan(plan, nodes)

    thread_ids = {node.ref_id for node in ordered_nodes if node.node_type == "thread"}
    thread_titles = await _resolve_threads(db, user_id=user_id, thread_ids=thread_ids)

    conflicts: list[ProjectionConflict] = []
    seen_thread_ids: set[int] = set()
    thread_positions: dict[int, list[int]] = {}
    preview_entries: list[ProjectionEntry] = []

    existing_rows = await db.execute(
        select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id == order.id)
    )
    existing = list(existing_rows.scalars())
    existing_positions: dict[int, int] = {item.thread_id: item.position for item in existing}

    for node in ordered_nodes:
        if node.node_type != "thread":
            conflicts.append(
                ProjectionConflict(
                    code="non_thread_node",
                    message=(
                        "Reading order projection only supports thread nodes; "
                        f"{node.node_type} node {node.id!r} cannot be projected."
                    ),
                    node_id=node.id,
                    thread_id=node.ref_id,
                )
            )
            continue
        thread_id = node.ref_id
        if thread_id in thread_titles:
            thread_positions.setdefault(thread_id, []).append(node.position)
            if thread_id in seen_thread_ids:
                conflicts.append(
                    ProjectionConflict(
                        code="duplicate_thread",
                        message=(
                            f"Thread {thread_id} appears multiple times in the plan; "
                            "deduplicate node positions before projection."
                        ),
                        node_id=node.id,
                        thread_id=thread_id,
                        existing_positions=sorted(thread_positions[thread_id]),
                    )
                )
                continue
            seen_thread_ids.add(thread_id)
        else:
            conflicts.append(
                ProjectionConflict(
                    code="missing_thread",
                    message=f"Thread {thread_id} from node {node.id!r} is not owned by the user.",
                    node_id=node.id,
                    thread_id=thread_id,
                )
            )
            continue

    if not conflicts:
        position = 1
        for node in ordered_nodes:
            if node.node_type != "thread" or node.ref_id not in thread_titles:
                continue
            thread_id = node.ref_id
            prior_position = existing_positions.get(thread_id)
            source: Literal["existing", "added", "updated"]
            if prior_position is None:
                source = "added"
            elif prior_position != position:
                source = "updated"
            else:
                source = "existing"
            preview_entries.append(
                ProjectionEntry(
                    thread_id=thread_id,
                    thread_title=thread_titles.get(thread_id),
                    position=position,
                    source=source,
                    source_node_id=node.id,
                )
            )
            position += 1
        total_positions = max(len(preview_entries), len(existing))
    else:
        preview_entries = []
        total_positions = len(existing)

    return ProjectionPlan(
        plan_id=plan.id,
        plan_name=plan.name,
        plan_ordering_mode=plan.ordering_mode,
        reading_order_id=order.id,
        reading_order_name=order.name,
        entries=tuple(preview_entries),
        conflicts=tuple(conflicts),
        total_positions=total_positions,
        dropped_node_ids=dropped_ids,
    )


async def apply_projection(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    reading_order_id: int,
) -> ProjectionOutcome:
    """Persist the projection atomically; rollback on any failure.

    The plan is reloaded and re-flattened so the confirmed result always
    matches the preview the caller reviewed. Any conflict or unrecoverable
    error rolls the transaction back so neither the plan nor the reading
    order change.
    """
    projection = await build_projection_plan(
        db,
        user_id=user_id,
        plan_id=plan_id,
        reading_order_id=reading_order_id,
    )
    if projection.conflicts:
        raise _conflict(
            {
                "code": "projection_conflicts",
                "conflicts": [
                    {
                        "code": conflict.code,
                        "node_id": conflict.node_id,
                        "thread_id": conflict.thread_id,
                        "message": conflict.message,
                        "existing_positions": conflict.existing_positions,
                    }
                    for conflict in projection.conflicts
                ],
            }
        )

    try:
        existing_rows = await db.execute(
            select(ReadingOrderItem).where(ReadingOrderItem.reading_order_id == reading_order_id)
        )
        existing = list(existing_rows.scalars())
        for item in existing:
            await db.delete(item)
        await db.flush()

        added = 0
        updated = 0
        kept = 0
        for entry in projection.entries:
            db.add(
                ReadingOrderItem(
                    reading_order_id=reading_order_id,
                    thread_id=entry.thread_id,
                    position=entry.position,
                    issue_number=None,
                )
            )
            if entry.source == "added":
                added += 1
            elif entry.source == "updated":
                updated += 1
            else:
                kept += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return ProjectionOutcome(
        plan_id=plan_id,
        reading_order_id=reading_order_id,
        added_count=added,
        updated_count=updated,
        kept_count=kept,
        total_positions=len(projection.entries),
    )


async def preview_to_response(projection: ProjectionPlan) -> ReadingOrderProjectionPreview:
    """Convert an internal projection into the API preview contract."""
    from app.schemas.reading_order import (
        ReadingOrderProjectionConflict,
        ReadingOrderProjectionEntry,
        ReadingOrderProjectionPreview,
    )

    return ReadingOrderProjectionPreview(
        plan_id=projection.plan_id,
        plan_name=projection.plan_name,
        plan_ordering_mode=projection.plan_ordering_mode,
        reading_order_id=projection.reading_order_id,
        reading_order_name=projection.reading_order_name,
        entries=[
            ReadingOrderProjectionEntry(
                thread_id=entry.thread_id,
                thread_title=entry.thread_title,
                position=entry.position,
                source=entry.source,
                source_node_id=entry.source_node_id,
            )
            for entry in projection.entries
        ],
        conflicts=[
            ReadingOrderProjectionConflict(
                code=conflict.code,
                message=conflict.message,
                node_id=conflict.node_id,
                thread_id=conflict.thread_id,
                existing_positions=conflict.existing_positions,
            )
            for conflict in projection.conflicts
        ],
        total_positions=projection.total_positions,
        dropped_node_ids=list(projection.dropped_node_ids),
    )


async def outcome_to_response(outcome: ProjectionOutcome) -> ReadingOrderProjectionResult:
    """Convert an internal outcome into the API confirm contract."""
    from app.schemas.reading_order import ReadingOrderProjectionResult

    return ReadingOrderProjectionResult(
        plan_id=outcome.plan_id,
        reading_order_id=outcome.reading_order_id,
        added_count=outcome.added_count,
        updated_count=outcome.updated_count,
        kept_count=outcome.kept_count,
        total_positions=outcome.total_positions,
    )
