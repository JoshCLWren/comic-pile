"""Compatibility adoption: convert a legacy ReadingOrder into a canonical ContinuityPlan.

ReadingOrders are flat thread-level lists (issue #1619). The canonical reader
order is the ContinuityPlan. This service provides one-way import without
mutating the source order. The adopted plan is the new owner of the ordering
intent; projection (plan -> reading_order) remains as export-only tooling.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode, ContinuityPlanWrite


async def _load_owned_order(db: AsyncSession, *, user_id: int, reading_order_id: int) -> ReadingOrder:
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
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Reading order {reading_order_id} not found")
    return order


def _raise_conflict(detail: dict[str, object]) -> None:
    """Raise a structured 409 with the given detail."""
    from fastapi import HTTPException

    raise HTTPException(status_code=409, detail=detail)


async def adopt_reading_order_to_plan(
    db: AsyncSession,
    *,
    user_id: int,
    reading_order_id: int,
    plan_name: str | None = None,
    lane_id: str = "adopted",
    lane_name: str = "Adopted",
) -> ContinuityPlan:
    """Create a canonical plan from one owned legacy reading order.

    Args:
        db: Async database session.
        user_id: Authenticated owner.
        reading_order_id: Legacy reading order to import.
        plan_name: Override for the resulting plan name. When ``None`` the
            source order name is preserved (or a fallback when blank).
        lane_id: Lane id for the single adopted lane.
        lane_name: Display name for the adopted lane.

    Returns:
        The newly persisted canonical ContinuityPlan. Caller commits.

    Raises:
        HTTPException: 404 when the order is not owned, 409 on duplicate
            thread ids or empty lane ids, 422 propagated from schema
            validation.
    """
    order = await _load_owned_order(db, user_id=user_id, reading_order_id=reading_order_id)
    items_result = await db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order.id)
        .order_by(ReadingOrderItem.position, ReadingOrderItem.id)
    )
    items = list(items_result.scalars())

    seen: set[int] = set()
    duplicates: list[int] = []
    for item in items:
        if item.thread_id in seen:
            duplicates.append(item.thread_id)
        else:
            seen.add(item.thread_id)
    if duplicates:
        _raise_conflict(
            {
                "code": "duplicate_thread",
                "reading_order_id": order.id,
                "duplicate_thread_ids": sorted(set(duplicates)),
                "message": "Reading order contains duplicate threads; deduplicate before adoption.",
            }
        )
    resolved_name = plan_name.strip() if isinstance(plan_name, str) and plan_name.strip() else order.name
    if not resolved_name or not resolved_name.strip():
        resolved_name = f"From reading order {order.id}"
    resolved_name = resolved_name.strip()

    if items:
        from app.models.thread import Thread

        owned_rows = await db.execute(
            select(Thread.id).where(Thread.id.in_({i.thread_id for i in items}), Thread.user_id == user_id)
        )
        owned_ids = {row[0] for row in owned_rows.all()}
        dangling = [item for item in items if item.thread_id not in owned_ids]
        if dangling:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail={"code": "dangling_plan_reference", "node_id": f"ro-{dangling[0].id}"},
            )

    lane = ContinuityPlanLane(id=lane_id, name=lane_name, order=0)
    nodes: list[ContinuityPlanNode] = []
    for idx, item in enumerate(sorted(items, key=lambda i: (i.position, i.id))):
        nodes.append(
            ContinuityPlanNode(
                id=f"ro-{item.id}",
                node_type="thread",
                ref_id=item.thread_id,
                lane_id=lane.id,
                position=idx,
            )
        )
    payload = ContinuityPlanWrite(name=resolved_name, ordering_mode="informational", lanes=[lane], nodes=nodes)
    plan = ContinuityPlan(
        user_id=user_id,
        name=payload.name,
        ordering_mode=payload.ordering_mode,
        lanes_json=[lane.model_dump() for lane in payload.lanes],
        nodes_json=[node.model_dump() for node in payload.nodes],
    )
    db.add(plan)
    await db.flush()
    return plan
