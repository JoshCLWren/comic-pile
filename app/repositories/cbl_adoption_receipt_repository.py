"""Query construction and persistence for CBL adoption receipts.

Repositories own SQLAlchemy access for :class:`~app.models.cbl_adoption_receipt.CblAdoptionReceipt`
and the legacy JSON provenance scan used to find plans adopted before receipts existed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_adoption_receipt import CblAdoptionReceipt
from app.models.continuity_plan import ContinuityPlan


def _placement_list(placements: object) -> list[dict[str, object]]:
    """Normalize stored CBL placement JSON into a list of dicts.

    Args:
        placements: Stored node placement value.

    Returns:
        Placement dicts; non-dict noise is discarded.
    """
    if isinstance(placements, dict):
        return [placements]
    if isinstance(placements, list):
        return [item for item in placements if isinstance(item, dict)]
    return []


async def find_adoption_plan(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
) -> ContinuityPlan | None:
    """Return the Reading Plan claimed for this user and CBL list, if any.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        cbl_source_list_id: CBL source list ID.

    Returns:
        The adopted plan, or ``None`` when this user has never claimed the list.
    """
    result = await db.execute(
        select(ContinuityPlan)
        .join(CblAdoptionReceipt, CblAdoptionReceipt.plan_id == ContinuityPlan.id)
        .where(
            CblAdoptionReceipt.user_id == user_id,
            CblAdoptionReceipt.cbl_source_list_id == cbl_source_list_id,
        )
    )
    return result.scalars().first()


async def insert_adoption_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    cbl_source_list_id: int,
    plan_id: int,
) -> CblAdoptionReceipt:
    """Insert the unique (user, list) claim inside the caller's transaction.

    The flush surfaces the unique-constraint race so the caller can converge on
    the winning receipt.

    Args:
        db: Async database session inside the adoption transaction.
        user_id: Owner user ID.
        cbl_source_list_id: CBL source list ID.
        plan_id: Reading Plan that owns this adoption.

    Returns:
        The persisted receipt.
    """
    receipt = CblAdoptionReceipt(
        user_id=user_id,
        cbl_source_list_id=cbl_source_list_id,
        plan_id=plan_id,
    )
    db.add(receipt)
    await db.flush()
    return receipt


async def find_plan_by_source_path(
    db: AsyncSession,
    *,
    user_id: int,
    source_path: str,
) -> ContinuityPlan | None:
    """Find a user-owned plan whose nodes already record this CBL source path.

    Used as a legacy fallback for plans adopted before receipts existed.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        source_path: CBL source path stored on plan nodes.

    Returns:
        The matching plan, or ``None``.
    """
    result = await db.execute(select(ContinuityPlan).where(ContinuityPlan.user_id == user_id))
    plans = result.scalars().all()
    for plan in plans:
        for node in plan.nodes_json or []:
            placements = _placement_list(node.get("source_cbl_placements"))
            if not placements:
                placements = _placement_list(node.get("source_cbl_placement"))
            if any(str(item.get("source_path")) == source_path for item in placements):
                return plan
    return None
